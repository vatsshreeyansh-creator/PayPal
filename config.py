"""Small environment-based configuration for the demo application."""
import os
from pathlib import Path
from decimal import Decimal, InvalidOperation

BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.getenv("TRADEPOINT_DATABASE_URL", f"sqlite:///{BASE_DIR / 'tradepoint.db'}")
DEMO_USER_ID = os.getenv("TRADEPOINT_DEMO_USER_ID", "demo-user")
SECRET_KEY = os.getenv("TRADEPOINT_SECRET_KEY", "local-development-only")
try:
    INITIAL_CASH = Decimal(os.getenv("TRADEPOINT_INITIAL_CASH", "1000000.00"))
except InvalidOperation as exc:
    raise ValueError("TRADEPOINT_INITIAL_CASH must be a decimal amount") from exc
if not INITIAL_CASH.is_finite() or INITIAL_CASH < 0 or INITIAL_CASH.as_tuple().exponent < -2:
    raise ValueError("TRADEPOINT_INITIAL_CASH must be nonnegative with at most two decimal places")
