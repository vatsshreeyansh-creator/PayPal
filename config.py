"""Small environment-based configuration for the demo application."""
import os

# Ensure SQLAlchemy pure-Python fallback is enabled if C extensions are blocked by OS/Application Control
if "DISABLE_SQLALCHEMY_CEXT" not in os.environ:
    os.environ["DISABLE_SQLALCHEMY_CEXT"] = "1"

from pathlib import Path
from decimal import Decimal, InvalidOperation
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent


def load_local_environment(directory: Path = BASE_DIR) -> None:
    """Load developer-local settings without overriding host-provided variables."""
    load_dotenv(directory / ".env.local", override=False)


load_local_environment()

DATABASE_URL = os.getenv("TRADEPOINT_DATABASE_URL", f"sqlite:///{BASE_DIR / 'tradepoint.db'}")
DEMO_USER_ID = os.getenv("TRADEPOINT_DEMO_USER_ID", "demo-user")
SECRET_KEY = os.getenv("TRADEPOINT_SECRET_KEY", "local-development-only")
try:
    INITIAL_CASH = Decimal(os.getenv("TRADEPOINT_INITIAL_CASH", "1000000.00"))
except InvalidOperation as exc:
    raise ValueError("TRADEPOINT_INITIAL_CASH must be a decimal amount") from exc
if not INITIAL_CASH.is_finite() or INITIAL_CASH < 0 or INITIAL_CASH.as_tuple().exponent < -2:
    raise ValueError("TRADEPOINT_INITIAL_CASH must be nonnegative with at most two decimal places")

# PayPal Sandbox configuration (USD payments settling into INR wallet)
def validate_paypal_environment(raw_env: str | None, raw_url: str | None) -> tuple[str, str]:
    """Strictly enforce sandbox-only configuration in this stage."""
    if raw_env is None:
        env = "sandbox"
    else:
        env_clean = raw_env.strip()
        if not env_clean:
            raise ValueError("PAYPAL_ENVIRONMENT cannot be empty. Only 'sandbox' is permitted in this stage.")
        if env_clean.lower() != "sandbox":
            raise ValueError(f"Invalid PAYPAL_ENVIRONMENT '{raw_env}'. Only 'sandbox' is permitted in this stage.")
        env = "sandbox"

    if raw_url is None:
        base_url = "https://api-m.sandbox.paypal.com"
    else:
        base_url = raw_url.strip()
        if not base_url:
            base_url = "https://api-m.sandbox.paypal.com"

    # Reject production PayPal URLs
    prohibited_hosts = ("api-m.paypal.com", "api.paypal.com")
    for host in prohibited_hosts:
        if host in base_url.lower():
            raise ValueError(
                f"Production PayPal URL '{base_url}' is strictly prohibited. Only sandbox endpoints are permitted in this stage."
            )

    return env, base_url


PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
PAYPAL_ENVIRONMENT, PAYPAL_BASE_URL = validate_paypal_environment(
    os.getenv("PAYPAL_ENVIRONMENT"),
    os.getenv("PAYPAL_BASE_URL")
)
PAYMENT_CURRENCY = "USD"
WALLET_CURRENCY = "INR"

