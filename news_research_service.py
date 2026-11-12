"""News ingestion, deduplication, article retrieval, summaries and research orchestration."""
from datetime import datetime, timezone
import json
import logging
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from uuid import uuid4
from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload
from models import (Account, ArticleRecord, ArticleSummaryRecord, ConversationExchangeRecord,
                    ConversationMessageRecord, ConversationRecord, Holding,
                    Instrument, WatchlistEntry)
from news_provider import ArticleData, NewsPage, NewsProvider, NewsProviderUnavailable
from llm_provider import (ArticleInput, ConversationMessage, LLMProvider, LLMProviderUnavailable,
                          ResearchEvidence)
from provider import InstrumentData, MarketDataProvider
from schemas import (NewsArticle, NewsFeedRequest, NewsSearchResponse,
                    ResearchRequest, ResearchResponse, ResearchSuggestion,
                    SummaryResponse, ConversationCreateRequest, ConversationResponse,
                    ConversationTurn)

logger = logging.getLogger(__name__)


class ArticleNotFound(Exception): pass
class ArticleContentUnavailable(Exception): pass
class NewsUnavailable(Exception): pass
class ResearchUnavailable(Exception): pass
class ResearchStockNotFound(Exception): pass
class ConversationNotFound(Exception): pass
class ConversationMessageIdConflict(Exception): pass


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
    cached_provider_is_usable = cached is not None and (
        cached.provider == llm.provider_name or
        (llm.provider_name == "tradepoint-composite" and cached.provider not in {
            "mock-llm", "tradepoint-financial-nlp", "tradepoint-composite"})
    )
    if cached is not None and cached_provider_is_usable:
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
        logger.warning("Article summary provider %s is unavailable (%s)", llm.provider_name, type(exc).__name__)
        raise ResearchUnavailable from exc
    actual_provider = draft.provider or llm.provider_name
    if cached is None:
        record = ArticleSummaryRecord(article_id=article_id, summary=draft.summary,
            key_developments=draft.key_developments, reported_facts=draft.reported_facts,
            positive_implications=draft.positive_implications,
            negative_implications=draft.negative_implications, provider=actual_provider)
        session.add(record)
    else:
        cached.summary = draft.summary
        cached.key_developments = draft.key_developments
        cached.reported_facts = draft.reported_facts
        cached.positive_implications = draft.positive_implications
        cached.negative_implications = draft.negative_implications
        cached.provider = actual_provider
    session.commit()
    logger.info("Article summary generated by provider %s", actual_provider)
    return SummaryResponse(article_id=article_id, summary=draft.summary,
        key_developments=draft.key_developments, reported_facts=draft.reported_facts,
        positive_implications=draft.positive_implications,
        negative_implications=draft.negative_implications,
        disclaimer="Reported facts are separated from AI-generated implications; verify against the source.",
        provider=actual_provider)


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
        logger.warning("Stock research provider %s is unavailable (%s)", llm.provider_name, type(exc).__name__)
        raise ResearchUnavailable from exc
    actual_provider = draft.provider or llm.provider_name
    logger.info("Stock research generated by provider %s", actual_provider)
    suggestion = ResearchSuggestion(symbol=symbol, provider=actual_provider,
        thesis=draft.thesis, risks=draft.risks,
        evidence_article_ids=[item.article_id for item in evidence], generated_at=datetime.now(timezone.utc),
        reported_facts=draft.reported_facts, positive_implications=draft.positive_implications,
        negative_implications=draft.negative_implications, uncertainty=draft.uncertainty)
    return ResearchResponse(suggestions=[suggestion],
        disclaimer="Informational research only, not financial advice. AI interpretation is uncertain and should be independently verified.")


def instrument_data(instrument: Instrument) -> InstrumentData:
    return InstrumentData(instrument.exchange, instrument.symbol, instrument.name,
                          instrument.instrument_token, instrument.instrument_type)


def _conversation_response(row: ConversationRecord) -> ConversationResponse:
    return ConversationResponse(
        conversation_id=row.conversation_id, context_type=row.context_type,
        context_reference=row.context_reference, context_title=row.context_title,
        created_at=row.created_at,
        messages=[ConversationTurn(role=item.role, content=item.content, provider=item.provider,
                                   created_at=item.created_at) for item in row.messages],
    )


