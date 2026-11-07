"""Application service protocols used as stable seams for independent work."""
from typing import Protocol, runtime_checkable
from sqlalchemy.orm import Session
from provider import MarketDataProvider
from schemas import (AccountSummary, GetWatchlistResponse, NewsArticle, NewsFeedRequest,
                     NewsSearchResponse, OrderRequest, OrderResponse, PortfolioSummary,
                     ResearchRequest, ResearchResponse, SummaryResponse, Transaction)


@runtime_checkable
class AccountService(Protocol):
    def get_account(self, session: Session, account_id: str) -> AccountSummary: ...


@runtime_checkable
class PortfolioService(Protocol):
    def get_portfolio(self, session: Session, provider: MarketDataProvider,
                      account_id: str) -> PortfolioSummary: ...


@runtime_checkable
class TradingService(Protocol):
    def place_order(self, session: Session, provider: MarketDataProvider,
                    account_id: str, request: OrderRequest) -> tuple[OrderResponse, bool]: ...
    def get_order(self, session: Session, account_id: str, order_id: str) -> OrderResponse: ...
    def list_orders(self, session: Session, account_id: str) -> list[OrderResponse]: ...
    def list_transactions(self, account_id: str) -> list[Transaction]: ...


@runtime_checkable
class NewsService(Protocol):
    def search_news(self, request: NewsFeedRequest) -> NewsSearchResponse: ...
    def get_article(self, article_id: str) -> NewsArticle: ...


@runtime_checkable
class ResearchService(Protocol):
    def summarize_article(self, article_id: str) -> SummaryResponse: ...
    def suggest(self, request: ResearchRequest) -> ResearchResponse: ...
