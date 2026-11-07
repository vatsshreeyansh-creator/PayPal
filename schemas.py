"""Pydantic v2 models define and validate the public JSON contract."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, field_serializer


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


class PortfolioSummary(ContractModel):
    account: AccountSummary
    holdings: list[Holding]
    total_portfolio_value: str


class OrderRequest(ContractModel):
    symbol: str = Field(min_length=1, max_length=32)
    side: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0, le=100000)
    order_type: Literal["MARKET"] = "MARKET"
    idempotency_key: str = Field(min_length=1, max_length=128)

class OrderResponse(ContractModel):
    order_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0, le=100000)
    order_type: Literal["MARKET"]
    status: Literal["FILLED", "REJECTED"]
    execution_price: str | None
    currency: Literal["INR"]
    created_at: datetime

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


class NewsArticle(ContractModel):
    article_id: str
    title: str
    source: str
    url: str
    published_at: datetime
    summary: str | None
    symbols: list[str]


class NewsSearchResponse(ContractModel):
    articles: list[NewsArticle]


class SummaryRequest(ContractModel):
    text: str = Field(min_length=1, max_length=30000)


class SummaryResponse(ContractModel):
    article_id: str
    summary: str
    provider: str


class ResearchSuggestion(ContractModel):
    symbol: str
    thesis: str
    risks: list[str]
    evidence_article_ids: list[str]
    generated_at: datetime
    informational_only: Literal[True] = True


class ResearchResponse(ContractModel):
    suggestions: list[ResearchSuggestion]
    disclaimer: str


class ResearchRequest(ContractModel):
    question: str = Field(min_length=1, max_length=2000)
    symbols: list[str] = Field(min_length=1, max_length=20)