def create_conversation(session: Session, news_provider: NewsProvider, llm: LLMProvider,
                        market_provider: MarketDataProvider, account_id: str,
                        request: ConversationCreateRequest) -> ConversationResponse:
    account = session.scalar(select(Account).where(Account.account_id == account_id))
    if account is None:
        raise RuntimeError("Demo account is not initialized")
    if request.context_type == "article":
        article = get_article(session, news_provider, request.article_id or "")
        if not article.content and not article.summary:
            raise ArticleContentUnavailable
        context_reference = article.article_id
        context_title = article.title
        summary = session.scalar(select(ArticleSummaryRecord).where(
            ArticleSummaryRecord.article_id == article.article_id))
        snapshot = {
            "kind": "article", "article_id": article.article_id, "title": article.title,
            "source": article.source, "url": article.url, "summary": article.summary,
            "content": article.content,
            "ai_summary": summary.summary if summary else None,
            "reported_facts": summary.reported_facts if summary else [],
        }
    else:
        symbol = request.symbol or ""
        suggestion = request.research_context
        if suggestion is None or suggestion.symbol != symbol:
            raise ValueError("Research context does not match the requested symbol")
        context_reference = suggestion.symbol
        context_title = f"{suggestion.symbol} research"
        snapshot = {"kind": "research", "report": suggestion.model_dump(mode="json")}
    row = ConversationRecord(
        conversation_id=str(uuid4()), account_id=account.id,
        context_type=request.context_type, context_reference=context_reference,
        context_title=context_title, context_snapshot=json.dumps(snapshot, ensure_ascii=False),
    )
    session.add(row)
    session.commit()
    return _conversation_response(row)


def get_conversation(session: Session, account_id: str, conversation_id: str) -> ConversationResponse:
    row = session.scalar(select(ConversationRecord).join(Account).where(
        Account.account_id == account_id, ConversationRecord.conversation_id == conversation_id
    ).options(selectinload(ConversationRecord.messages)))
    if row is None:
        raise ConversationNotFound
    return _conversation_response(row)


def send_conversation_message(session: Session, llm: LLMProvider, account_id: str,
                              conversation_id: str, request_id: str, content: str) -> ConversationResponse:
    # Reserve SQLite's writer before reading history. This serializes concurrent
    # turns across threads and processes, so each provider call sees prior turns.
    if session.get_bind().dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))

    existing = session.get(ConversationExchangeRecord, request_id)
    if existing is not None:
        if existing.conversation_id != conversation_id or existing.user_content != content:
            session.rollback()
            raise ConversationMessageIdConflict
        session.rollback()
        return get_conversation(session, account_id, conversation_id)

    statement = select(ConversationRecord).join(Account).where(
        Account.account_id == account_id, ConversationRecord.conversation_id == conversation_id
    ).options(selectinload(ConversationRecord.messages))
    if session.get_bind().dialect.name != "sqlite":
        statement = statement.with_for_update()
    row = session.scalar(statement)
    if row is None:
        session.rollback()
        raise ConversationNotFound
    transcript = [ConversationMessage(role=item.role, content=item.content) for item in row.messages]
    user_turn = ConversationMessageRecord(conversation_id=row.conversation_id, role="user", content=content)
    row.messages.append(user_turn)
    transcript.append(ConversationMessage(role="user", content=content))
    try:
        reply = llm.converse(
            system_instructions=("You are TradePoint's cautious financial research assistant. Distinguish source facts "
                                 "from interpretation, do not invent facts, and state clearly when the supplied context "
                                 "does not support an answer. This is informational, not investment advice."),
            context=row.context_snapshot, messages=transcript,
        )
        logger.info("Conversation reply generated by provider %s", reply.provider)
        row.messages.append(ConversationMessageRecord(role="assistant", content=reply.content,
                                                      provider=reply.provider))
        session.flush()
        assistant_turn = row.messages[-1]
        session.add(ConversationExchangeRecord(
            request_id=request_id, conversation_id=row.conversation_id, user_content=content,
            user_message_id=user_turn.id, assistant_message_id=assistant_turn.id,
        ))
        session.commit()
    except LLMProviderUnavailable as exc:
        session.rollback()
        logger.warning("Conversation provider %s is unavailable (%s)", llm.provider_name, type(exc).__name__)
        raise
    except Exception:
        session.rollback()
        raise
    return get_conversation(session, account_id, conversation_id)
