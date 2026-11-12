"""Database engine/session setup, including SQLite foreign-key enforcement."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URL
from models import Base

engine = create_engine(DATABASE_URL, future=True)
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=45000")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def initialize_database():
    Base.metadata.create_all(engine)
    if DATABASE_URL.startswith("sqlite"):
        with engine.connect() as conn:
            cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(payment_deposits)").fetchall()]
            if cols:
                if "claimed_at" not in cols:
                    conn.exec_driver_sql("ALTER TABLE payment_deposits ADD COLUMN claimed_at TIMESTAMP")
                if "paypal_fee_in_receivable_currency" not in cols:
                    conn.exec_driver_sql("ALTER TABLE payment_deposits ADD COLUMN paypal_fee_in_receivable_currency NUMERIC(18, 2)")
                if "paypal_fee_in_receivable_currency_code" not in cols:
                    conn.exec_driver_sql("ALTER TABLE payment_deposits ADD COLUMN paypal_fee_in_receivable_currency_code VARCHAR(3)")
                if "approval_url" not in cols:
                    conn.exec_driver_sql("ALTER TABLE payment_deposits ADD COLUMN approval_url VARCHAR(512)")
                if "is_provider_confirmed_terminal" not in cols:
                    conn.exec_driver_sql("ALTER TABLE payment_deposits ADD COLUMN is_provider_confirmed_terminal BOOLEAN DEFAULT 0 NOT NULL")
                conn.commit()
