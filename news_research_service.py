"""News ingestion, deduplication, article retrieval, summaries and research orchestration."""
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
from models import (Account, ArticleRecord, ArticleSummaryRecord, Holding,
                    Instrument, WatchlistEntry)
from news_provider import ArticleData, NewsPage, NewsProvider, NewsProviderUnavailable
from llm_provider import (ArticleInput, LLMProvider, LLMProviderUnavailable,
                          ResearchEvidence)
from provider import InstrumentData, MarketDataProvider
from schemas import (NewsArticle, NewsFeedRequest, NewsSearchResponse,
                    ResearchRequest, ResearchResponse, ResearchSuggestion,
                    SummaryResponse)


class ArticleNotFound(Exception): pass
class ArticleContentUnavailable(Exception): pass
class NewsUnavailable(Exception): pass
class ResearchUnavailable(Exception): pass
class ResearchStockNotFound(Exception): pass


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        raise ValueError("provider article URL must be absolute")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.casefold().startswith("utm_") and k.casefold() not in {"fbclid", "gclid"}]
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path.rstrip("/"),
                       urlencode(query, doseq=True), ""))


def _article_schema(row: ArticleRecord) -> NewsArticle:
    return NewsArticle(article_id=row.article_id, title=row.title, source=row.source, url=row.url,
                       published_at=row.published_at, summary=row.summary,
                       symbols=row.symbols or [], content=row.content)


def _upsert_article(session: Session, data: ArticleData) -> ArticleRecord:
    canonical = canonicalize_url(data.url)
    row = session.scalar(select(ArticleRecord).where(ArticleRecord.canonical_url == canonical))
    if row is None:
        row = session.scalar(select(ArticleRecord).where(
            ArticleRecord.source == data.source,
            ArticleRecord.provider_article_id == data.provider_article_id))
    if row is None:
        row = ArticleRecord(article_id=str(uuid4()), source=data.source,
                            provider_article_id=data.provider_article_id, canonical_url=canonical,
                            title=data.title, url=data.url, published_at=data.published_at,
                            summary=data.summary, symbols=sorted(set(s.upper() for s in data.symbols)),
                            content=data.content)
        session.add(row)
        session.flush()
    else:
        row.title, row.url, row.published_at = data.title, data.url, data.published_at
        row.summary = data.summary or row.summary
        row.content = data.content or row.content
        row.symbols = sorted(set((row.symbols or []) + [s.upper() for s in data.symbols]))
    return row


def _associated_symbols(session: Session, account_id: str) -> list[str]:
    watched = session.scalars(select(Instrument.symbol).join(WatchlistEntry)
        .where(WatchlistEntry.user_id == account_id, WatchlistEntry.instrument_id == Instrument.id)).all()
    owned = session.scalars(select(Instrument.symbol).join(Holding)
        .join(Account, Holding.account_id == Account.id)
        .where(Account.account_id == account_id, Holding.quantity > 0)).all()
    return sorted(set(watched) | set(owned))


def search_news(session: Session, provider: NewsProvider, account_id: str,
                request: NewsFeedRequest) -> NewsSearchResponse:
    symbols = request.symbols or []
    if request.scope == "personal":
        associated = set(_associated_symbols(session, account_id))
        symbols = sorted(associated.intersection(symbols)) if symbols else sorted(associated)
        if not symbols:
            return NewsSearchResponse(articles=[], scope=request.scope, next_page_token=None)
    try:
        page = provider.search_articles(query=request.query, symbols=symbols,
                                        page_token=request.page_token, page_size=request.page_size)
    except NewsProviderUnavailable as exc:
        raise NewsUnavailable from exc
    filtered = page.articles
    if request.scope == "personal":
        wanted = set(symbols)
        filtered = [item for item in page.articles if wanted.intersection(s.upper() for s in item.symbols)]
    rows_by_id = {}
    for item in filtered:
        row = _upsert_article(session, item)
        rows_by_id[row.article_id] = row
    session.commit()
    return NewsSearchResponse(articles=[_article_schema(row) for row in rows_by_id.values()],
                              scope=request.scope, next_page_token=page.next_page_token)


