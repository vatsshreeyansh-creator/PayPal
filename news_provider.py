"""Normalized news provider boundary; no network implementation in MVP."""
from typing import Protocol, runtime_checkable
from schemas import NewsArticle


class NewsProviderUnavailable(Exception):
    pass


@runtime_checkable
class NewsProvider(Protocol):
    def search_articles(self, query: str, symbols: list[str], limit: int) -> list[NewsArticle]: ...
    def get_article(self, article_id: str) -> NewsArticle | None: ...
