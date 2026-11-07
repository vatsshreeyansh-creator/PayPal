"""Small environment-based configuration for the demo application."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.getenv("TRADEPOINT_DATABASE_URL", f"sqlite:///{BASE_DIR / 'tradepoint.db'}")
DEMO_USER_ID = os.getenv("TRADEPOINT_DEMO_USER_ID", "demo-user")
SECRET_KEY = os.getenv("TRADEPOINT_SECRET_KEY", "local-development-only")
