"""Unit and integration tests for PayPal USD deposit flow, conversion, and wallet accounting."""
from decimal import Decimal
import os
import unittest
from uuid import uuid4

from app import create_app
from config import DEMO_USER_ID, INITIAL_CASH
from sqlalchemy import select
from database import SessionLocal
from provider import MockMarketDataProvider
from models import Account, CashLedgerEntry, PaymentDepositRecord
from paypal_service import (
    MockPayPalClient,
    PayPalNetworkError,
    extract_and_validate_approval_url,
    InvalidApprovalUrlError,
)
from portfolio_service import ensure_demo_account, get_cash_balance
from schemas import (
    PayPalCaptureOrderRequest,
    PayPalCreateOrderRequest,
    PayPalCancelOrderRequest,
)
from wallet_service import (
    execute_paypal_capture,
    get_wallet_summary,
    list_wallet_history,
    reconcile_deposit,
    UnresolvedDepositConflict,
    create_deposit_intent,
    cancel_paypal_deposit,
)


class TestPayPalWalletBackend(unittest.TestCase):
    def setUp(self):
        self.market_data = MockMarketDataProvider()
        self.paypal_client = MockPayPalClient(default_rate=Decimal("85.0000"), fee_percent=Decimal("0.035"))
        self.app = create_app(provider=self.market_data, paypal_client=self.paypal_client)
        self.client = self.app.test_client()

        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            if account:
                session.query(PaymentDepositRecord).filter(PaymentDepositRecord.account_id == account.id).delete()
                session.commit()
            ensure_demo_account(session, DEMO_USER_ID, Decimal("1000.00"))

    def test_usd_deposit_intent_and_paypal_order_creation(self):
        """Verify USD deposit intent creation binds PayPal order ID in USD."""
        idem_key = f"test-create-{uuid4()}"
        res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00",
            "currency": "USD",
            "idempotency_key": idem_key
        })
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["payment_amount"], "100.00")
        self.assertEqual(data["payment_currency"], "USD")
        self.assertEqual(data["status"], "CREATED")
        self.assertTrue(data["paypal_order_id"].startswith("MOCK-PAYPAL-"))

        # Verify database record
        with SessionLocal() as session:
            dep = session.scalar(
                select(PaymentDepositRecord).filter_by(deposit_id=data["deposit_id"])
            )
            self.assertIsNotNone(dep)
            self.assertEqual(dep.payment_amount, Decimal("100.00"))
            self.assertEqual(dep.payment_currency, "USD")
            self.assertEqual(dep.wallet_currency, "INR")
            self.assertEqual(dep.status, "CREATED")
            self.assertEqual(dep.paypal_order_id, data["paypal_order_id"])

    def test_idempotent_order_creation_returns_same_order(self):
        """Replaying create-order with same idempotency key returns existing PayPal order."""
        idem_key = f"test-replay-{uuid4()}"
        payload = {"amount": "100.00", "currency": "USD", "idempotency_key": idem_key}
        res1 = self.client.post("/api/wallet/paypal/create-order", json=payload)
        res2 = self.client.post("/api/wallet/paypal/create-order", json=payload)
        self.assertEqual(res1.status_code, 201)
        self.assertEqual(res2.status_code, 201)
        self.assertEqual(res1.get_json()["deposit_id"], res2.get_json()["deposit_id"])
        self.assertEqual(res1.get_json()["paypal_order_id"], res2.get_json()["paypal_order_id"])

    def test_idempotency_conflict_on_mismatched_amount(self):
        """Replaying with same idempotency key but different amount returns 409 conflict."""
        idem_key = f"test-conflict-{uuid4()}"
        res1 = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": idem_key
        })
        self.assertEqual(res1.status_code, 201)
        res2 = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "200.00", "currency": "USD", "idempotency_key": idem_key
        })
        self.assertEqual(res2.status_code, 409)
        self.assertEqual(res2.get_json()["error"]["code"], "IDEMPOTENCY_CONFLICT")

    def test_reject_non_usd_currency(self):
        """Only USD payments are accepted for international wallet funding."""
        res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "INR", "idempotency_key": f"key-{uuid4()}"
        })
        self.assertEqual(res.status_code, 400)

    def test_successful_usd_capture_with_verified_inr_receivable(self):
        """USD payment captured with seller_receivable_breakdown credits verified INR amount."""
        create_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"cap-{uuid4()}"
        })
        order_id = create_res.get_json()["paypal_order_id"]

        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            initial_balance = get_cash_balance(session, account)

        capture_res = self.client.post("/api/wallet/paypal/capture-order", json={
            "paypal_order_id": order_id
        })
        self.assertEqual(capture_res.status_code, 200)
        data = capture_res.get_json()
        self.assertEqual(data["status"], "COMPLETED")
        self.assertEqual(data["payment_amount"], "100.00")
        self.assertEqual(data["payment_currency"], "USD")
        self.assertEqual(data["paypal_fee_amount"], "3.50")
        self.assertEqual(data["net_payment_amount"], "96.50")
        self.assertEqual(data["exchange_rate"], "85.000000")
        self.assertEqual(data["exchange_rate_source_currency"], "USD")
        self.assertEqual(data["exchange_rate_target_currency"], "INR")
        # 96.50 * 85 = 8202.50 INR
        self.assertEqual(data["wallet_credit_amount"], "8202.50")
        self.assertEqual(data["wallet_currency"], "INR")

        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            new_balance = get_cash_balance(session, account)
            self.assertEqual(new_balance, initial_balance + Decimal("8202.50"))

            # Verify exactly one CashLedgerEntry was created
            entries = session.scalars(select(CashLedgerEntry).where(
                CashLedgerEntry.account_id == account.id, CashLedgerEntry.entry_key == f"PAYPAL_DEPOSIT:{order_id}"
            )).all()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].amount, Decimal("8202.50"))
            self.assertEqual(entries[0].entry_type, "DEPOSIT")

    def test_no_wallet_credit_when_inr_receivable_missing(self):
        """If PayPal does not return seller_receivable_breakdown, deposit goes to REQUIRES_RECONCILIATION without credit."""
        self.paypal_client.simulate_missing_receivable = True
        create_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"missing-{uuid4()}"
        })
        order_id = create_res.get_json()["paypal_order_id"]

        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            initial_balance = get_cash_balance(session, account)

        capture_res = self.client.post("/api/wallet/paypal/capture-order", json={
            "paypal_order_id": order_id
        })
        self.assertEqual(capture_res.status_code, 200)
        data = capture_res.get_json()
        self.assertEqual(data["status"], "REQUIRES_RECONCILIATION")
        self.assertIsNone(data["wallet_credit_amount"])
        self.assertEqual(data["failure_code"], "CONVERSION_VERIFICATION_FAILED")

        # Invariant: Balance unchanged, NO ledger entry
        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            self.assertEqual(get_cash_balance(session, account), initial_balance)
            entries = session.scalars(select(CashLedgerEntry).where(
                CashLedgerEntry.account_id == account.id, CashLedgerEntry.entry_key == f"PAYPAL_DEPOSIT:{order_id}"
            )).all()
            self.assertEqual(len(entries), 0)

    def test_no_wallet_credit_for_target_currency_mismatch(self):
        """If PayPal converts USD to EUR instead of INR, funds are NOT credited to INR ledger."""
        self.paypal_client.simulate_currency_mismatch = True
        create_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"curr-mismatch-{uuid4()}"
        })
        order_id = create_res.get_json()["paypal_order_id"]

        capture_res = self.client.post("/api/wallet/paypal/capture-order", json={
            "paypal_order_id": order_id
        })
        data = capture_res.get_json()
        self.assertEqual(data["status"], "REQUIRES_RECONCILIATION")
        self.assertIn("Target currency is EUR", data["failure_reason"])

    def test_capture_timeout_moves_to_reconciliation_and_recovers(self):
        """Network timeout during capture leaves deposit in REQUIRES_RECONCILIATION; recovery credits ledger."""
        create_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"timeout-{uuid4()}"
        })
        order_id = create_res.get_json()["paypal_order_id"]
        deposit_id = create_res.get_json()["deposit_id"]

        self.paypal_client.simulate_network_timeout = True
        capture_res = self.client.post("/api/wallet/paypal/capture-order", json={
            "paypal_order_id": order_id
        })
        self.assertEqual(capture_res.get_json()["status"], "REQUIRES_RECONCILIATION")
        self.assertEqual(capture_res.get_json()["failure_code"], "NETWORK_TIMEOUT")

        # Now simulate customer approval and recovery
        self.paypal_client.simulate_network_timeout = False
        self.paypal_client.orders[order_id]["status"] = "APPROVED"
        with SessionLocal() as session:
            reconciled = reconcile_deposit(session, self.paypal_client, DEMO_USER_ID, deposit_id)
            self.assertEqual(reconciled.status, "COMPLETED")
            self.assertEqual(reconciled.wallet_credit_amount, Decimal("8202.50"))

    def test_duplicate_capture_replay_is_idempotent(self):
        """Calling capture multiple times returns the same result without double crediting."""
        create_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"dup-{uuid4()}"
        })
        order_id = create_res.get_json()["paypal_order_id"]

        res1 = self.client.post("/api/wallet/paypal/capture-order", json={"paypal_order_id": order_id})
        res2 = self.client.post("/api/wallet/paypal/capture-order", json={"paypal_order_id": order_id})

        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res1.get_json()["wallet_credit_amount"], res2.get_json()["wallet_credit_amount"])

        # Invariant: exactly one ledger entry
        with SessionLocal() as session:
            account = session.query(Account).filter_by(account_id=DEMO_USER_ID).one()
            entries = session.query(CashLedgerEntry).filter_by(
                account_id=account.id, entry_key=f"PAYPAL_DEPOSIT:{order_id}"
            ).all()
            self.assertEqual(len(entries), 1)

    def test_cancellation_lifecycle_and_capture_rejection(self):
        """A user-cancelled deposit with provider confirmation cannot be captured."""
        create_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "50.00", "currency": "USD", "idempotency_key": f"cancel-{uuid4()}"
        })
        order_id = create_res.get_json()["paypal_order_id"]

        # Provider authoritatively voids the order
        self.paypal_client.orders[order_id]["status"] = "VOIDED"

        cancel_res = self.client.post("/api/wallet/paypal/cancel-order", json={"paypal_order_id": order_id})
        self.assertEqual(cancel_res.status_code, 200)
        self.assertEqual(cancel_res.get_json()["status"], "CANCELLED")

        # Subsequent capture attempt is rejected
        capture_res = self.client.post("/api/wallet/paypal/capture-order", json={"paypal_order_id": order_id})
        self.assertEqual(capture_res.status_code, 422)

    def test_deposited_inr_immediately_increases_stock_buying_power(self):
        """Core Invariant: USD deposit converts to INR and immediately enables buying Indian stocks."""
        # Reset account cash to ₹1,000
        with SessionLocal() as session:
            account = session.query(Account).filter_by(account_id=DEMO_USER_ID).one()
            session.query(CashLedgerEntry).filter_by(account_id=account.id).delete()
            session.add(CashLedgerEntry(account_id=account.id, entry_key="TEST_OPENING", entry_type="INITIAL_CASH", amount=Decimal("1000.00")))
            session.commit()

        # Step 1: Attempt to buy 1 share of TCS @ ~₹3,865 -> Must fail with INSUFFICIENT_CASH
        buy_res1 = self.client.post("/api/orders", json={
            "symbol": "TCS",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MARKET",
            "idempotency_key": f"buy-fail-{uuid4()}"
        })
        self.assertEqual(buy_res1.status_code, 201)
        self.assertEqual(buy_res1.get_json()["status"], "REJECTED")
        self.assertEqual(buy_res1.get_json()["rejection_reason"], "INSUFFICIENT_CASH")

        # Step 2: Deposit $100 USD (converts to ₹8,202.50 INR)
        create_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"deposit-buy-{uuid4()}"
        })
        order_id = create_res.get_json()["paypal_order_id"]
        cap_res = self.client.post("/api/wallet/paypal/capture-order", json={"paypal_order_id": order_id})
        self.assertEqual(cap_res.status_code, 200)
        self.assertEqual(cap_res.get_json()["status"], "COMPLETED")

        # New balance: 1000 + 8202.50 = 9202.50 INR
        summary_res = self.client.get("/api/wallet")
        self.assertEqual(summary_res.get_json()["cash_balance"], "9202.50")

        # Step 3: Now buy 1 share of TCS -> Must succeed (FILLED)
        buy_res2 = self.client.post("/api/orders", json={
            "symbol": "TCS",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MARKET",
            "idempotency_key": f"buy-success-{uuid4()}"
        })
        self.assertEqual(buy_res2.status_code, 201)
        self.assertEqual(buy_res2.get_json()["status"], "FILLED")
        exec_price = Decimal(buy_res2.get_json()["execution_price"])

        # Remaining cash must equal 9202.50 - exec_price
        with SessionLocal() as session:
            account = session.query(Account).filter_by(account_id=DEMO_USER_ID).one()
            self.assertEqual(get_cash_balance(session, account), Decimal("9202.50") - exec_price)

    def test_wallet_history_reports_both_usd_payment_and_inr_credit(self):
        """Unified history returns deposit details with USD payment and INR wallet credit."""
        create_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"hist-{uuid4()}"
        })
        order_id = create_res.get_json()["paypal_order_id"]
        self.client.post("/api/wallet/paypal/capture-order", json={"paypal_order_id": order_id})

        history_res = self.client.get("/api/wallet/history")
        self.assertEqual(history_res.status_code, 200)
        items = history_res.get_json()["items"]
        deposit_items = [i for i in items if i["category"] == "DEPOSIT" and i["reference_id"] == order_id]
        self.assertEqual(len(deposit_items), 1)
        item = deposit_items[0]
        self.assertEqual(item["payment_amount"], "100.00")
        self.assertEqual(item["payment_currency"], "USD")
        self.assertEqual(item["amount"], "+8202.50")
        self.assertEqual(item["currency"], "INR")
        self.assertEqual(item["exchange_rate"], "85.000000")

    def test_concurrent_capture_requests_rejects_pending(self):
        """If a deposit is in CAPTURE_PENDING, a second capture request is rejected as in progress."""
        create_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"concur-{uuid4()}"
        })
        order_id = create_res.get_json()["paypal_order_id"]

        # Simulate claim in progress
        with SessionLocal() as session:
            account = session.query(Account).filter_by(account_id=DEMO_USER_ID).one()
            dep = session.query(PaymentDepositRecord).filter_by(account_id=account.id, paypal_order_id=order_id).one()
            dep.status = "CAPTURE_PENDING"
            from datetime import datetime, timezone
            dep.claimed_at = datetime.now(timezone.utc)
            session.commit()

        # Attempting capture while pending must raise 409 CAPTURE_PENDING
        res = self.client.post("/api/wallet/paypal/capture-order", json={"paypal_order_id": order_id})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json()["error"]["code"], "CAPTURE_PENDING")

    def test_reconcile_already_completed_order_does_not_call_capture_again(self):
        """When PayPal order is already COMPLETED, reconciliation does NOT issue another capture request."""
        create_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"already-comp-{uuid4()}"
        })
        order_id = create_res.get_json()["paypal_order_id"]
        deposit_id = create_res.get_json()["deposit_id"]

        # Capture order externally directly on PayPal
        self.paypal_client.capture_order(order_id, "external-test-cap")
        self.assertEqual(len(self.paypal_client.capture_calls), 1)

        # Deposit locally is still CREATED / REQUIRES_RECONCILIATION
        with SessionLocal() as session:
            account = session.query(Account).filter_by(account_id=DEMO_USER_ID).one()
            dep = session.query(PaymentDepositRecord).filter_by(deposit_id=deposit_id).one()
            dep.status = "REQUIRES_RECONCILIATION"
            session.commit()

        # Reconcile: must settle using get_order without incrementing capture_calls!
        with SessionLocal() as session:
            reconciled = reconcile_deposit(session, self.paypal_client, DEMO_USER_ID, deposit_id)
            self.assertEqual(reconciled.status, "COMPLETED")
            self.assertEqual(reconciled.wallet_credit_amount, Decimal("8202.50"))

        # Invariant: capture_order was NOT called by reconcile_deposit
        self.assertEqual(len(self.paypal_client.capture_calls), 1)

        # Repeated reconciliation is completely idempotent
        with SessionLocal() as session:
            reconciled_again = reconcile_deposit(session, self.paypal_client, DEMO_USER_ID, deposit_id)
            self.assertEqual(reconciled_again.status, "COMPLETED")

            account = session.query(Account).filter_by(account_id=DEMO_USER_ID).one()
            entries = session.query(CashLedgerEntry).filter_by(
                account_id=account.id, entry_key=f"PAYPAL_DEPOSIT:{order_id}"
            ).all()
            self.assertEqual(len(entries), 1)

    def test_timeout_recovery_after_successful_provider_capture(self):
        """Exact Sequence: capture succeeds on PayPal -> network times out -> recovery settles without re-capture."""
        create_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"post-timeout-{uuid4()}"
        })
        order_id = create_res.get_json()["paypal_order_id"]
        deposit_id = create_res.get_json()["deposit_id"]

        # Enable post-capture timeout simulation
        self.paypal_client.simulate_timeout_after_capture = True
        cap_res = self.client.post("/api/wallet/paypal/capture-order", json={"paypal_order_id": order_id})
        self.assertEqual(cap_res.status_code, 200)
        self.assertEqual(cap_res.get_json()["status"], "REQUIRES_RECONCILIATION")
        self.assertEqual(cap_res.get_json()["failure_code"], "NETWORK_TIMEOUT")

        # Provider recorded 1 capture call
        self.assertEqual(len(self.paypal_client.capture_calls), 1)

        # Recovery runs
        self.paypal_client.simulate_timeout_after_capture = False
        with SessionLocal() as session:
            reconciled = reconcile_deposit(session, self.paypal_client, DEMO_USER_ID, deposit_id)
            self.assertEqual(reconciled.status, "COMPLETED")
            self.assertEqual(reconciled.wallet_credit_amount, Decimal("8202.50"))

        # Provider capture was NOT repeated
        self.assertEqual(len(self.paypal_client.capture_calls), 1)

        # Ledger credited exactly once
        with SessionLocal() as session:
            account = session.query(Account).filter_by(account_id=DEMO_USER_ID).one()
            entries = session.query(CashLedgerEntry).filter_by(
                account_id=account.id, entry_key=f"PAYPAL_DEPOSIT:{order_id}"
            ).all()
            self.assertEqual(len(entries), 1)

    def test_operational_reconciliation_mechanism(self):
        """Backend operator reconciliation function processes recoverable deposits."""
        from wallet_service import reconcile_unsettled_deposits
        create_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"op-rec-{uuid4()}"
        })
        order_id = create_res.get_json()["paypal_order_id"]
        deposit_id = create_res.get_json()["deposit_id"]

        self.paypal_client.simulate_timeout_after_capture = True
        self.client.post("/api/wallet/paypal/capture-order", json={"paypal_order_id": order_id})
        self.paypal_client.simulate_timeout_after_capture = False

        with SessionLocal() as session:
            results = reconcile_unsettled_deposits(session, self.paypal_client, DEMO_USER_ID, deposit_id)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].status, "COMPLETED")
            self.assertEqual(results[0].wallet_credit_amount, Decimal("8202.50"))

    def test_settlement_rejects_inverted_rate_direction(self):
        """If PayPal reports exchange rate direction INR->USD instead of USD->INR, reject and move to reconciliation."""
        self.paypal_client.simulate_rate_direction_inversion = True
        create_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"inv-rate-{uuid4()}"
        })
        order_id = create_res.get_json()["paypal_order_id"]

        cap_res = self.client.post("/api/wallet/paypal/capture-order", json={"paypal_order_id": order_id})
        data = cap_res.get_json()
        self.assertEqual(data["status"], "REQUIRES_RECONCILIATION")
        self.assertEqual(data["failure_code"], "CONVERSION_VERIFICATION_FAILED")
        self.assertIn("rate currencies invalid", data["failure_reason"])

    def test_settlement_rejects_mismatched_gross_amount(self):
        """If PayPal returns gross amount different from local deposit intent, reject."""
        self.paypal_client.simulate_gross_mismatch = True
        create_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"gross-mis-{uuid4()}"
        })
        order_id = create_res.get_json()["paypal_order_id"]

        cap_res = self.client.post("/api/wallet/paypal/capture-order", json={"paypal_order_id": order_id})
        data = cap_res.get_json()
        self.assertEqual(data["status"], "REQUIRES_RECONCILIATION")
        self.assertEqual(data["failure_code"], "CONVERSION_VERIFICATION_FAILED")
        self.assertIn("Gross amount/currency mismatch", data["failure_reason"])

    def test_settlement_rejects_mismatched_net_amount(self):
        """If PayPal net amount does not equal gross minus fee, reject."""
        self.paypal_client.simulate_net_mismatch = True
        create_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"net-mis-{uuid4()}"
        })
        order_id = create_res.get_json()["paypal_order_id"]

        cap_res = self.client.post("/api/wallet/paypal/capture-order", json={"paypal_order_id": order_id})
        data = cap_res.get_json()
        self.assertEqual(data["status"], "REQUIRES_RECONCILIATION")
        self.assertIn("Net amount", data["failure_reason"])

    def test_settlement_rejects_excessive_discrepancy(self):
        """If mathematical conversion deviates from receivable amount by > 0.01 INR, reject."""
        self.paypal_client.simulate_excessive_discrepancy = True
        create_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"disc-{uuid4()}"
        })
        order_id = create_res.get_json()["paypal_order_id"]

        cap_res = self.client.post("/api/wallet/paypal/capture-order", json={"paypal_order_id": order_id})
        data = cap_res.get_json()
        self.assertEqual(data["status"], "REQUIRES_RECONCILIATION")
        self.assertIn("Excessive conversion discrepancy", data["failure_reason"])

    def test_settlement_preserves_optional_fee_in_receivable_currency(self):
        """When paypal_fee_in_receivable_currency is present, verify and persist it."""
        self.paypal_client.include_fee_in_receivable_currency = True
        create_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"fee-rec-{uuid4()}"
        })
        order_id = create_res.get_json()["paypal_order_id"]
        cap_res = self.client.post("/api/wallet/paypal/capture-order", json={"paypal_order_id": order_id})
        self.assertEqual(cap_res.status_code, 200)
        data = cap_res.get_json()
        self.assertEqual(data["status"], "COMPLETED")
        self.assertEqual(data["paypal_fee_in_receivable_currency"], "297.50")
        self.assertEqual(data["paypal_fee_in_receivable_currency_code"], "INR")

        with SessionLocal() as session:
            dep = session.scalar(select(PaymentDepositRecord).filter_by(paypal_order_id=order_id))
            self.assertEqual(dep.paypal_fee_in_receivable_currency, Decimal("297.50"))
            self.assertEqual(dep.paypal_fee_in_receivable_currency_code, "INR")

    def test_environment_safety_fail_closed(self):
        """Verify Sandbox-only environment validation fails closed for all unsafe configurations."""
        from config import validate_paypal_environment

        # 1. Unset: defaults to sandbox
        env, url = validate_paypal_environment(None, None)
        self.assertEqual(env, "sandbox")
        self.assertEqual(url, "https://api-m.sandbox.paypal.com")

        # 2. sandbox (lowercase)
        env, url = validate_paypal_environment("sandbox", None)
        self.assertEqual(env, "sandbox")

        # 3. Sandbox (mixed case)
        env, url = validate_paypal_environment("Sandbox", None)
        self.assertEqual(env, "sandbox")

        # 4. Empty environment value
        with self.assertRaises(ValueError) as ctx:
            validate_paypal_environment("", None)
        self.assertIn("cannot be empty", str(ctx.exception))

        # 5. Invalid environment value (e.g. production)
        with self.assertRaises(ValueError) as ctx:
            validate_paypal_environment("production", None)
        self.assertIn("Invalid PAYPAL_ENVIRONMENT", str(ctx.exception))

        # 6. Explicit production base URL
        with self.assertRaises(ValueError) as ctx:
            validate_paypal_environment("sandbox", "https://api-m.paypal.com")
        self.assertIn("strictly prohibited", str(ctx.exception))

    def test_approval_url_validation_comprehensive(self):
        """Verify strict validation of PayPal customer approval URLs."""
        # 1. Valid Sandbox approve URL
        valid_order = {
            "id": "ORD-1",
            "links": [
                {"href": "https://api-m.sandbox.paypal.com/v2/checkout/orders/ORD-1", "rel": "self"},
                {"href": "https://www.sandbox.paypal.com/checkoutnow?token=ORD-1", "rel": "approve"},
            ]
        }
        url = extract_and_validate_approval_url(valid_order, is_sandbox=True)
        self.assertEqual(url, "https://www.sandbox.paypal.com/checkoutnow?token=ORD-1")

        # 2. Valid supported payer-action link
        payer_action_order = {
            "id": "ORD-2",
            "links": [
                {"href": "https://sandbox.paypal.com/checkoutnow?token=ORD-2", "rel": "payer-action"},
            ]
        }
        url = extract_and_validate_approval_url(payer_action_order, is_sandbox=True)
        self.assertEqual(url, "https://sandbox.paypal.com/checkoutnow?token=ORD-2")

        # 3. Missing approval link
        missing_link = {"id": "ORD-3", "links": [{"href": "https://api.sandbox.paypal.com", "rel": "self"}]}
        with self.assertRaises(InvalidApprovalUrlError) as ctx:
            extract_and_validate_approval_url(missing_link, is_sandbox=True)
        self.assertIn("does not contain an approval link", str(ctx.exception))

        # 4. Insecure HTTP link rejected
        http_order = {"id": "ORD-4", "links": [{"href": "http://www.sandbox.paypal.com/checkoutnow?token=ORD-4", "rel": "approve"}]}
        with self.assertRaises(InvalidApprovalUrlError) as ctx:
            extract_and_validate_approval_url(http_order, is_sandbox=True)
        self.assertIn("must use HTTPS scheme", str(ctx.exception))

        # 5. Production URL rejected in Sandbox mode
        prod_order = {"id": "ORD-5", "links": [{"href": "https://www.paypal.com/checkoutnow?token=ORD-5", "rel": "approve"}]}
        with self.assertRaises(InvalidApprovalUrlError) as ctx:
            extract_and_validate_approval_url(prod_order, is_sandbox=True)
        self.assertIn("rejected in Sandbox environment", str(ctx.exception))

        # 6. Lookalike / attacker domain rejected
        evil_order = {"id": "ORD-6", "links": [{"href": "https://www.sandbox.paypal.com.attacker.test/checkout", "rel": "approve"}]}
        with self.assertRaises(InvalidApprovalUrlError) as ctx:
            extract_and_validate_approval_url(evil_order, is_sandbox=True)
        self.assertIn("not an authorized Sandbox PayPal host", str(ctx.exception))

        # 7. Embedded credentials rejected
        cred_order = {"id": "ORD-7", "links": [{"href": "https://user:pass@www.sandbox.paypal.com/checkout", "rel": "approve"}]}
        with self.assertRaises(InvalidApprovalUrlError) as ctx:
            extract_and_validate_approval_url(cred_order, is_sandbox=True)
        self.assertIn("embedded user credentials", str(ctx.exception))

        # 8. Non-standard port rejected
        port_order = {"id": "ORD-8", "links": [{"href": "https://www.sandbox.paypal.com:8443/checkout", "rel": "approve"}]}
        with self.assertRaises(InvalidApprovalUrlError) as ctx:
            extract_and_validate_approval_url(port_order, is_sandbox=True)
        self.assertIn("unexpected port", str(ctx.exception))

    def test_mock_mode_works_without_approval_url(self):
        """Mock mode returns null approval_url and enables simulated approval."""
        res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "50.00",
            "currency": "USD",
            "idempotency_key": f"mock-mode-test-{uuid4()}"
        })
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertIsNone(data.get("approval_url"))
        self.assertEqual(data.get("payment_mode"), "mock")

    def test_unresolved_deposit_blocks_new_deposit_initiation(self):
        """A new deposit cannot be created while an earlier deposit is unresolved."""
        # 1. Create first deposit (status CREATED)
        key1 = f"unresolved-key-1-{uuid4()}"
        res1 = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "50.00",
            "currency": "USD",
            "idempotency_key": key1
        })
        self.assertEqual(res1.status_code, 201)
        dep1_id = res1.get_json()["deposit_id"]
        order1_id = res1.get_json()["paypal_order_id"]

        # 2. Attempting to create a second deposit with DIFFERENT idempotency key is rejected
        key2 = f"unresolved-key-2-{uuid4()}"
        res2 = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "75.00",
            "currency": "USD",
            "idempotency_key": key2
        })
        self.assertEqual(res2.status_code, 409)
        self.assertEqual(res2.get_json()["error"]["code"], "UNRESOLVED_DEPOSIT_CONFLICT")
        self.assertIn("unresolved deposit", res2.get_json()["error"]["message"])

        # 3. Retrying the SAME idempotency key returns the existing order safely
        res_replay = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "50.00",
            "currency": "USD",
            "idempotency_key": key1
        })
        self.assertEqual(res_replay.status_code, 201)
        self.assertEqual(res_replay.get_json()["deposit_id"], dep1_id)

        # 4. Now cancel the first deposit with provider confirmation
        self.paypal_client.orders[order1_id]["status"] = "VOIDED"
        cancel_res = self.client.post("/api/wallet/paypal/cancel-order", json={
            "paypal_order_id": order1_id
        })
        self.assertEqual(cancel_res.status_code, 200)

        # 5. Now creating with key2 succeeds because previous deposit is definitively CANCELLED
        res3 = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "75.00",
            "currency": "USD",
            "idempotency_key": key2
        })
        self.assertEqual(res3.status_code, 201)
        self.assertEqual(res3.get_json()["payment_amount"], "75.00")

    def test_requires_reconciliation_deposit_blocks_new_deposit(self):
        """A deposit in REQUIRES_RECONCILIATION strictly blocks new deposit creation."""
        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            unsettled_dep = PaymentDepositRecord(
                deposit_id=str(uuid4()),
                account_id=account.id,
                idempotency_key=f"recon-block-key-{uuid4()}",
                provider="PAYPAL",
                paypal_order_id=f"RECON-ORDER-{uuid4().hex[:8]}",
                payment_amount=Decimal("150.00"),
                payment_currency="USD",
                wallet_currency="INR",
                status="REQUIRES_RECONCILIATION",
                failure_code="CONVERSION_VERIFICATION_FAILED"
            )
            session.add(unsettled_dep)
            session.commit()

        # Attempt to create a new deposit must fail with 409 conflict
        res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00",
            "currency": "USD",
            "idempotency_key": f"new-deposit-after-recon-{uuid4()}"
        })
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json()["error"]["code"], "UNRESOLVED_DEPOSIT_CONFLICT")

    def test_capture_pending_deposit_blocks_new_deposit(self):
        """A deposit in CAPTURE_PENDING strictly blocks new deposit creation."""
        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            pending_dep = PaymentDepositRecord(
                deposit_id=str(uuid4()),
                account_id=account.id,
                idempotency_key=f"capture-pending-key-{uuid4()}",
                provider="PAYPAL",
                paypal_order_id=f"PENDING-ORDER-{uuid4().hex[:8]}",
                payment_amount=Decimal("200.00"),
                payment_currency="USD",
                wallet_currency="INR",
                status="CAPTURE_PENDING"
            )
            session.add(pending_dep)
            session.commit()

        res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00",
            "currency": "USD",
            "idempotency_key": f"new-deposit-after-pending-{uuid4()}"
        })
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json()["error"]["code"], "UNRESOLVED_DEPOSIT_CONFLICT")

    def test_concurrent_deposit_intent_creation_prevents_multiple_unresolved(self):
        """Concurrent requests with distinct keys cannot create multiple unresolved deposits."""
        from concurrent.futures import ThreadPoolExecutor

        # Ensure no residual deposits
        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            session.query(PaymentDepositRecord).filter(
                PaymentDepositRecord.account_id == account.id
            ).delete()
            session.commit()

        keys = [f"concurrent-create-{uuid4()}" for _ in range(2)]
        def try_create(k):
            with self.app.test_client() as client:
                return client.post("/api/wallet/paypal/create-order", json={
                    "amount": "100.00",
                    "currency": "USD",
                    "idempotency_key": k
                })

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(try_create, keys))

        status_codes = [r.status_code for r in responses]
        self.assertEqual(status_codes.count(201), 1)
        self.assertIn(status_codes[0] if status_codes[1] == 201 else status_codes[1], (409, 500))

        # Crucially: exactly 1 unresolved deposit exists in DB
        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            unresolved_count = session.query(PaymentDepositRecord).filter(
                PaymentDepositRecord.account_id == account.id,
                PaymentDepositRecord.status != "COMPLETED",
                PaymentDepositRecord.is_provider_confirmed_terminal.is_(False)
            ).count()
            self.assertEqual(unresolved_count, 1)

    def test_capture_500_after_provider_capture_moves_to_reconciliation_and_blocks(self):
        """When capture succeeds at PayPal but response returns HTTP 500, state moves to reconciliation and blocks new deposits."""
        idem_key = f"cap-500-{uuid4()}"
        res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": idem_key
        })
        self.assertEqual(res.status_code, 201)
        order_id = res.get_json()["paypal_order_id"]

        # Simulate provider-side capture success followed by HTTP 500 response
        self.paypal_client.simulate_500_after_capture = True
        cap_res = self.client.post("/api/wallet/paypal/capture-order", json={"paypal_order_id": order_id})
        self.assertEqual(cap_res.status_code, 200)
        data = cap_res.get_json()
        self.assertEqual(data["status"], "REQUIRES_RECONCILIATION")
        self.assertNotEqual(data["status"], "FAILED")

        # Verify new deposit attempt is blocked with 409
        block_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"new-key-{uuid4()}"
        })
        self.assertEqual(block_res.status_code, 409)
        self.assertEqual(block_res.get_json()["error"]["code"], "UNRESOLVED_DEPOSIT_CONFLICT")

        # Reconcile: discovers existing completed capture and settles without second capture
        self.paypal_client.simulate_500_after_capture = False
        initial_capture_call_count = len(self.paypal_client.capture_calls)

        with SessionLocal() as session:
            rec = reconcile_deposit(session, self.paypal_client, DEMO_USER_ID, data["deposit_id"])
            self.assertEqual(rec.status, "COMPLETED")
            self.assertIsNotNone(rec.wallet_credit_amount)

        # Confirm no second capture was dispatched
        self.assertEqual(len(self.paypal_client.capture_calls), initial_capture_call_count)

    def test_capture_malformed_and_missing_id_retains_reconciliation(self):
        """Malformed capture response or missing capture ID must never set FAILED; retains REQUIRES_RECONCILIATION."""
        # Test 1: Missing capture ID in response
        idem_key1 = f"missing-id-{uuid4()}"
        res1 = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": idem_key1
        })
        order_id1 = res1.get_json()["paypal_order_id"]
        self.paypal_client.simulate_missing_capture_id = True

        cap_res1 = self.client.post("/api/wallet/paypal/capture-order", json={"paypal_order_id": order_id1})
        self.assertEqual(cap_res1.status_code, 200)
        self.assertEqual(cap_res1.get_json()["status"], "REQUIRES_RECONCILIATION")
        self.assertNotEqual(cap_res1.get_json()["status"], "FAILED")

        # Must block new deposit
        b_res1 = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "50.00", "currency": "USD", "idempotency_key": f"blocked-{uuid4()}"
        })
        self.assertEqual(b_res1.status_code, 409)

        # Clear state for Test 2
        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            session.query(PaymentDepositRecord).filter(PaymentDepositRecord.account_id == account.id).delete()
            session.commit()

        # Test 2: Malformed capture response
        self.paypal_client.simulate_missing_capture_id = False
        self.paypal_client.simulate_malformed_capture_response = True
        idem_key2 = f"malformed-{uuid4()}"
        res2 = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": idem_key2
        })
        order_id2 = res2.get_json()["paypal_order_id"]

        cap_res2 = self.client.post("/api/wallet/paypal/capture-order", json={"paypal_order_id": order_id2})
        self.assertEqual(cap_res2.status_code, 200)
        self.assertEqual(cap_res2.get_json()["status"], "REQUIRES_RECONCILIATION")
        self.assertNotEqual(cap_res2.get_json()["status"], "FAILED")

        # Must block new deposit
        b_res2 = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "50.00", "currency": "USD", "idempotency_key": f"blocked-{uuid4()}"
        })
        self.assertEqual(b_res2.status_code, 409)

    def test_reconcile_created_order_does_not_call_capture(self):
        """Reconciliation of a CREATED (unapproved) order must not dispatch a capture request."""
        idem_key = f"created-recon-{uuid4()}"
        res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": idem_key
        })
        dep_id = res.get_json()["deposit_id"]

        capture_count_before = len(self.paypal_client.capture_calls)
        with SessionLocal() as session:
            rec = reconcile_deposit(session, self.paypal_client, DEMO_USER_ID, dep_id)
            self.assertEqual(rec.status, "REQUIRES_RECONCILIATION")
            self.assertEqual(rec.failure_code, "AWAITING_CUSTOMER_APPROVAL")

        # Assert no capture call was dispatched to PayPal
        self.assertEqual(len(self.paypal_client.capture_calls), capture_count_before)

    def test_reconcile_approved_order_executes_capture(self):
        """Reconciliation of an APPROVED order dispatches capture and credits verified receivable."""
        idem_key = f"approved-recon-{uuid4()}"
        res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": idem_key
        })
        dep_id = res.get_json()["deposit_id"]
        order_id = res.get_json()["paypal_order_id"]

        # Mark order as APPROVED by customer on PayPal
        self.paypal_client.orders[order_id]["status"] = "APPROVED"

        capture_count_before = len(self.paypal_client.capture_calls)
        with SessionLocal() as session:
            rec = reconcile_deposit(session, self.paypal_client, DEMO_USER_ID, dep_id)
            self.assertEqual(rec.status, "COMPLETED")
            self.assertIsNotNone(rec.wallet_credit_amount)
            self.assertEqual(rec.wallet_credit_amount, Decimal("8202.50"))

        self.assertEqual(len(self.paypal_client.capture_calls), capture_count_before + 1)

    def test_reconcile_voided_and_expired_orders_set_terminal_failed(self):
        """Authoritatively voided and expired orders transition to FAILED and release the account."""
        for terminal_status in ("VOIDED", "EXPIRED"):
            with SessionLocal() as session:
                account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
                session.query(PaymentDepositRecord).filter(PaymentDepositRecord.account_id == account.id).delete()
                session.commit()

            idem_key = f"term-{terminal_status}-{uuid4()}"
            res = self.client.post("/api/wallet/paypal/create-order", json={
                "amount": "100.00", "currency": "USD", "idempotency_key": idem_key
            })
            dep_id = res.get_json()["deposit_id"]
            order_id = res.get_json()["paypal_order_id"]

            self.paypal_client.orders[order_id]["status"] = terminal_status
            with SessionLocal() as session:
                rec = reconcile_deposit(session, self.paypal_client, DEMO_USER_ID, dep_id)
                self.assertEqual(rec.status, "FAILED")
                self.assertEqual(rec.failure_code, f"PAYPAL_ORDER_{terminal_status}")

            # Because VOIDED/EXPIRED is a provider-confirmed terminal outcome, new deposits are now unblocked
            new_res = self.client.post("/api/wallet/paypal/create-order", json={
                "amount": "50.00", "currency": "USD", "idempotency_key": f"new-after-{terminal_status}-{uuid4()}"
            })
            self.assertEqual(new_res.status_code, 201)

    def test_create_order_timeout_uncertainty_retains_reconciliation_and_recovers_same_request_id(self):
        """When create_order times out after provider receives it, state moves to reconciliation and retries with same request ID."""
        idem_key = f"timeout-create-{uuid4()}"
        self.paypal_client.simulate_create_timeout_after_order = True

        res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": idem_key
        })
        self.assertIn(res.status_code, (500, 503))

        # Deposit record is preserved in DB as REQUIRES_RECONCILIATION
        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            dep = session.scalar(
                select(PaymentDepositRecord).where(
                    PaymentDepositRecord.account_id == account.id,
                    PaymentDepositRecord.idempotency_key == idem_key
                )
            )
            self.assertIsNotNone(dep)
            self.assertEqual(dep.status, "REQUIRES_RECONCILIATION")
            self.assertEqual(dep.failure_code, "ORDER_CREATION_UNCERTAIN")
            initial_request_id = f"create-{dep.deposit_id}"

        # Different key is blocked
        b_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"diff-key-{uuid4()}"
        })
        self.assertEqual(b_res.status_code, 409)
        self.assertEqual(b_res.get_json()["error"]["code"], "UNRESOLVED_DEPOSIT_CONFLICT")

        # Retry with SAME idempotency key reuses existing intent and stable provider request ID
        self.paypal_client.simulate_create_timeout_after_order = False
        retry_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": idem_key
        })
        self.assertEqual(retry_res.status_code, 201)
        data = retry_res.get_json()
        self.assertEqual(data["status"], "CREATED")
        self.assertTrue(data["paypal_order_id"].startswith("MOCK-PAYPAL-"))

        # Verify the same provider request ID was reused in create_calls
        matching_calls = [c for c in self.paypal_client.create_calls if c["idempotency_key"] == initial_request_id]
        self.assertGreaterEqual(len(matching_calls), 1)

    def test_cancellation_requested_for_created_order_preserves_unresolved(self):
        """Cancellation of a CREATED order cannot be finalized via API; preserves REQUIRES_RECONCILIATION and blocks."""
        res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"cancel-created-{uuid4()}"
        })
        order_id = res.get_json()["paypal_order_id"]
        dep_id = res.get_json()["deposit_id"]

        # Order on PayPal remains in CREATED status
        cancel_res = self.client.post("/api/wallet/paypal/cancel-order", json={"paypal_order_id": order_id})
        self.assertEqual(cancel_res.status_code, 422)
        self.assertEqual(cancel_res.get_json()["error"]["code"], "INVALID_DEPOSIT_STATE")

        # In DB: deposit is in REQUIRES_RECONCILIATION, NOT cancelled
        with SessionLocal() as session:
            dep = session.scalar(select(PaymentDepositRecord).where(PaymentDepositRecord.deposit_id == dep_id))
            self.assertEqual(dep.status, "REQUIRES_RECONCILIATION")
            self.assertEqual(dep.failure_code, "CANCELLATION_PENDING_PROVIDER_EXPIRY")
            self.assertFalse(dep.is_provider_confirmed_terminal)

        # New deposit with different key is blocked
        new_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "50.00", "currency": "USD", "idempotency_key": f"new-blocked-{uuid4()}"
        })
        self.assertEqual(new_res.status_code, 409)

    def test_cancellation_requested_for_approved_and_completed_orders_rejected(self):
        """Approved or completed PayPal orders strictly reject cancellation and preserve unresolved state."""
        # 1. APPROVED order rejection
        res1 = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"cancel-appr-{uuid4()}"
        })
        order_id1 = res1.get_json()["paypal_order_id"]
        self.paypal_client.orders[order_id1]["status"] = "APPROVED"

        cancel_res1 = self.client.post("/api/wallet/paypal/cancel-order", json={"paypal_order_id": order_id1})
        self.assertEqual(cancel_res1.status_code, 422)
        self.assertIn("already APPROVED", cancel_res1.get_json()["error"]["message"])

        # 2. COMPLETED order rejection
        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            session.query(PaymentDepositRecord).filter(PaymentDepositRecord.account_id == account.id).delete()
            session.commit()

        res2 = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"cancel-comp-{uuid4()}"
        })
        order_id2 = res2.get_json()["paypal_order_id"]
        self.client.post("/api/wallet/paypal/capture-order", json={"paypal_order_id": order_id2})

        cancel_res2 = self.client.post("/api/wallet/paypal/cancel-order", json={"paypal_order_id": order_id2})
        self.assertEqual(cancel_res2.status_code, 422)
        self.assertIn("already completed", cancel_res2.get_json()["error"]["message"])

    def test_cancellation_provider_timeout_preserves_unresolved(self):
        """Provider network timeout during cancellation query preserves deposit as REQUIRES_RECONCILIATION."""
        res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"cancel-timeout-{uuid4()}"
        })
        order_id = res.get_json()["paypal_order_id"]
        dep_id = res.get_json()["deposit_id"]

        self.paypal_client.simulate_network_timeout = True
        cancel_res = self.client.post("/api/wallet/paypal/cancel-order", json={"paypal_order_id": order_id})
        self.assertEqual(cancel_res.status_code, 422)

        with SessionLocal() as session:
            dep = session.scalar(select(PaymentDepositRecord).where(PaymentDepositRecord.deposit_id == dep_id))
            self.assertEqual(dep.status, "REQUIRES_RECONCILIATION")
            self.assertEqual(dep.failure_code, "CANCELLATION_UNCERTAIN")
            self.assertFalse(dep.is_provider_confirmed_terminal)

        # Blocked
        self.paypal_client.simulate_network_timeout = False
        new_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "50.00", "currency": "USD", "idempotency_key": f"new-blocked-to-{uuid4()}"
        })
        self.assertEqual(new_res.status_code, 409)

    def test_unverified_local_cancelled_record_blocks_new_deposit(self):
        """An unverified CANCELLED status (is_provider_confirmed_terminal=False) strictly blocks new deposits."""
        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            dep = PaymentDepositRecord(
                deposit_id=str(uuid4()),
                account_id=account.id,
                idempotency_key=f"unverified-cancel-{uuid4()}",
                provider="PAYPAL",
                paypal_order_id=f"UNVERIFIED-ORDER-{uuid4().hex[:8]}",
                payment_amount=Decimal("100.00"),
                payment_currency="USD",
                wallet_currency="INR",
                status="CANCELLED",
                is_provider_confirmed_terminal=False
            )
            session.add(dep)
            session.commit()

        # Must be blocked because is_provider_confirmed_terminal is False
        new_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "50.00", "currency": "USD", "idempotency_key": f"new-after-unverified-{uuid4()}"
        })
        self.assertEqual(new_res.status_code, 409)
        self.assertEqual(new_res.get_json()["error"]["code"], "UNRESOLVED_DEPOSIT_CONFLICT")

    def test_definitive_provider_confirmed_cancellation_releases_block(self):
        """Authoritatively confirmed terminal cancellation by provider releases the unresolved block."""
        res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": f"verified-term-{uuid4()}"
        })
        order_id = res.get_json()["paypal_order_id"]

        self.paypal_client.orders[order_id]["status"] = "EXPIRED"
        cancel_res = self.client.post("/api/wallet/paypal/cancel-order", json={"paypal_order_id": order_id})
        self.assertEqual(cancel_res.status_code, 200)
        self.assertEqual(cancel_res.get_json()["status"], "CANCELLED")

        # Now creating with a different key succeeds because cancellation was provider-verified
        new_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "50.00", "currency": "USD", "idempotency_key": f"new-after-term-{uuid4()}"
        })
        self.assertEqual(new_res.status_code, 201)

    def test_reconcile_intent_without_order_id_after_72h_idempotency_expiry(self):
        """Intent without order ID older than 72h stops automatic create_order to prevent duplicate orders."""
        from datetime import datetime, timezone, timedelta
        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            session.query(PaymentDepositRecord).filter(PaymentDepositRecord.account_id == account.id).delete()
            old_dep = PaymentDepositRecord(
                deposit_id=str(uuid4()),
                account_id=account.id,
                idempotency_key=f"old-intent-{uuid4()}",
                provider="PAYPAL",
                paypal_order_id=None,
                payment_amount=Decimal("100.00"),
                payment_currency="USD",
                wallet_currency="INR",
                status="REQUIRES_RECONCILIATION",
                is_provider_confirmed_terminal=False,
                created_at=datetime.now(timezone.utc) - timedelta(hours=75)
            )
            session.add(old_dep)
            session.commit()
            old_dep_id = old_dep.deposit_id

        create_count_before = len(self.paypal_client.create_calls)
        with SessionLocal() as session:
            rec = reconcile_deposit(session, self.paypal_client, DEMO_USER_ID, old_dep_id)
            self.assertEqual(rec.status, "REQUIRES_RECONCILIATION")
            self.assertEqual(rec.failure_code, "ORDER_RECOVERY_EXPIRED_UNCERTAIN")
            self.assertFalse(rec.is_provider_confirmed_terminal)

        # Did NOT call create_order at PayPal
        self.assertEqual(len(self.paypal_client.create_calls), create_count_before)

    def test_concurrent_create_order_requests_same_key_use_claim_lease(self):
        """Concurrent requests with identical idempotency key use atomic claim lease; exactly 1 provider order created."""
        from concurrent.futures import ThreadPoolExecutor
        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            if account:
                session.query(PaymentDepositRecord).filter(PaymentDepositRecord.account_id == account.id).delete()
                session.commit()
        same_key = f"concurrent-same-key-{uuid4()}"

        def submit_same(_):
            with self.app.test_client() as client:
                return client.post("/api/wallet/paypal/create-order", json={
                    "amount": "100.00",
                    "currency": "USD",
                    "idempotency_key": same_key
                })

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(submit_same, range(2)))

        status_codes = [r.status_code for r in responses]
        # At least one must succeed (201). The other may get 201 or 409 ORDER_CREATION_PENDING
        self.assertIn(201, status_codes)
        for code in status_codes:
            self.assertIn(code, (200, 201, 409, 500))

        # Most critically: exactly 1 provider order was recorded in mock client
        matching_orders = [c for c in self.paypal_client.create_calls if c["amount"] == Decimal("100.00") and c["idempotency_key"].startswith("create-")]
        self.assertEqual(len(matching_orders), 1)

    def test_expired_create_order_claim_moves_to_reconciliation_and_blocks(self):
        """Expired create-order claim lease transitions to REQUIRES_RECONCILIATION and prevents unsafe new order."""
        from datetime import datetime, timezone, timedelta
        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            session.query(PaymentDepositRecord).filter(PaymentDepositRecord.account_id == account.id).delete()
            dep = PaymentDepositRecord(
                deposit_id=str(uuid4()),
                account_id=account.id,
                idempotency_key=f"lease-expired-{uuid4()}",
                provider="PAYPAL",
                paypal_order_id=None,
                payment_amount=Decimal("100.00"),
                payment_currency="USD",
                wallet_currency="INR",
                status="INTENT_CREATED",
                is_provider_confirmed_terminal=False,
                claimed_at=datetime.now(timezone.utc) - timedelta(seconds=70)  # expired lease (>60s)
            )
            session.add(dep)
            session.commit()
            dep_id = dep.deposit_id

        # Replaying or attempting creation raises 409
        res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "100.00", "currency": "USD", "idempotency_key": dep.idempotency_key
        })
        self.assertEqual(res.status_code, 409)

        # Status moved to REQUIRES_RECONCILIATION
        with SessionLocal() as session:
            d = session.scalar(select(PaymentDepositRecord).where(PaymentDepositRecord.deposit_id == dep_id))
            self.assertEqual(d.status, "REQUIRES_RECONCILIATION")
            self.assertEqual(d.failure_code, "ORDER_CREATION_CLAIM_TIMEOUT")
            self.assertFalse(d.is_provider_confirmed_terminal)

        # Different key is strictly blocked
        diff_res = self.client.post("/api/wallet/paypal/create-order", json={
            "amount": "50.00", "currency": "USD", "idempotency_key": f"diff-key-{uuid4()}"
        })
        self.assertEqual(diff_res.status_code, 409)
        self.assertEqual(diff_res.get_json()["error"]["code"], "UNRESOLVED_DEPOSIT_CONFLICT")



if __name__ == "__main__":
    unittest.main()
