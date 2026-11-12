"""SQLAlchemy 2.x models. Quotes are intentionally not persisted."""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, func, text
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


class ConversationRecord(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    context_type: Mapped[str] = mapped_column(String(16), nullable=False)
    context_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    context_title: Mapped[str] = mapped_column(String(512), nullable=False)
    context_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    messages: Mapped[list["ConversationMessageRecord"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="ConversationMessageRecord.id"
    )


class ConversationMessageRecord(Base):
    __tablename__ = "ai_conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("ai_conversations.conversation_id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    conversation: Mapped[ConversationRecord] = relationship(back_populates="messages")


class ConversationExchangeRecord(Base):
    """Idempotency ledger for one atomic user/assistant exchange."""
    __tablename__ = "ai_conversation_exchanges"

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("ai_conversations.conversation_id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_content: Mapped[str] = mapped_column(Text, nullable=False)
    user_message_id: Mapped[int] = mapped_column(
        ForeignKey("ai_conversation_messages.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    assistant_message_id: Mapped[int] = mapped_column(
        ForeignKey("ai_conversation_messages.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PaymentDepositRecord(Base):
    """Persisted external wallet deposit tracking both USD payment and INR ledger settlement."""
    __tablename__ = "payment_deposits"
    __table_args__ = (
        UniqueConstraint("account_id", "idempotency_key", name="uq_deposit_account_idempotency"),
        UniqueConstraint("paypal_order_id", name="uq_deposit_paypal_order_id"),
        UniqueConstraint("paypal_capture_id", name="uq_deposit_paypal_capture_id"),
        CheckConstraint("payment_amount > 0", name="ck_deposit_payment_amount_positive"),
        CheckConstraint("wallet_credit_amount IS NULL OR wallet_credit_amount > 0", name="ck_deposit_wallet_credit_positive"),
        CheckConstraint(
            "status IN ('INTENT_CREATED', 'CREATED', 'CAPTURE_PENDING', 'COMPLETED', 'FAILED', 'CANCELLED', 'REQUIRES_RECONCILIATION')",
            name="ck_deposit_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deposit_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False, default="PAYPAL")
    paypal_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paypal_capture_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    payment_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    paypal_fee_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    paypal_fee_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    paypal_fee_in_receivable_currency: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    paypal_fee_in_receivable_currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    net_payment_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    exchange_rate_source_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    exchange_rate_target_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    wallet_credit_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    wallet_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="INTENT_CREATED")
    is_provider_confirmed_terminal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default=text("0"))
    approval_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    account: Mapped[Account] = relationship()