def get_article(session: Session, provider: NewsProvider, article_id: str) -> NewsArticle:
    row = session.scalar(select(ArticleRecord).where(ArticleRecord.article_id == article_id))
    if row is None:
        raise ArticleNotFound
    if row.content is None:
        try:
            fetched = provider.get_article(source=row.source, provider_article_id=row.provider_article_id)
        except NewsProviderUnavailable:
            fetched = None
        if fetched is not None and fetched.content:
            row.content = fetched.content
            row.summary = fetched.summary or row.summary
            session.commit()
    return _article_schema(row)


def summarize_article(session: Session, news_provider: NewsProvider, llm: LLMProvider,
                      article_id: str) -> SummaryResponse:
    article = get_article(session, news_provider, article_id)
    cached = session.scalar(select(ArticleSummaryRecord).where(ArticleSummaryRecord.article_id == article_id))
    if cached is not None:
        return SummaryResponse(article_id=article_id, summary=cached.summary,
            key_developments=cached.key_developments, reported_facts=cached.reported_facts,
            positive_implications=cached.positive_implications,
            negative_implications=cached.negative_implications,
            disclaimer="Reported facts are separated from AI-generated implications; verify against the source.",
            provider=cached.provider)
    text = article.content or article.summary
    if not text:
        raise ArticleContentUnavailable
    try:
        draft = llm.summarize_article(ArticleInput(article.title, article.source, article.summary, article.content))
    except LLMProviderUnavailable as exc:
        raise ResearchUnavailable from exc
    record = ArticleSummaryRecord(article_id=article_id, summary=draft.summary,
        key_developments=draft.key_developments, reported_facts=draft.reported_facts,
        positive_implications=draft.positive_implications,
        negative_implications=draft.negative_implications, provider=llm.provider_name)
    session.add(record)
    session.commit()
    return SummaryResponse(article_id=article_id, summary=draft.summary,
        key_developments=draft.key_developments, reported_facts=draft.reported_facts,
        positive_implications=draft.positive_implications,
        negative_implications=draft.negative_implications,
        disclaimer="Reported facts are separated from AI-generated implications; verify against the source.",
        provider=llm.provider_name)


def research_stock(session: Session, news_provider: NewsProvider, llm: LLMProvider,
                   market_provider: MarketDataProvider, request: ResearchRequest) -> ResearchResponse:
    symbol = request.symbol
    instrument = session.scalar(select(Instrument).where(Instrument.exchange == "NSE",
                                                          Instrument.symbol == symbol))
    if instrument is None:
        raise ResearchStockNotFound
    try:
        page = news_provider.search_articles(query=None, symbols=[symbol], page_token=None, page_size=10)
    except NewsProviderUnavailable as exc:
        raise NewsUnavailable from exc
    rows_by_id = {}
    for article in page.articles:
        row = _upsert_article(session, article)
        rows_by_id[row.article_id] = row
    session.commit()
    evidence_rows = sorted(rows_by_id.values(), key=lambda row: row.published_at, reverse=True)[:10]
    evidence = [ResearchEvidence(row.article_id, row.title, row.source,
                                 row.published_at.isoformat(), row.summary) for row in evidence_rows]
    quote = None
    try:
        quote = market_provider.get_quotes([instrument_data(instrument)]).get((instrument.exchange, instrument.symbol))
    except ProviderUnavailable:
        quote = None
    price = quote.price if quote is not None and quote.simulated else None
    try:
        draft = llm.research_stock(symbol=symbol, current_price=price, evidence=evidence)
    except LLMProviderUnavailable as exc:
        raise ResearchUnavailable from exc
    suggestion = ResearchSuggestion(symbol=symbol, thesis=draft.thesis, risks=draft.risks,
        evidence_article_ids=[item.article_id for item in evidence], generated_at=datetime.now(timezone.utc),
        reported_facts=draft.reported_facts, positive_implications=draft.positive_implications,
        negative_implications=draft.negative_implications, uncertainty=draft.uncertainty)
    return ResearchResponse(suggestions=[suggestion],
        disclaimer="Informational research only, not financial advice. AI interpretation is uncertain and should be independently verified.")


def instrument_data(instrument: Instrument) -> InstrumentData:
    return InstrumentData(instrument.exchange, instrument.symbol, instrument.name,
                          instrument.instrument_token, instrument.instrument_type)
