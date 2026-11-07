"""Application service protocols used as stable seams for independent work."""
from typing import Protocol, runtime_checkable
from schemas import (AccountSummary, GetWatchlistResponse, NewsSearchResponse,
                     OrderRequest, OrderResponse, PortfolioSummary, ResearchResponse,
                     SummaryResponse, Transaction)


@runtime_checkable
class AccountService(Protocol):
    def get_account(self, account_id: str) -> AccountSummary: ...


@runtime_checkable
class PortfolioService(Protocol):
    def get_portfolio(self, account_id: str) -> PortfolioSummary: ...


@runtime_checkable
class TradingService(Protocol):
    def place_order(self, account_id: str, request: OrderRequest) -> OrderResponse: ...
    def list_transactions(self, account_id: str) -> list[Transaction]: ...


@runtime_checkable
class NewsService(Protocol):
    def search_news(self, query: str, symbols: list[str], limit: int) -> NewsSearchResponse: ...


@runtime_checkable
class ResearchService(Protocol):
    def summarize_article(self, article_id: str) -> SummaryResponse: ...
    def suggest(self, question: str, symbols: list[str]) -> ResearchResponse: ...
