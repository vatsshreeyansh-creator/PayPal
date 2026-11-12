"""Deterministic, credential-free provider implementations for backend use/tests."""
from datetime import datetime, timezone
from decimal import Decimal
from news_provider import ArticleData, NewsPage
from llm_provider import (ArticleInput, ConversationMessage, ConversationReply, LLMProviderUnavailable,
                          ResearchDraft, ResearchEvidence, SummaryDraft, conversation_context_excerpt,
                          prepare_conversation)


class MockNewsProvider:
    _articles = (
        ArticleData("wire-001", "TCS announces expanded cloud partnership", "TradePoint Mock News",
                    "https://news.example.test/tcs-cloud", datetime(2026, 11, 7, 9, tzinfo=timezone.utc),
                    "TCS announced a cloud partnership expansion.", ["TCS"],
                    "TCS announced an expanded cloud partnership on Friday. The companies did not disclose financial terms."),
        ArticleData("wire-002", "Infosys updates annual outlook", "TradePoint Mock News",
                    "https://news.example.test/infy-outlook", datetime(2026, 11, 6, 12, tzinfo=timezone.utc),
                    "Infosys revised its outlook; the report contains no independent forecast.", ["INFY"], None),
        ArticleData("wire-003", "Indian equities close higher", "TradePoint Mock News",
                    "https://news.example.test/market-close", datetime(2026, 11, 5, 15, tzinfo=timezone.utc),
                    "Broad indices ended higher in the session.", [],
                    "Indian benchmark indices ended higher. This mock article contains no individual company disclosures."),
        ArticleData("wire-004", "Tata Motors reports production update", "TradePoint Mock News",
                    "https://news.example.test/tata-production?utm_source=sample", datetime(2026, 11, 4, 10, tzinfo=timezone.utc),
                    "The company shared a production update.", ["TATAMOTORS"], None),
    )

    def search_articles(self, *, query, symbols, page_token, page_size):
        matches = list(self._articles)
        if symbols:
            wanted = set(symbols)
            matches = [article for article in matches if wanted.intersection(article.symbols)]
        if query:
            q = query.casefold()
            matches = [article for article in matches if q in article.title.casefold()
                       or q in (article.summary or "").casefold()]
        start = int(page_token or "0")
        page = matches[start:start + page_size]
        next_token = str(start + page_size) if start + page_size < len(matches) else None
        return NewsPage(page, next_token)

    def get_article(self, *, source, provider_article_id):
        return next((a for a in self._articles if a.source == source and a.provider_article_id == provider_article_id), None)


class MockLLMProvider:
    provider_name = "mock-llm"

    def summarize_article(self, article: ArticleInput) -> SummaryDraft:
        text = article.content or article.summary or "Article body is unavailable."
        sentence = text.split(".")[0].strip().rstrip(".")
        fact = sentence + "." if sentence else "No article text was available."
        return SummaryDraft(
            summary=fact,
            key_developments=[fact],
            reported_facts=[fact],
            positive_implications=["Potential benefit is uncertain and requires independent verification."],
            negative_implications=["The article does not establish the size or durability of any impact."],
        )

    def converse(self, *, system_instructions: str, context: str,
                 messages: list[ConversationMessage]) -> ConversationReply:
        prepared = prepare_conversation(context, messages)
        latest = prepared.messages[-1].content
        prior = sum(message.role == "user" for message in prepared.messages) - 1
        first_sentence = conversation_context_excerpt(context, limit=300).split(".")[0].strip()
        return ConversationReply(
            f"Based on the supplied context ({first_sentence}), I cannot verify a specific answer to "
            f"“{latest}”. This reply includes {max(prior, 0)} earlier follow-up question(s); verify details against the source.",
            self.provider_name,
        )

    def research_stock(self, *, symbol, current_price: Decimal | None,
                       evidence: list[ResearchEvidence]) -> ResearchDraft:
        if not evidence:
            return ResearchDraft(
                thesis=f"Insufficient news evidence is available to form a view on {symbol}.", risks=["Evidence set is empty."],
                reported_facts=[], positive_implications=[], negative_implications=[],
                uncertainty="High: no relevant articles were available; this is not an investment recommendation.")
        facts = [item.summary for item in evidence if item.summary]
        return ResearchDraft(
            thesis=f"Available news for {symbol} is limited to the cited reports; no directional conclusion is established.",
            risks=["News coverage may be incomplete, delayed, or unrepresentative."],
            reported_facts=facts,
            positive_implications=["Any business impact described by these reports remains uncertain."],
            negative_implications=["The available reports may omit offsetting risks or context."],
            uncertainty="High: this summary uses only the listed news items and does not establish future performance.")
