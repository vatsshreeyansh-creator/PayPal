"""SQLAlchemy 2.x models. Quotes are intentionally not persisted."""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("exchange", "symbol", name="uq_instrument_exchange_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exchange: Mapped[str] = mapped_column(String(8), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    instrument_token: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    instrument_type: Mapped[str] = mapped_column(String(16), nullable=False)


class WatchlistEntry(Base):
    __tablename__ = "watchlist_entries"
    __table_args__ = (UniqueConstraint("user_id", "instrument_id", name="uq_watchlist_user_instrument"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Account(Base):
    """Persisted demo account; balance remains the configured starting cash until trading exists."""
    __tablename__ = "accounts"
    __table_args__ = (CheckConstraint("initial_cash >= 0", name="ck_account_initial_cash_nonnegative"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    holdings: Mapped[list["Holding"]] = relationship(back_populates="account", cascade="all, delete-orphan")
    cash_entries: Mapped[list["CashLedgerEntry"]] = relationship(back_populates="account", cascade="all, delete-orphan")


class Holding(Base):
    """Persisted position foundation; no code in this slice executes trades."""
    __tablename__ = "holdings"
    __table_args__ = (
        UniqueConstraint("account_id", "instrument_id", name="uq_holding_account_instrument"),
        CheckConstraint("quantity > 0", name="ck_holding_quantity_positive"),
        CheckConstraint("average_purchase_price >= 0", name="ck_holding_average_price_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # Keep sub-cent internal precision for weighted cost basis; APIs still emit INR cents.
    average_purchase_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"))

    account: Mapped[Account] = relationship(back_populates="holdings")
    instrument: Mapped[Instrument] = relationship()


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("account_id", "idempotency_key", name="uq_order_account_idempotency"),
        CheckConstraint("quantity > 0 AND quantity <= 100000", name="ck_order_quantity_range"),
        CheckConstraint("side IN ('BUY', 'SELL')", name="ck_order_side"),
        CheckConstraint("order_type = 'MARKET'", name="ck_order_market_type"),
        CheckConstraint("status IN ('FILLED', 'REJECTED')", name="ck_order_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    order_type: Mapped[str] = mapped_column(String(8), nullable=False, default="MARKET")
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    execution_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    account: Mapped[Account] = relationship()
    instrument: Mapped[Instrument] = relationship()


class TransactionRecord(Base):
    __tablename__ = "transactions"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_transaction_quantity_positive"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id", ondelete="RESTRICT"), nullable=False, unique=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CashLedgerEntry(Base):
    __tablename__ = "cash_ledger_entries"
    __table_args__ = (UniqueConstraint("account_id", "entry_key", name="uq_cash_ledger_entry_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.order_id", ondelete="RESTRICT"), nullable=True)
    entry_key: Mapped[str] = mapped_column(String(140), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(24), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    account: Mapped[Account] = relationship(back_populates="cash_entries")


class ArticleRecord(Base):
    __tablename__ = "news_articles"
    __table_args__ = (UniqueConstraint("source", "provider_article_id", name="uq_news_source_provider_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String(160), nullable=False)
    provider_article_id: Mapped[str] = mapped_column(String(256), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    symbols: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ArticleSummaryRecord(Base):
    __tablename__ = "article_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[str] = mapped_column(ForeignKey("news_articles.article_id", ondelete="CASCADE"), nullable=False, unique=True)
    summary: Mapped[str] = mapped_column(String(4000), nullable=False)
    key_developments: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reported_facts: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    positive_implications: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    negative_implications: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
