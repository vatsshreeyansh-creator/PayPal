"""Structured LLM boundary; implementations do not persist or mutate domain state."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable


class LLMProviderUnavailable(Exception):
    pass


@dataclass(frozen=True)
class ArticleInput:
    title: str
    source: str
    summary: str | None
    content: str | None


@dataclass(frozen=True)
class SummaryDraft:
    summary: str
    key_developments: list[str]
    reported_facts: list[str]
    positive_implications: list[str]
    negative_implications: list[str]


@dataclass(frozen=True)
class ResearchEvidence:
    article_id: str
    title: str
    source: str
    published_at: str
    summary: str | None


@dataclass(frozen=True)
class ResearchDraft:
    thesis: str
    risks: list[str]
    reported_facts: list[str]
    positive_implications: list[str]
    negative_implications: list[str]
    uncertainty: str


@runtime_checkable
class LLMProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    def summarize_article(self, article: ArticleInput) -> SummaryDraft: ...
    def research_stock(self, *, symbol: str, current_price: Decimal | None,
                       evidence: list[ResearchEvidence]) -> ResearchDraft: ...
