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
