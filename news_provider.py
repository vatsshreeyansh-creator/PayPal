"""Normalized news-provider boundary. Provider IDs are scoped by source."""
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


class NewsProviderUnavailable(Exception):
    pass


@dataclass(frozen=True)
class ArticleData:
    provider_article_id: str
    title: str
    source: str
    url: str
    published_at: datetime
    summary: str | None
    symbols: list[str]
    content: str | None


@dataclass(frozen=True)
class NewsPage:
    articles: list[ArticleData]
    next_page_token: str | None


@runtime_checkable
class NewsProvider(Protocol):
    def search_articles(self, *, query: str | None, symbols: list[str],
                        page_token: str | None, page_size: int) -> NewsPage: ...
    def get_article(self, *, source: str, provider_article_id: str) -> ArticleData | None: ...
