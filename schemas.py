"""Pydantic v2 models define and validate the public JSON contract."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, field_serializer, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchRequest(ContractModel):
    query: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=20, ge=1, le=100)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be empty")
        return value


class AddWatchlistRequest(ContractModel):
    symbol: str = Field(min_length=1, max_length=32)

    @field_validator("symbol")
    @classmethod
    def clean_symbol(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("symbol must not be empty")
        return value


class StockSummary(ContractModel):
    symbol: str
    name: str
    exchange: Literal["NSE"]
    instrument_token: int = Field(gt=0)


class Quote(ContractModel):
    price: str
    currency: Literal["INR"] = "INR"
    as_of: datetime
    simulated: bool

    @field_validator("price")
    @classmethod
    def valid_price(cls, value: str) -> str:
        if not re.fullmatch(r"(?:0|[1-9]\d*)\.\d{2}", value):
            raise ValueError("price must have exactly two decimal places")
        try:
            amount = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("price must be a decimal string") from exc
        if amount <= 0:
            raise ValueError("price must be positive")
        return value

    @field_validator("as_of")
    @classmethod
    def ensure_utc(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @field_serializer("as_of")
    def serialize_as_utc_z(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class WatchlistItem(ContractModel):
    stock: StockSummary
    quote: Quote | None


class SearchResponse(ContractModel):
    results: list[StockSummary]


class AddWatchlistResponse(ContractModel):
    item: WatchlistItem
    created: bool


class GetWatchlistResponse(ContractModel):
    items: list[WatchlistItem]


class DeleteWatchlistResponse(ContractModel):
    symbol: str
    deleted: Literal[True] = True


class ErrorDetail(ContractModel):
    code: str
    message: str
    field: str | None = None


class ErrorResponse(ContractModel):
    error: ErrorDetail


# Planned product contracts. These models define data boundaries only; they do
# not imply that routes, persistence, or product behavior are implemented yet.
class AccountSummary(ContractModel):
    account_id: str
    currency: Literal["INR"]
    cash_balance: str

    @field_validator("cash_balance")
    @classmethod
    def valid_cash_balance(cls, value: str) -> str:
        if not re.fullmatch(r"(?:0|[1-9]\d*)\.\d{2}", value):
            raise ValueError("cash_balance must be a nonnegative INR decimal string with two fractional digits")
        return value


class Holding(ContractModel):
    symbol: str
    name: str
    quantity: str
    average_purchase_price: str
    current_price: str | None
    market_value: str | None
    realized_pnl: str
    unrealized_pnl: str | None
    currency: Literal["INR"]

    @field_validator("quantity")
    @classmethod
    def valid_holding_quantity(cls, value: str) -> str:
        if not re.fullmatch(r"[1-9]\d*", value):
            raise ValueError("quantity must be a positive whole-share string")
        return value

    @field_validator("average_purchase_price")
    @classmethod
    def valid_holding_money(cls, value: str) -> str:
        if not re.fullmatch(r"(?:0|[1-9]\d*)\.\d{2}", value):
            raise ValueError("holding monetary values must use two fractional digits")
        return value

    @field_validator("realized_pnl", "unrealized_pnl")
    @classmethod
    def valid_profit_loss(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"-?(?:0|[1-9]\d*)\.\d{2}", value):
            raise ValueError("profit/loss values must use two fractional digits")
        return value

    @field_validator("current_price", "market_value")
    @classmethod
    def valid_nullable_money(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"(?:0|[1-9]\d*)\.\d{2}", value):
            raise ValueError("holding monetary values must use two fractional digits")
        return value


class PortfolioSummary(ContractModel):
    account: AccountSummary
    holdings: list[Holding]
    total_portfolio_value: str | None

    @field_validator("total_portfolio_value")
    @classmethod
    def valid_total_value(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"(?:0|[1-9]\d*)\.\d{2}", value):
            raise ValueError("total_portfolio_value must use two fractional digits")
        return value


class OrderRequest(ContractModel):
    symbol: str = Field(min_length=1, max_length=32)
    side: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0, le=100000, strict=True)
    order_type: Literal["MARKET"] = "MARKET"
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("symbol")
    @classmethod
    def normalize_order_symbol(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("symbol must not be empty")
        return value

    @field_validator("idempotency_key")
    @classmethod
    def normalize_idempotency_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("idempotency_key must not be empty")
        return value

class OrderResponse(ContractModel):
    order_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0, le=100000)
    order_type: Literal["MARKET"]
    status: Literal["FILLED", "REJECTED"]
    execution_price: str | None
    rejection_reason: Literal["INSUFFICIENT_CASH", "INSUFFICIENT_SHARES", "QUOTE_UNAVAILABLE"] | None
    currency: Literal["INR"]
    created_at: datetime

    @field_validator("execution_price")
    @classmethod
    def valid_execution_price(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"(?:0|[1-9]\d*)\.\d{2}", value):
            raise ValueError("execution_price must use two fractional digits")
        return value

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")

class Transaction(ContractModel):
    transaction_id: str
    order_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: str
    price: str
    gross_amount: str
    currency: Literal["INR"]
    occurred_at: datetime

    @field_validator("quantity")
    @classmethod
    def valid_transaction_quantity(cls, value: str) -> str:
        if not re.fullmatch(r"[1-9]\d*", value):
            raise ValueError("quantity must be a positive whole number")
        return value

    @field_validator("price", "gross_amount")
    @classmethod
    def valid_money(cls, value: str) -> str:
        if not re.fullmatch(r"(?:0|[1-9]\d*)\.\d{2}", value):
            raise ValueError("money must be a decimal string with two fractional digits")
        return value

    @field_serializer("occurred_at")
    def serialize_occurred_at(self, value: datetime) -> str:
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")


class NewsArticle(ContractModel):
    article_id: str
    title: str
    source: str
    url: str
    published_at: datetime
    summary: str | None
    symbols: list[str]
    content: str | None

    @field_validator("published_at")
    @classmethod
    def normalize_published_at(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @field_serializer("published_at")
    def serialize_published_at(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class NewsSearchResponse(ContractModel):
    articles: list[NewsArticle]
    scope: Literal["personal", "market"]
    next_page_token: str | None


class NewsFeedRequest(ContractModel):
    scope: Literal["personal", "market"] = "personal"
    query: str | None = Field(default=None, min_length=1, max_length=200)
    symbols: list[str] | None = Field(default=None, max_length=20)
    page_token: str | None = None
    page_size: int = Field(default=20, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def clean_news_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("query must not be empty")
        return value

    @field_validator("symbols")
    @classmethod
    def normalize_news_symbols(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = list(dict.fromkeys(value.strip().upper() for value in values if value.strip()))
        if not normalized:
            raise ValueError("symbols must contain at least one symbol")
        return normalized


class SummaryResponse(ContractModel):
    article_id: str
    summary: str
    key_developments: list[str]
    reported_facts: list[str]
    positive_implications: list[str]
    negative_implications: list[str]
    disclaimer: str
    provider: str


class ResearchSuggestion(ContractModel):
    symbol: str
    provider: str
    thesis: str
    risks: list[str]
    evidence_article_ids: list[str]
    generated_at: datetime
    reported_facts: list[str]
    positive_implications: list[str]
    negative_implications: list[str]
    uncertainty: str
    informational_only: Literal[True] = True

    @field_serializer("generated_at")
    def serialize_generated_at(self, value: datetime) -> str:
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")


class ResearchResponse(ContractModel):
    suggestions: list[ResearchSuggestion]
    disclaimer: str


class ResearchRequest(ContractModel):
    symbol: str = Field(min_length=1, max_length=32)

    @field_validator("symbol")
    @classmethod
    def normalize_research_symbol(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("symbol must not be empty")
        return value


class ConversationCreateRequest(ContractModel):
    context_type: Literal["article", "research"]
    article_id: str | None = None
    symbol: str | None = Field(default=None, min_length=1, max_length=32)
    research_context: ResearchSuggestion | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_conversation_symbol(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if not value:
            raise ValueError("symbol must not be empty")
        return value

    @model_validator(mode="after")
    def validate_context_reference(self):
        if self.context_type == "article" and (not self.article_id or self.symbol is not None or self.research_context is not None):
            raise ValueError("article context requires article_id only")
        if self.context_type == "research" and (not self.symbol or self.article_id is not None or self.research_context is None):
            raise ValueError("research context requires symbol and research_context only")
        if self.research_context is not None and self.research_context.symbol != self.symbol:
            raise ValueError("research context symbol must match symbol")
        return self


class ConversationMessageRequest(ContractModel):
    request_id: UUID
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def clean_conversation_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be empty")
        return value


class ConversationTurn(ContractModel):
    role: Literal["user", "assistant"]
    content: str
    provider: str | None
    created_at: datetime

    @field_serializer("created_at")
    def serialize_turn_created_at(self, value: datetime) -> str:
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")


class ConversationResponse(ContractModel):
    conversation_id: str
    context_type: Literal["article", "research"]
    context_reference: str
    context_title: str
    messages: list[ConversationTurn]
    created_at: datetime

    @field_serializer("created_at")
    def serialize_conversation_created_at(self, value: datetime) -> str:
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")


# Wallet and PayPal Sandbox (USD payment -> INR ledger settlement)
class PayPalCreateOrderRequest(ContractModel):
    amount: str
    currency: Literal["USD"] = "USD"
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("amount")
    @classmethod
    def valid_deposit_amount(cls, value: str) -> str:
        if not re.fullmatch(r"(?:0|[1-9]\d*)\.\d{2}", value):
            raise ValueError("amount must be a decimal string with two fractional digits")
        try:
            val = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("amount must be a decimal string") from exc
        if val <= 0:
            raise ValueError("amount must be positive")
        return value

    @field_validator("idempotency_key")
    @classmethod
    def clean_idempotency_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("idempotency_key must not be empty")
        return value


class PayPalCreateOrderResponse(ContractModel):
    deposit_id: str
    paypal_order_id: str
    status: Literal["CREATED"]
    payment_amount: str
    payment_currency: Literal["USD"]
    payment_mode: Literal["mock", "sandbox"] | None = None
    approval_url: str | None = None


class PayPalCaptureOrderRequest(ContractModel):
    paypal_order_id: str = Field(min_length=1, max_length=64)

    @field_validator("paypal_order_id")
    @classmethod
    def clean_paypal_order_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("paypal_order_id must not be empty")
        return value


class PayPalCaptureOrderResponse(ContractModel):
    deposit_id: str
    paypal_order_id: str
    paypal_capture_id: str | None = None
    status: Literal["COMPLETED", "REQUIRES_RECONCILIATION", "FAILED"]
    payment_amount: str
    payment_currency: Literal["USD"]
    paypal_fee_amount: str | None = None
    paypal_fee_currency: str | None = None
    paypal_fee_in_receivable_currency: str | None = None
    paypal_fee_in_receivable_currency_code: str | None = None
    net_payment_amount: str | None = None
    exchange_rate: str | None = None
    exchange_rate_source_currency: str | None = None
    exchange_rate_target_currency: str | None = None
    wallet_credit_amount: str | None = None
    wallet_currency: Literal["INR"] = "INR"
    updated_cash_balance: str
    failure_code: str | None = None
    failure_reason: str | None = None
    completed_at: datetime | None = None

    @field_serializer("completed_at")
    def serialize_completed_at(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")


class PayPalCancelOrderRequest(ContractModel):
    paypal_order_id: str = Field(min_length=1, max_length=64)

    @field_validator("paypal_order_id")
    @classmethod
    def clean_paypal_order_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("paypal_order_id must not be empty")
        return value


class PayPalCancelOrderResponse(ContractModel):
    deposit_id: str
    paypal_order_id: str
    status: Literal["CANCELLED"]


class WalletSummaryResponse(ContractModel):
    account_id: str
    currency: Literal["INR"] = "INR"
    cash_balance: str
    total_deposited: str
    payment_mode: Literal["mock", "sandbox"] | None = None


class WalletHistoryItem(ContractModel):
    entry_id: int
    entry_key: str
    category: Literal[
        "INITIAL_CASH", "DEPOSIT", "STOCK_BUY", "STOCK_SELL",
        "SUBSCRIPTION", "REPORT_PURCHASE", "REFUND"
    ]
    amount: str
    currency: Literal["INR"] = "INR"
    description: str
    reference_id: str | None = None
    payment_amount: str | None = None
    payment_currency: str | None = None
    exchange_rate: str | None = None
    created_at: datetime

    @field_serializer("created_at")
    def serialize_history_created_at(self, value: datetime) -> str:
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")


class WalletHistoryResponse(ContractModel):
    items: list[WalletHistoryItem]

