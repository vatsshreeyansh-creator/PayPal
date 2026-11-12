"""Domain wallet service managing deposits, conversions, and unified cash ledger history."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import uuid4
from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import Account, CashLedgerEntry, Instrument, Order, PaymentDepositRecord
from paypal_service import (
    PayPalClient,
    PayPalError,
    PayPalOrderAlreadyCaptured,
    PayPalNetworkError,
    InvalidApprovalUrlError,
    extract_and_validate_approval_url,
)
from portfolio_service import get_cash_balance
from schemas import (
    PayPalCaptureOrderResponse,
    PayPalCreateOrderRequest,
    PayPalCreateOrderResponse,
    PayPalCancelOrderResponse,
    WalletHistoryItem,
    WalletHistoryResponse,
    WalletSummaryResponse,
)

CENT = Decimal("0.01")
RATE_PRECISION = Decimal("0.000001")
CAPTURE_CLAIM_TIMEOUT_SECONDS = 120  # 2 minutes claim lease
MAX_SETTLEMENT_ROUNDING_TOLERANCE = Decimal("0.01")  # Exactly 1 paisa (0.01 INR)


def _cash(value: Decimal | str | None) -> str:
    if value is None:
        return "0.00"
    return f"{Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP):.2f}"


def _rate_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{Decimal(value):.6f}"


class DepositNotFound(Exception): pass
class IdempotencyConflict(Exception): pass
class InvalidDepositState(Exception): pass
class DepositCapturePending(Exception): pass
class DepositOrderCreationPending(Exception): pass
class CurrencyMismatch(Exception): pass
class ConversionVerificationFailed(Exception): pass
class UnresolvedDepositConflict(Exception): pass


def _same_create_request(deposit: PaymentDepositRecord, request: PayPalCreateOrderRequest) -> bool:
    return (
        deposit.payment_amount == Decimal(request.amount) and
        deposit.payment_currency == request.currency
    )


def create_deposit_intent(session: Session, account_id: str,
                          request: PayPalCreateOrderRequest) -> PaymentDepositRecord:
    """Phase 1 of order creation: Idempotently creates or reloads local intent before calling PayPal."""
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    account = session.scalar(select(Account).where(Account.account_id == account_id))
    if account is None:
        session.rollback()
        raise RuntimeError("Demo account is not initialized")

    if request.currency != "USD":
        session.rollback()
        raise CurrencyMismatch("Payment currency must be USD for international deposits")

    req_amount = Decimal(request.amount).quantize(CENT, rounding=ROUND_HALF_UP)
    if req_amount <= 0:
        session.rollback()
        raise ValueError("Deposit amount must be positive")

    # Fast idempotency read: return matching deposit if replayed with identical request
    existing = session.scalar(
        select(PaymentDepositRecord).where(
            PaymentDepositRecord.account_id == account.id,
            PaymentDepositRecord.idempotency_key == request.idempotency_key
        )
    )
    if existing is not None:
        if not _same_create_request(existing, request):
            session.rollback()
            raise IdempotencyConflict("Idempotency key was already used for a different deposit request")
        session.commit()
        return existing

    # Mandatory protection: check if account has any unresolved deposit.
    # An account is blocked if any deposit is NOT COMPLETED and NOT provider-confirmed terminal.
    unresolved = session.scalar(
        select(PaymentDepositRecord).where(
            PaymentDepositRecord.account_id == account.id,
            PaymentDepositRecord.status != "COMPLETED",
            PaymentDepositRecord.is_provider_confirmed_terminal.is_(False)
        ).order_by(PaymentDepositRecord.created_at.desc())
    )
    if unresolved is not None:
        session.rollback()
        unresolved_ref = unresolved.paypal_order_id or unresolved.deposit_id
        raise UnresolvedDepositConflict(
            f"An unresolved deposit ({unresolved_ref}) in status '{unresolved.status}' already exists for this account. Please complete, cancel, or reconcile it before initiating a new deposit."
        )

    deposit = PaymentDepositRecord(
        deposit_id=str(uuid4()),
        account_id=account.id,
        idempotency_key=request.idempotency_key,
        provider="PAYPAL",
        paypal_order_id=None,
        payment_amount=req_amount,
        payment_currency="USD",
        wallet_currency="INR",
        status="INTENT_CREATED"
    )
    session.add(deposit)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(PaymentDepositRecord).where(
                PaymentDepositRecord.account_id == account.id,
                PaymentDepositRecord.idempotency_key == request.idempotency_key
            )
        )
        if existing is not None:
            if not _same_create_request(existing, request):
                raise IdempotencyConflict("Idempotency key was already used for a different deposit request")
            return existing
        raise

    return deposit


CREATE_ORDER_CLAIM_TIMEOUT_SECONDS = 60  # 60s lease for order creation


def claim_deposit_for_order_creation(session: Session, deposit_id: str) -> tuple[PaymentDepositRecord, bool]:
    """Atomically claims an intent for outbound PayPal create_order call under SQLite BEGIN IMMEDIATE.
    Returns (deposit, already_has_order)."""
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    deposit = session.scalar(select(PaymentDepositRecord).where(PaymentDepositRecord.deposit_id == deposit_id))
    if deposit is None:
        session.rollback()
        raise DepositNotFound("Deposit record was not found")

    if deposit.paypal_order_id is not None:
        session.rollback()
        return deposit, True

    now = datetime.now(timezone.utc)
    if deposit.claimed_at is not None and deposit.status == "INTENT_CREATED":
        claimed_at_utc = deposit.claimed_at.replace(tzinfo=timezone.utc) if deposit.claimed_at.tzinfo is None else deposit.claimed_at
        elapsed = (now - claimed_at_utc).total_seconds()
        if elapsed < CREATE_ORDER_CLAIM_TIMEOUT_SECONDS:
            session.rollback()
            raise DepositOrderCreationPending("Order creation is currently in progress. Please retry shortly.")
        else:
            # Lease expired! Ambiguous provider outcome: move to REQUIRES_RECONCILIATION
            deposit.status = "REQUIRES_RECONCILIATION"
            deposit.is_provider_confirmed_terminal = False
            deposit.failure_code = "ORDER_CREATION_CLAIM_TIMEOUT"
            deposit.failure_reason = "Order creation claim lease expired; provider outcome requires verification"
            session.commit()
            raise DepositOrderCreationPending("Order creation claim lease expired; deposit preserved for verification.")

    deposit.claimed_at = now
    session.commit()
    return deposit, False


def bind_paypal_order(session: Session, deposit_id: str, paypal_order_id: str,
                      approval_url: str | None = None) -> PaymentDepositRecord:
    """Binds the created external PayPal order ID to the local deposit intent."""
    deposit = session.scalar(select(PaymentDepositRecord).where(PaymentDepositRecord.deposit_id == deposit_id))
    if deposit is None:
        raise DepositNotFound("Deposit record was not found")

    deposit.paypal_order_id = paypal_order_id
    if approval_url is not None:
        deposit.approval_url = approval_url
    deposit.status = "CREATED"
    deposit.claimed_at = None  # Reset claim lease on successful binding
    session.commit()
    return deposit


def initiate_paypal_deposit(session: Session, paypal_client: PayPalClient,
                            account_id: str, request: PayPalCreateOrderRequest) -> PayPalCreateOrderResponse:
    """Full workflow: local intent -> PayPal call outside DB -> order association."""
    deposit = create_deposit_intent(session, account_id, request)

    raw_mode = getattr(paypal_client, "mode", None)
    payment_mode = "mock" if raw_mode == "mock" else ("sandbox" if raw_mode == "sandbox" else None)

    # Atomically claim intent for order creation
    deposit, already_has_order = claim_deposit_for_order_creation(session, deposit.deposit_id)
    if already_has_order:
        return PayPalCreateOrderResponse(
            deposit_id=deposit.deposit_id,
            paypal_order_id=deposit.paypal_order_id,
            status=deposit.status,
            payment_amount=_cash(deposit.payment_amount),
            payment_currency="USD",
            payment_mode=payment_mode,
            approval_url=deposit.approval_url
        )

    # Call PayPal outside any database transaction
    request_id = f"create-{deposit.deposit_id}"
    try:
        paypal_order = paypal_client.create_order(
            amount=deposit.payment_amount,
            currency="USD",
            idempotency_key=request_id
        )
        paypal_order_id = paypal_order.get("id")
        if not paypal_order_id:
            raise PayPalError("PayPal returned an order response without an ID")
    except Exception as exc:
        deposit = session.scalar(select(PaymentDepositRecord).where(PaymentDepositRecord.deposit_id == deposit.deposit_id))
        if deposit:
            # Distinguish definitive provider rejection from ambiguous transport/provider failure
            is_definitive_rejection = False
            if isinstance(exc, PayPalError) and not isinstance(exc, PayPalNetworkError):
                if exc.status_code is not None and 400 <= exc.status_code < 500:
                    is_definitive_rejection = True

            if is_definitive_rejection:
                deposit.status = "FAILED"
                deposit.is_provider_confirmed_terminal = True
                deposit.failure_code = "PAYPAL_CREATE_FAILED"
                deposit.failure_reason = str(exc)[:250]
            else:
                # Ambiguous transport or 5xx provider failure:
                # PayPal may have created the order; preserve unresolved reconciliation state
                deposit.status = "REQUIRES_RECONCILIATION"
                deposit.is_provider_confirmed_terminal = False
                deposit.failure_code = "ORDER_CREATION_UNCERTAIN"
                deposit.failure_reason = str(exc)[:250]
            session.commit()
        raise

    # Extract and validate authoritative approval URL
    approval_url = None
    if payment_mode != "mock" or "links" in paypal_order:
        try:
            approval_url = extract_and_validate_approval_url(paypal_order, is_sandbox=True)
        except InvalidApprovalUrlError as exc:
            # Preserve local deposit record in database for operator reconciliation
            bind_paypal_order(session, deposit.deposit_id, paypal_order_id, approval_url=None)
            deposit = session.scalar(select(PaymentDepositRecord).where(PaymentDepositRecord.deposit_id == deposit.deposit_id))
            if deposit:
                deposit.status = "REQUIRES_RECONCILIATION"
                deposit.is_provider_confirmed_terminal = False
                deposit.failure_code = "INVALID_APPROVAL_URL"
                deposit.failure_reason = f"Provider order {paypal_order_id} created, but approval URL validation failed: {exc}"[:250]
                session.commit()
            raise PayPalError(
                f"PayPal order created ({paypal_order_id}), but approval URL validation failed: {exc}. Deposit preserved for operator reconciliation."
            ) from exc

    deposit = bind_paypal_order(session, deposit.deposit_id, paypal_order_id, approval_url=approval_url)
    return PayPalCreateOrderResponse(
        deposit_id=deposit.deposit_id,
        paypal_order_id=deposit.paypal_order_id,
        status="CREATED",
        payment_amount=_cash(deposit.payment_amount),
        payment_currency="USD",
        payment_mode=payment_mode,
        approval_url=approval_url
    )


def claim_deposit_for_capture(session: Session, account_id: str,
                              paypal_order_id: str,
                              allow_reclaim_for_recovery: bool = False) -> tuple[PaymentDepositRecord, bool]:
    """Phase 1 of capture: short DB transaction to transition to CAPTURE_PENDING.
    Returns (deposit, already_completed)."""
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    account = session.scalar(select(Account).where(Account.account_id == account_id))
    if account is None:
        session.rollback()
        raise RuntimeError("Demo account is not initialized")

    deposit = session.scalar(
        select(PaymentDepositRecord).where(
            PaymentDepositRecord.account_id == account.id,
            PaymentDepositRecord.paypal_order_id == paypal_order_id
        )
    )
    if deposit is None:
        session.rollback()
        raise DepositNotFound("No deposit found with the given PayPal order ID")

    if deposit.status == "COMPLETED":
        session.rollback()
        return deposit, True

    if deposit.status in ("FAILED", "CANCELLED"):
        session.rollback()
        raise InvalidDepositState(f"Deposit is in terminal status {deposit.status} and cannot be captured")

    now = datetime.now(timezone.utc)

    if deposit.status == "CAPTURE_PENDING":
        if deposit.claimed_at is not None:
            claimed_at_utc = deposit.claimed_at.replace(tzinfo=timezone.utc) if deposit.claimed_at.tzinfo is None else deposit.claimed_at
            elapsed = (now - claimed_at_utc).total_seconds()
            if elapsed < CAPTURE_CLAIM_TIMEOUT_SECONDS and not allow_reclaim_for_recovery:
                session.rollback()
                raise DepositCapturePending("Payment capture is currently in progress. Please retry shortly.")
            elif elapsed >= CAPTURE_CLAIM_TIMEOUT_SECONDS and not allow_reclaim_for_recovery:
                deposit.status = "REQUIRES_RECONCILIATION"
                deposit.failure_code = "CLAIM_TIMEOUT"
                deposit.failure_reason = "Capture claim lease expired; deposit requires reconciliation"
                session.commit()
                raise DepositCapturePending("Capture claim lease expired; deposit moved to reconciliation.")
        else:
            if not allow_reclaim_for_recovery:
                session.rollback()
                raise DepositCapturePending("Payment capture is currently in progress. Please retry shortly.")

    deposit.status = "CAPTURE_PENDING"
    deposit.claimed_at = now
    session.commit()
    return deposit, False


def _parse_and_verify_capture_data(deposit: PaymentDepositRecord,
                                   capture_data: dict[str, Any] | None,
                                   network_timeout: bool = False,
                                   provider_error_msg: str | None = None) -> dict[str, Any]:
    """Parse and strictly verify PayPal capture response data."""
    res: dict[str, Any] = {
        "verified_capture_id": None,
        "verified_gross_amount": None,
        "verified_fee_amount": None,
        "verified_fee_currency": None,
        "verified_fee_in_rec": None,
        "verified_fee_in_rec_curr": None,
        "verified_net_amount": None,
        "verified_exchange_rate": None,
        "verified_rate_source": None,
        "verified_rate_target": None,
        "verified_receivable_amount": None,
        "conversion_valid": False,
        "verification_error": None,
        "network_timeout": network_timeout,
        "provider_error_msg": provider_error_msg,
    }

    if not capture_data:
        res["verification_error"] = provider_error_msg or "No capture data received from PayPal"
        return res

    units = capture_data.get("purchase_units", [])
    if not units:
        res["verification_error"] = "No purchase units found in PayPal response"
        return res

    payments = units[0].get("payments", {})
    captures = payments.get("captures", [])
    if not captures:
        res["verification_error"] = "No captures found in PayPal purchase unit payments"
        return res

    cap = captures[0]
    cap_id = cap.get("id")
    if not cap_id:
        res["verification_error"] = "PayPal capture object is missing capture ID"
        return res
    res["verified_capture_id"] = cap_id
    cap_status = cap.get("status")

    if cap_status != "COMPLETED":
        res["verification_error"] = f"PayPal capture status is {cap_status} (not COMPLETED)"
        return res

    amt_obj = cap.get("amount", {})
    gross_val = Decimal(amt_obj.get("value", "0.00")).quantize(CENT, rounding=ROUND_HALF_UP)
    gross_curr = amt_obj.get("currency_code", "")

    if gross_curr != deposit.payment_currency or gross_val != deposit.payment_amount:
        res["verification_error"] = f"Gross amount/currency mismatch: {gross_val} {gross_curr} vs expected {deposit.payment_amount} {deposit.payment_currency}"
        return res

    res["verified_gross_amount"] = gross_val
    breakdown = cap.get("seller_receivable_breakdown")
    if not breakdown:
        res["verification_error"] = "PayPal capture is missing seller_receivable_breakdown"
        return res

    fee_obj = breakdown.get("paypal_fee", {})
    fee_val = Decimal(fee_obj.get("value", "0.00")).quantize(CENT, rounding=ROUND_HALF_UP)
    fee_curr = fee_obj.get("currency_code", "USD")
    res["verified_fee_amount"] = fee_val
    res["verified_fee_currency"] = fee_curr

    net_obj = breakdown.get("net_amount", {})
    net_val = Decimal(net_obj.get("value", "0.00")).quantize(CENT, rounding=ROUND_HALF_UP)
    res["verified_net_amount"] = net_val

    # Strict financial check: gross minus fee must equal net
    expected_net = (gross_val - fee_val).quantize(CENT, rounding=ROUND_HALF_UP)
    if net_val != expected_net:
        res["verification_error"] = f"Net amount {net_val} does not equal gross {gross_val} minus fee {fee_val} ({expected_net})"
        return res

    # Inspect optional paypal_fee_in_receivable_currency
    fee_rec_obj = breakdown.get("paypal_fee_in_receivable_currency")
    if fee_rec_obj:
        res["verified_fee_in_rec"] = Decimal(fee_rec_obj.get("value", "0.00")).quantize(CENT, rounding=ROUND_HALF_UP)
        res["verified_fee_in_rec_curr"] = fee_rec_obj.get("currency_code", "INR")

    rec_obj = breakdown.get("receivable_amount", {})
    rec_val = Decimal(rec_obj.get("value", "0.00")).quantize(CENT, rounding=ROUND_HALF_UP)
    rec_curr = rec_obj.get("currency_code", "")

    rate_obj = breakdown.get("exchange_rate", {})
    rate_val = Decimal(rate_obj.get("value", "0.000000"))
    rate_source = rate_obj.get("source_currency", "")
    rate_target = rate_obj.get("target_currency", "")
    res["verified_rate_source"] = rate_source
    res["verified_rate_target"] = rate_target
    res["verified_exchange_rate"] = rate_val

    if rec_curr != "INR" or rate_source != "USD" or rate_target != "INR":
        res["verification_error"] = f"Target currency is {rec_curr} (expected INR) or rate currencies invalid ({rate_source}->{rate_target})"
        return res

    if rec_val <= 0 or rate_val <= 0:
        res["verification_error"] = "Receivable amount or exchange rate is non-positive"
        return res

    # Narrow financial check: tolerance at most 1 paisa (0.01 INR)
    calc_rec = (net_val * rate_val).quantize(CENT, rounding=ROUND_HALF_UP)
    diff = abs(calc_rec - rec_val)
    if diff > MAX_SETTLEMENT_ROUNDING_TOLERANCE:
        res["verification_error"] = f"Excessive conversion discrepancy: receivable {rec_val} INR deviates by {diff} INR from net {net_val} USD * rate {rate_val} ({calc_rec} INR)"
        return res

    res["verified_receivable_amount"] = rec_val
    res["conversion_valid"] = True
    return res


def _settle_verified_capture(session: Session, account: Account, deposit_id: str,
                             paypal_order_id: str, parsed: dict[str, Any]) -> tuple[PayPalCaptureOrderResponse, bool]:
    """Phase 2 of capture / recovery: short DB transaction for atomic ledger credit."""
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    deposit = session.scalar(
        select(PaymentDepositRecord).where(
            PaymentDepositRecord.account_id == account.id,
            PaymentDepositRecord.paypal_order_id == paypal_order_id
        )
    )
    if deposit.status == "COMPLETED":
        session.rollback()
        return _make_capture_response(deposit, get_cash_balance(session, account)), False

    if parsed["conversion_valid"] and parsed["verified_receivable_amount"] is not None:
        deposit.status = "COMPLETED"
        deposit.is_provider_confirmed_terminal = True
        deposit.paypal_capture_id = parsed["verified_capture_id"]
        deposit.paypal_fee_amount = parsed["verified_fee_amount"]
        deposit.paypal_fee_currency = parsed["verified_fee_currency"]
        deposit.paypal_fee_in_receivable_currency = parsed["verified_fee_in_rec"]
        deposit.paypal_fee_in_receivable_currency_code = parsed["verified_fee_in_rec_curr"]
        deposit.net_payment_amount = parsed["verified_net_amount"]
        deposit.exchange_rate = parsed["verified_exchange_rate"]
        deposit.exchange_rate_source_currency = parsed["verified_rate_source"]
        deposit.exchange_rate_target_currency = parsed["verified_rate_target"]
        deposit.wallet_credit_amount = parsed["verified_receivable_amount"]
        deposit.completed_at = datetime.now(timezone.utc)
        deposit.failure_code = None
        deposit.failure_reason = None

        # Append exactly one CashLedgerEntry
        session.add(CashLedgerEntry(
            account_id=account.id,
            order_id=None,
            entry_key=f"PAYPAL_DEPOSIT:{deposit.paypal_order_id}",
            entry_type="DEPOSIT",
            amount=parsed["verified_receivable_amount"]
        ))
        try:
            session.commit()
            created = True
        except IntegrityError:
            session.rollback()
            deposit = session.scalar(select(PaymentDepositRecord).where(PaymentDepositRecord.deposit_id == deposit.deposit_id))
            return _make_capture_response(deposit, get_cash_balance(session, account)), False
    elif parsed["network_timeout"]:
        deposit.status = "REQUIRES_RECONCILIATION"
        deposit.is_provider_confirmed_terminal = False
        deposit.failure_code = "NETWORK_TIMEOUT"
        deposit.failure_reason = parsed["provider_error_msg"] or "Connection timed out during capture"
        if parsed["verified_capture_id"]:
            deposit.paypal_capture_id = parsed["verified_capture_id"]
        session.commit()
        created = False
    elif parsed["verification_error"]:
        # Capture was dispatched; any verification or response failure requires reconciliation
        deposit.status = "REQUIRES_RECONCILIATION"
        deposit.is_provider_confirmed_terminal = False
        deposit.failure_code = "CONVERSION_VERIFICATION_FAILED" if parsed["verified_capture_id"] else "CAPTURE_RESPONSE_ERROR"
        deposit.failure_reason = parsed["verification_error"] or parsed["provider_error_msg"]
        if parsed["verified_capture_id"]:
            deposit.paypal_capture_id = parsed["verified_capture_id"]
        session.commit()
        created = False
    else:
        # Ambiguous capture outcome: never set FAILED; preserve unresolved state for operator reconciliation
        deposit.status = "REQUIRES_RECONCILIATION"
        deposit.is_provider_confirmed_terminal = False
        deposit.failure_code = "CAPTURE_UNCERTAIN"
        deposit.failure_reason = parsed["provider_error_msg"] or "Capture outcome uncertain; provider response missing or incomplete"
        if parsed["verified_capture_id"]:
            deposit.paypal_capture_id = parsed["verified_capture_id"]
        session.commit()
        created = False

    new_balance = get_cash_balance(session, account)
    return _make_capture_response(deposit, new_balance), created


def execute_paypal_capture(session: Session, paypal_client: PayPalClient,
                           account_id: str, paypal_order_id: str) -> tuple[PayPalCaptureOrderResponse, bool]:
    """Full two-phase capture workflow with verified USD-to-INR receivable conversion and atomic ledger credit."""
    deposit, already_completed = claim_deposit_for_capture(session, account_id, paypal_order_id)
    account = session.scalar(select(Account).where(Account.account_id == account_id))

    if already_completed:
        return _make_capture_response(deposit, get_cash_balance(session, account)), False

    capture_request_id = f"capture-{deposit.deposit_id}"
    capture_data = None
    already_captured_error = False
    network_timeout = False
    provider_error_msg = None

    # Step 2: Call PayPal outside DB transaction
    try:
        capture_data = paypal_client.capture_order(paypal_order_id, capture_request_id)
    except PayPalOrderAlreadyCaptured:
        already_captured_error = True
    except PayPalNetworkError as exc:
        network_timeout = True
        provider_error_msg = str(exc)[:250]
    except PayPalError as exc:
        provider_error_msg = str(exc)[:250]
    except Exception as exc:
        provider_error_msg = f"Unexpected capture error: {exc}"[:250]

    # If ORDER_ALREADY_CAPTURED, fetch the order details directly from PayPal
    if already_captured_error:
        try:
            capture_data = paypal_client.get_order(paypal_order_id)
        except Exception as exc:
            network_timeout = True
            provider_error_msg = f"Failed to retrieve order after already captured: {exc}"[:250]

    # Step 3: Parse and strictly verify capture data
    parsed = _parse_and_verify_capture_data(deposit, capture_data, network_timeout, provider_error_msg)

    # Step 4: Short DB transaction 2 (Atomic Ledger Credit)
    return _settle_verified_capture(session, account, deposit.deposit_id, paypal_order_id, parsed)


def cancel_paypal_deposit(session: Session, paypal_client: PayPalClient, account_id: str,
                          paypal_order_id: str) -> PayPalCancelOrderResponse:
    """Safely cancels a deposit only upon authoritative provider confirmation that no payment can occur."""
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    account = session.scalar(select(Account).where(Account.account_id == account_id))
    if account is None:
        session.rollback()
        raise RuntimeError("Demo account is not initialized")

    deposit = session.scalar(
        select(PaymentDepositRecord).where(
            PaymentDepositRecord.account_id == account.id,
            PaymentDepositRecord.paypal_order_id == paypal_order_id
        )
    )
    if deposit is None:
        session.rollback()
        raise DepositNotFound("Deposit record was not found")

    if deposit.status == "CANCELLED" and deposit.is_provider_confirmed_terminal:
        session.rollback()
        return PayPalCancelOrderResponse(
            deposit_id=deposit.deposit_id,
            paypal_order_id=deposit.paypal_order_id or "",
            status="CANCELLED"
        )

    if deposit.status == "COMPLETED":
        session.rollback()
        raise InvalidDepositState("Deposit is already completed and cannot be cancelled.")

    if not deposit.paypal_order_id:
        deposit.status = "REQUIRES_RECONCILIATION"
        deposit.is_provider_confirmed_terminal = False
        deposit.failure_code = "INTENT_CANCELLATION_UNCERTAIN"
        deposit.failure_reason = "Deposit has no associated PayPal order ID; provider outcome requires investigation"
        session.commit()
        raise InvalidDepositState("Deposit intent has no associated PayPal order ID but may have an in-flight provider request. Deposit marked for reconciliation.")

    # Query PayPal order status outside write transaction
    session.commit()

    try:
        order_data = paypal_client.get_order(deposit.paypal_order_id)
        order_status = order_data.get("status")
    except Exception as exc:
        deposit = session.scalar(select(PaymentDepositRecord).where(PaymentDepositRecord.deposit_id == deposit.deposit_id))
        if deposit:
            deposit.status = "REQUIRES_RECONCILIATION"
            deposit.is_provider_confirmed_terminal = False
            deposit.failure_code = "CANCELLATION_UNCERTAIN"
            deposit.failure_reason = f"Provider query failed during cancellation: {exc}"[:250]
            session.commit()
        raise InvalidDepositState("Cancellation could not be confirmed with PayPal due to provider/network error. Deposit preserved as unresolved.")

    # Re-acquire lock to commit cancellation decision
    deposit = session.scalar(select(PaymentDepositRecord).where(PaymentDepositRecord.deposit_id == deposit.deposit_id))

    if order_status in ("COMPLETED", "APPROVED"):
        deposit.status = "REQUIRES_RECONCILIATION"
        deposit.is_provider_confirmed_terminal = False
        deposit.failure_code = "ORDER_NOT_CANCELLABLE"
        deposit.failure_reason = f"PayPal order is in status '{order_status}' and cannot be cancelled"
        session.commit()
        raise InvalidDepositState(f"Deposit cannot be cancelled because PayPal order is already {order_status}.")

    elif order_status in ("VOIDED", "EXPIRED"):
        # Authoritative provider-confirmed terminal cancellation
        deposit.status = "CANCELLED"
        deposit.is_provider_confirmed_terminal = True
        deposit.failure_code = f"PAYPAL_ORDER_{order_status}"
        deposit.failure_reason = f"PayPal authoritatively confirmed order status is {order_status}"
        session.commit()
        return PayPalCancelOrderResponse(
            deposit_id=deposit.deposit_id,
            paypal_order_id=deposit.paypal_order_id or "",
            status="CANCELLED"
        )
    else:
        # e.g. CREATED: PayPal Orders v2 does not provide an endpoint to actively cancel an unapproved CAPTURE order.
        # The order remains active on PayPal and could still be approved by the customer.
        deposit.status = "REQUIRES_RECONCILIATION"
        deposit.is_provider_confirmed_terminal = False
        deposit.failure_code = "CANCELLATION_PENDING_PROVIDER_EXPIRY"
        deposit.failure_reason = "PayPal order remains active in CREATED status; cancellation cannot be confirmed until expired by PayPal."
        session.commit()
        raise InvalidDepositState("PayPal order remains active in CREATED status and cannot be cancelled via API until expired by PayPal. Deposit preserved as unresolved.")


def _make_capture_response(deposit: PaymentDepositRecord,
                           cash_balance: Decimal) -> PayPalCaptureOrderResponse:
    return PayPalCaptureOrderResponse(
        deposit_id=deposit.deposit_id,
        paypal_order_id=deposit.paypal_order_id or "",
        paypal_capture_id=deposit.paypal_capture_id,
        status=deposit.status,
        payment_amount=_cash(deposit.payment_amount),
        payment_currency="USD",
        paypal_fee_amount=_cash(deposit.paypal_fee_amount) if deposit.paypal_fee_amount is not None else None,
        paypal_fee_currency=deposit.paypal_fee_currency,
        paypal_fee_in_receivable_currency=_cash(deposit.paypal_fee_in_receivable_currency) if deposit.paypal_fee_in_receivable_currency is not None else None,
        paypal_fee_in_receivable_currency_code=deposit.paypal_fee_in_receivable_currency_code,
        net_payment_amount=_cash(deposit.net_payment_amount) if deposit.net_payment_amount is not None else None,
        exchange_rate=_rate_str(deposit.exchange_rate),
        exchange_rate_source_currency=deposit.exchange_rate_source_currency,
        exchange_rate_target_currency=deposit.exchange_rate_target_currency,
        wallet_credit_amount=_cash(deposit.wallet_credit_amount) if deposit.wallet_credit_amount is not None else None,
        wallet_currency="INR",
        updated_cash_balance=_cash(cash_balance),
        failure_code=deposit.failure_code,
        failure_reason=deposit.failure_reason,
        completed_at=deposit.completed_at
    )


def get_wallet_summary(session: Session, account_id: str,
                       payment_mode: str | None = None) -> WalletSummaryResponse:
    account = session.scalar(select(Account).where(Account.account_id == account_id))
    if account is None:
        raise LookupError("Demo account is not initialized")

    cash = get_cash_balance(session, account)
    total_dep = session.scalar(
        select(func.coalesce(func.sum(PaymentDepositRecord.wallet_credit_amount), 0))
        .where(
            PaymentDepositRecord.account_id == account.id,
            PaymentDepositRecord.status == "COMPLETED"
        )
    )
    validated_mode = "mock" if payment_mode == "mock" else ("sandbox" if payment_mode == "sandbox" else None)
    return WalletSummaryResponse(
        account_id=account.account_id,
        currency="INR",
        cash_balance=_cash(cash),
        total_deposited=_cash(Decimal(total_dep)),
        payment_mode=validated_mode
    )


def list_wallet_history(session: Session, account_id: str) -> WalletHistoryResponse:
    account = session.scalar(select(Account).where(Account.account_id == account_id))
    if account is None:
        raise LookupError("Demo account is not initialized")

    entries = session.execute(
        select(CashLedgerEntry, Order, Instrument)
        .outerjoin(Order, CashLedgerEntry.order_id == Order.order_id)
        .outerjoin(Instrument, Order.instrument_id == Instrument.id)
        .where(CashLedgerEntry.account_id == account.id)
        .order_by(CashLedgerEntry.created_at.desc(), CashLedgerEntry.id.desc())
    ).all()

    # Preload completed deposit records for this account
    deposits = {
        f"PAYPAL_DEPOSIT:{d.paypal_order_id}": d
        for d in session.scalars(
            select(PaymentDepositRecord).where(
                PaymentDepositRecord.account_id == account.id,
                PaymentDepositRecord.paypal_order_id.is_not(None)
            )
        ).all()
    }

    items = []
    for entry, order, instrument in entries:
        raw_type = entry.entry_type
        payment_amount = None
        payment_currency = None
        exchange_rate = None
        reference_id = None

        if raw_type == "INITIAL_CASH":
            category = "INITIAL_CASH"
            desc = "Initial demo account balance"
        elif raw_type == "BUY":
            category = "STOCK_BUY"
            sym = instrument.symbol if instrument else "NSE"
            qty = order.quantity if order else "?"
            desc = f"Bought {qty} shares of {sym}"
            reference_id = entry.order_id
        elif raw_type == "SELL":
            category = "STOCK_SELL"
            sym = instrument.symbol if instrument else "NSE"
            qty = order.quantity if order else "?"
            desc = f"Sold {qty} shares of {sym}"
            reference_id = entry.order_id
        elif raw_type == "DEPOSIT":
            category = "DEPOSIT"
            dep = deposits.get(entry.entry_key)
            if dep:
                payment_amount = _cash(dep.payment_amount)
                payment_currency = dep.payment_currency
                exchange_rate = _rate_str(dep.exchange_rate)
                reference_id = dep.paypal_order_id
                desc = f"PayPal deposit ({payment_amount} {payment_currency} converted to {entry.amount:.2f} INR)"
            else:
                desc = "PayPal deposit"
                reference_id = entry.entry_key.replace("PAYPAL_DEPOSIT:", "")
        else:
            category = "DEPOSIT"
            desc = f"Cash movement ({raw_type})"

        amt_sign = f"+{Decimal(entry.amount):.2f}" if entry.amount > 0 else f"{Decimal(entry.amount):.2f}"
        items.append(WalletHistoryItem(
            entry_id=entry.id,
            entry_key=entry.entry_key,
            category=category,
            amount=amt_sign,
            currency="INR",
            description=desc,
            reference_id=reference_id,
            payment_amount=payment_amount,
            payment_currency=payment_currency,
            exchange_rate=exchange_rate,
            created_at=entry.created_at
        ))

    return WalletHistoryResponse(items=items)


def reconcile_deposit(session: Session, paypal_client: PayPalClient,
                      account_id: str, deposit_id: str) -> PaymentDepositRecord:
    """Recovery method for deposits requiring reconciliation.
    Inspects provider state; if already completed, settles existing capture without re-capture."""
    account = session.scalar(select(Account).where(Account.account_id == account_id))
    if account is None:
        raise LookupError("Demo account is not initialized")

    deposit = session.scalar(
        select(PaymentDepositRecord).where(
            PaymentDepositRecord.account_id == account.id,
            PaymentDepositRecord.deposit_id == deposit_id
        )
    )
    if deposit is None:
        raise DepositNotFound("Deposit record was not found")

    if deposit.status == "COMPLETED":
        return deposit

    if not deposit.paypal_order_id:
        # Check provider idempotency retention (PayPal retains PayPal-Request-Id for 72 hours)
        now = datetime.now(timezone.utc)
        created_at_utc = deposit.created_at.replace(tzinfo=timezone.utc) if deposit.created_at.tzinfo is None else deposit.created_at
        age_hours = (now - created_at_utc).total_seconds() / 3600.0

        if age_hours > 72.0:
            # Retention expired: automatic create_order retry would create a duplicate order rather than recover!
            deposit.status = "REQUIRES_RECONCILIATION"
            deposit.is_provider_confirmed_terminal = False
            deposit.failure_code = "ORDER_RECOVERY_EXPIRED_UNCERTAIN"
            deposit.failure_reason = (
                f"Deposit intent was created {age_hours:.1f}h ago (>72h idempotency retention). "
                "Provider outcome is uncertain; automatic retry cannot guarantee idempotent replay. "
                "Operator must manually check PayPal Sandbox dashboard."
            )
            session.commit()
            return deposit

        # Attempt to recover provider order using the stable request ID within 72h
        request_id = f"create-{deposit.deposit_id}"
        try:
            order_data = paypal_client.create_order(
                amount=deposit.payment_amount,
                currency=deposit.payment_currency,
                idempotency_key=request_id
            )
            order_id = order_data.get("id")
            if order_id:
                bind_paypal_order(session, deposit.deposit_id, order_id, approval_url=None)
                session.refresh(deposit)
            else:
                deposit.status = "REQUIRES_RECONCILIATION"
                deposit.is_provider_confirmed_terminal = False
                deposit.failure_code = "ORDER_RECOVERY_FAILED"
                deposit.failure_reason = "PayPal order creation retry did not return an order ID"
                session.commit()
                return deposit
        except Exception as exc:
            deposit.status = "REQUIRES_RECONCILIATION"
            deposit.is_provider_confirmed_terminal = False
            deposit.failure_code = "ORDER_RECOVERY_UNCERTAIN"
            deposit.failure_reason = f"Could not establish order status with PayPal: {exc}"[:250]
            session.commit()
            return deposit

    # Call PayPal order query
    order_data = paypal_client.get_order(deposit.paypal_order_id)
    order_status = order_data.get("status")

    if order_status == "COMPLETED":
        # Order is ALREADY captured on PayPal!
        # Do NOT issue a new capture request. Parse and settle existing capture from order_data directly.
        parsed = _parse_and_verify_capture_data(deposit, order_data)
        _settle_verified_capture(session, account, deposit.deposit_id, deposit.paypal_order_id, parsed)
        session.refresh(deposit)
    elif order_status == "APPROVED":
        # Order is approved by customer; capture is appropriate
        execute_paypal_capture(session, paypal_client, account_id, deposit.paypal_order_id)
        session.refresh(deposit)
    elif order_status == "CREATED":
        # Order exists at PayPal but has NOT been approved by the customer.
        # DO NOT call the capture endpoint. Preserve unresolved state and record that customer approval is required.
        deposit.status = "REQUIRES_RECONCILIATION"
        deposit.is_provider_confirmed_terminal = False
        deposit.failure_code = "AWAITING_CUSTOMER_APPROVAL"
        deposit.failure_reason = "PayPal order is in CREATED status; customer approval is required before capture"
        session.commit()
    elif order_status in ("VOIDED", "EXPIRED"):
        deposit.status = "FAILED"
        deposit.is_provider_confirmed_terminal = True
        deposit.failure_code = f"PAYPAL_ORDER_{order_status}"
        deposit.failure_reason = f"PayPal authoritatively confirmed order status is {order_status}"
        session.commit()
    else:
        # Unknown or unexpected status: preserve unresolved state and require operator review
        deposit.status = "REQUIRES_RECONCILIATION"
        deposit.is_provider_confirmed_terminal = False
        deposit.failure_code = "UNKNOWN_PROVIDER_STATUS"
        deposit.failure_reason = f"Unexpected PayPal order status '{order_status}'; manual operator review required"
        session.commit()

    return deposit


def reconcile_unsettled_deposits(session: Session, paypal_client: PayPalClient,
                                 account_id: str,
                                 deposit_id: str | None = None) -> list[PaymentDepositRecord]:
    """Protected backend-only reconciliation mechanism for operators.
    Reconciles unsettled deposits in recoverable states."""
    account = session.scalar(select(Account).where(Account.account_id == account_id))
    if account is None:
        raise LookupError("Account is not initialized")

    query = select(PaymentDepositRecord).where(
        PaymentDepositRecord.account_id == account.id,
        PaymentDepositRecord.status.in_(("REQUIRES_RECONCILIATION", "CAPTURE_PENDING"))
    )
    if deposit_id:
        query = query.where(PaymentDepositRecord.deposit_id == deposit_id)

    unsettled = session.scalars(query).all()
    results = []
    for dep in unsettled:
        rec = reconcile_deposit(session, paypal_client, account_id, dep.deposit_id)
        results.append(rec)
    return results
