"""PayPal REST API v2 client and normalized provider protocol."""
from decimal import Decimal
import os
import time
from typing import Any, Protocol
import urllib.error
import urllib.parse
import urllib.request
import json
from uuid import uuid4

from config import PAYPAL_BASE_URL, PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET


class PayPalError(Exception):
    def __init__(self, message: str, status_code: int | None = None, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class PayPalOrderAlreadyCaptured(PayPalError):
    pass


class PayPalNetworkError(PayPalError):
    pass


class InvalidApprovalUrlError(PayPalError):
    pass


ALLOWED_SANDBOX_PAYPAL_HOSTS = frozenset({"www.sandbox.paypal.com", "sandbox.paypal.com"})
REJECTED_PRODUCTION_PAYPAL_HOSTS = frozenset({"www.paypal.com", "paypal.com"})


def extract_and_validate_approval_url(order_data: dict[str, Any], is_sandbox: bool = True) -> str:
    """Extract and strictly validate customer approval URL from PayPal Orders v2 response."""
    links = order_data.get("links", [])
    if not isinstance(links, list):
        raise InvalidApprovalUrlError("PayPal order response contains invalid 'links' structure")

    approval_href = None
    for link in links:
        if isinstance(link, dict) and link.get("rel") in ("approve", "payer-action"):
            approval_href = link.get("href")
            break

    if not approval_href or not isinstance(approval_href, str):
        raise InvalidApprovalUrlError("PayPal order response does not contain an approval link ('approve' or 'payer-action')")

    try:
        parsed = urllib.parse.urlparse(approval_href.strip())
    except Exception as exc:
        raise InvalidApprovalUrlError(f"Malformed approval URL: {exc}") from exc

    if parsed.scheme.lower() != "https":
        raise InvalidApprovalUrlError(f"Approval URL must use HTTPS scheme, got '{parsed.scheme}'")

    if "@" in parsed.netloc or parsed.username or parsed.password:
        raise InvalidApprovalUrlError("Approval URL contains embedded user credentials")

    hostname = parsed.hostname
    if not hostname:
        raise InvalidApprovalUrlError("Approval URL has no valid hostname")

    hostname = hostname.lower()

    if parsed.port is not None and parsed.port != 443:
        raise InvalidApprovalUrlError(f"Approval URL contains unexpected port '{parsed.port}'")

    if hostname in REJECTED_PRODUCTION_PAYPAL_HOSTS and is_sandbox:
        raise InvalidApprovalUrlError(f"Production PayPal approval URL '{hostname}' is rejected in Sandbox environment")

    if is_sandbox:
        if hostname not in ALLOWED_SANDBOX_PAYPAL_HOSTS:
            raise InvalidApprovalUrlError(
                f"Approval URL hostname '{hostname}' is not an authorized Sandbox PayPal host ({sorted(ALLOWED_SANDBOX_PAYPAL_HOSTS)})"
            )
    else:
        raise InvalidApprovalUrlError("Production PayPal environment is not configured")

    return approval_href


class PayPalClient(Protocol):
    def create_order(self, amount: Decimal, currency: str, idempotency_key: str) -> dict[str, Any]:
        ...

    def capture_order(self, paypal_order_id: str, idempotency_key: str) -> dict[str, Any]:
        ...

    def get_order(self, paypal_order_id: str) -> dict[str, Any]:
        ...


class LivePayPalClient:
    """Production/Sandbox HTTP client for official PayPal Orders v2 API."""
    mode: str = "sandbox"

    def __init__(self, client_id: str = PAYPAL_CLIENT_ID,
                 client_secret: str = PAYPAL_CLIENT_SECRET,
                 base_url: str = PAYPAL_BASE_URL):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url.rstrip("/")
        self._access_token: str | None = None
        self._token_expires_at: float = 0

    def _get_access_token(self) -> str:
        now = time.time()
        if self._access_token and now < self._token_expires_at - 60:
            return self._access_token

        url = f"{self.base_url}/v1/oauth2/token"
        req = urllib.request.Request(
            url,
            data=b"grant_type=client_credentials",
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        import base64
        auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        req.add_header("Authorization", f"Basic {auth}")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                self._access_token = data["access_token"]
                self._token_expires_at = now + data.get("expires_in", 3600)
                return self._access_token
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
            raise PayPalError(f"PayPal OAuth failed ({exc.code}): {body}", status_code=exc.code) from exc
        except Exception as exc:
            raise PayPalNetworkError(f"PayPal connection error: {exc}") from exc

    def create_order(self, amount: Decimal, currency: str, idempotency_key: str) -> dict[str, Any]:
        token = self._get_access_token()
        url = f"{self.base_url}/v2/checkout/orders"
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "amount": {
                    "currency_code": currency,
                    "value": f"{amount:.2f}"
                }
            }]
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "PayPal-Request-Id": idempotency_key
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
            raise PayPalError(f"PayPal create order failed ({exc.code}): {body}", status_code=exc.code) from exc
        except Exception as exc:
            raise PayPalNetworkError(f"PayPal network error during create order: {exc}") from exc

    def capture_order(self, paypal_order_id: str, idempotency_key: str) -> dict[str, Any]:
        token = self._get_access_token()
        url = f"{self.base_url}/v2/checkout/orders/{urllib.parse.quote(paypal_order_id)}/capture"
        req = urllib.request.Request(
            url,
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "PayPal-Request-Id": idempotency_key
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode()
            try:
                body_json = json.loads(body_text)
            except Exception:
                body_json = {}

            # Detect ORDER_ALREADY_CAPTURED issue
            details = body_json.get("details", [])
            if any(d.get("issue") == "ORDER_ALREADY_CAPTURED" for d in details):
                raise PayPalOrderAlreadyCaptured("Order already captured on PayPal", status_code=422, details=body_json)
            raise PayPalError(f"PayPal capture order failed ({exc.code}): {body_text}", status_code=exc.code, details=body_json) from exc
        except Exception as exc:
            raise PayPalNetworkError(f"PayPal network error during capture: {exc}") from exc

    def get_order(self, paypal_order_id: str) -> dict[str, Any]:
        token = self._get_access_token()
        url = f"{self.base_url}/v2/checkout/orders/{urllib.parse.quote(paypal_order_id)}"
        req = urllib.request.Request(
            url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
            raise PayPalError(f"PayPal get order failed ({exc.code}): {body}", status_code=exc.code) from exc
        except Exception as exc:
            raise PayPalNetworkError(f"PayPal network error during get order: {exc}") from exc


class MockPayPalClient:
    """Deterministic in-memory mock client for tests with realistic USD-to-INR conversions."""
    mode: str = "mock"

    def __init__(self, default_rate: Decimal = Decimal("85.0000"),
                 fee_percent: Decimal = Decimal("0.035")):
        self.default_rate = default_rate
        self.fee_percent = fee_percent
        self.orders: dict[str, dict[str, Any]] = {}
        self.orders_by_idempotency_key: dict[str, dict[str, Any]] = {}
        self.create_calls: list[dict[str, Any]] = []
        self.capture_calls: list[dict[str, Any]] = []
        self.simulate_network_timeout: bool = False
        self.simulate_timeout_after_capture: bool = False
        self.simulate_500_after_capture: bool = False
        self.simulate_malformed_capture_response: bool = False
        self.simulate_missing_capture_id: bool = False
        self.simulate_create_timeout_after_order: bool = False
        self.simulate_create_500: bool = False
        self.simulate_missing_receivable: bool = False
        self.simulate_currency_mismatch: bool = False
        self.simulate_already_captured: bool = False
        self.simulate_declined: bool = False
        self.simulate_rate_direction_inversion: bool = False
        self.simulate_gross_mismatch: bool = False
        self.simulate_net_mismatch: bool = False
        self.simulate_excessive_discrepancy: bool = False
        self.include_fee_in_receivable_currency: bool = False
        self.fee_in_receivable_currency_value: Decimal | None = None
        self.include_approval_link: bool = False
        self.custom_approval_href: str | None = None

    def create_order(self, amount: Decimal, currency: str, idempotency_key: str) -> dict[str, Any]:
        if self.simulate_create_500:
            raise PayPalError("PayPal API internal error 500", status_code=500)

        if self.simulate_network_timeout:
            raise PayPalNetworkError("Mock network timeout during order creation")

        # Stable provider idempotency cache check
        if idempotency_key in self.orders_by_idempotency_key:
            return self.orders_by_idempotency_key[idempotency_key]

        self.create_calls.append({"amount": amount, "currency": currency, "idempotency_key": idempotency_key})
        order_id = f"MOCK-PAYPAL-{uuid4().hex[:12].upper()}"
        order = {
            "id": order_id,
            "status": "CREATED",
            "intent": "CAPTURE",
            "purchase_units": [{
                "amount": {
                    "currency_code": currency,
                    "value": f"{amount:.2f}"
                }
            }]
        }
        if self.include_approval_link:
            href = self.custom_approval_href or f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}"
            order["links"] = [{"href": href, "rel": "approve", "method": "GET"}]
        self.orders[order_id] = order
        self.orders_by_idempotency_key[idempotency_key] = order

        if self.simulate_create_timeout_after_order:
            raise PayPalNetworkError("Mock network timeout after order creation at PayPal")

        return order

    def capture_order(self, paypal_order_id: str, idempotency_key: str) -> dict[str, Any]:
        self.capture_calls.append({"order_id": paypal_order_id, "idempotency_key": idempotency_key})
        if self.simulate_network_timeout:
            raise PayPalNetworkError("Mock network timeout during capture")

        if self.simulate_already_captured:
            raise PayPalOrderAlreadyCaptured("Order already captured", status_code=422, details={"details": [{"issue": "ORDER_ALREADY_CAPTURED"}]})

        if self.simulate_declined:
            raise PayPalError("Card declined", status_code=422, details={"details": [{"issue": "INSTRUMENT_DECLINED"}]})

        order = self.orders.get(paypal_order_id)
        if not order:
            # Generate deterministic fallback
            order = {
                "id": paypal_order_id,
                "status": "CREATED",
                "purchase_units": [{"amount": {"currency_code": "USD", "value": "100.00"}}]
            }
            self.orders[paypal_order_id] = order

        unit = order["purchase_units"][0]
        usd_gross = Decimal(unit["amount"]["value"])
        if self.simulate_gross_mismatch:
            usd_gross = usd_gross + Decimal("10.00")

        usd_fee = (usd_gross * self.fee_percent).quantize(Decimal("0.01"))
        usd_net = usd_gross - usd_fee
        if self.simulate_net_mismatch:
            usd_net = usd_net - Decimal("5.00")

        if self.simulate_currency_mismatch:
            target_currency = "EUR"
            rate = Decimal("0.9200")
            receivable = (usd_net * rate).quantize(Decimal("0.01"))
        else:
            target_currency = "INR"
            rate = self.default_rate
            receivable = (usd_net * rate).quantize(Decimal("0.01"))

        if self.simulate_excessive_discrepancy:
            receivable = receivable + Decimal("15.00")  # Major unexplained discrepancy

        capture_id = f"CAP-{uuid4().hex[:12].upper()}"
        capture_obj: dict[str, Any] = {
            "id": capture_id,
            "status": "COMPLETED",
            "amount": {
                "currency_code": "USD",
                "value": f"{usd_gross:.2f}"
            }
        }

        if not self.simulate_missing_receivable:
            source_curr = "INR" if self.simulate_rate_direction_inversion else "USD"
            target_curr = "USD" if self.simulate_rate_direction_inversion else target_currency

            breakdown_dict: dict[str, Any] = {
                "gross_amount": {"currency_code": "USD", "value": f"{usd_gross:.2f}"},
                "paypal_fee": {"currency_code": "USD", "value": f"{usd_fee:.2f}"},
                "net_amount": {"currency_code": "USD", "value": f"{usd_net:.2f}"},
                "receivable_amount": {"currency_code": target_currency, "value": f"{receivable:.2f}"},
                "exchange_rate": {
                    "source_currency": source_curr,
                    "target_currency": target_curr,
                    "value": f"{rate:.6f}"
                }
            }

            if self.include_fee_in_receivable_currency:
                fee_val = self.fee_in_receivable_currency_value or (usd_fee * rate).quantize(Decimal("0.01"))
                breakdown_dict["paypal_fee_in_receivable_currency"] = {
                    "currency_code": target_currency,
                    "value": f"{fee_val:.2f}"
                }

            capture_obj["seller_receivable_breakdown"] = breakdown_dict

        order["status"] = "COMPLETED"
        order["purchase_units"][0]["payments"] = {"captures": [capture_obj]}

        if self.simulate_timeout_after_capture:
            # Order is captured on PayPal, but response times out before reaching caller
            raise PayPalNetworkError("Mock network timeout after successful capture")

        if self.simulate_500_after_capture:
            # Order is captured on PayPal, but response returns HTTP 500
            raise PayPalError("PayPal API error 500: Internal Server Error", status_code=500)

        if self.simulate_missing_capture_id:
            # Capture succeeded on PayPal, but response payload omitted capture ID
            cap_without_id = dict(capture_obj)
            cap_without_id.pop("id", None)
            order_copy = dict(order)
            unit_copy = dict(order["purchase_units"][0])
            unit_copy["payments"] = {"captures": [cap_without_id]}
            order_copy["purchase_units"] = [unit_copy]
            return order_copy

        if self.simulate_malformed_capture_response:
            # Capture succeeded on PayPal, but returned malformed payload
            return {"malformed_response": True}

        return order

    def get_order(self, paypal_order_id: str) -> dict[str, Any]:
        if self.simulate_network_timeout:
            raise PayPalNetworkError("Mock network timeout during get order")
        order = self.orders.get(paypal_order_id)
        if not order:
            # If requested for a captured order, return synthetic capture
            return self.capture_order(paypal_order_id, f"synth-get-{paypal_order_id}")
        return order


def get_default_paypal_client() -> PayPalClient:
    if PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET:
        return LivePayPalClient()
    return MockPayPalClient()

