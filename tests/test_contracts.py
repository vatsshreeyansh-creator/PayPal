import json
import os
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
DB_FILE.close()
os.environ["TRADEPOINT_DATABASE_URL"] = "sqlite:///" + DB_FILE.name.replace("\\", "/")

from app import create_app
from provider import MarketDataProvider, MockMarketDataProvider, QuoteData, InstrumentData
from news_provider import NewsProvider, NewsProviderUnavailable
from llm_provider import (ArticleInput, ConversationMessage, ConversationReply, LLMProvider,
                          HeuristicFinancialLLMProvider, ResearchDraft, SummaryDraft,
                          LLMProviderUnavailable)
from schemas import Quote, OrderRequest, OrderResponse, Transaction, ErrorResponse
from config import DEMO_USER_ID, INITIAL_CASH
from database import SessionLocal
from models import (Account, ArticleRecord, ArticleSummaryRecord, Base, CashLedgerEntry,
                    ConversationExchangeRecord, ConversationMessageRecord, ConversationRecord, Holding, Instrument,
                    Order, TransactionRecord)
from services import seed_instruments
from mock_research_providers import MockNewsProvider, MockLLMProvider
from news_provider import NewsPage
from sqlalchemy import select, create_engine, inspect, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from decimal import Decimal


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()

    def reset_trading_state(self, cash=INITIAL_CASH):
        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            session.query(TransactionRecord).delete()
            session.query(CashLedgerEntry).delete()
            session.query(Order).delete()
            session.query(Holding).delete()
            session.add(CashLedgerEntry(account_id=account.id, entry_key="OPENING_BALANCE",
                                        entry_type="INITIAL_CASH", amount=cash))
            session.commit()

    def submit(self, side, quantity, key):
        return self.client.post("/api/orders", json={"symbol": "TCS", "side": side,
            "quantity": quantity, "order_type": "MARKET", "idempotency_key": key})

    def test_provider_protocol_and_batch_shape(self):
        provider = MockMarketDataProvider()
        self.assertIsInstance(provider, MarketDataProvider)
        stocks = provider.search_stocks("Tata", 20)
        quotes = provider.get_quotes(stocks)
        self.assertEqual(set(quotes), {(x.exchange, x.symbol) for x in stocks})
        self.assertTrue(all(isinstance(q, QuoteData) and q.simulated for q in quotes.values()))

    def test_only_nse_equities_are_searchable_addable_and_seeded(self):
        candidates = [
            InstrumentData("NSE", "AUDITIDX", "Audit Index", 9001, "INDICES"),
            InstrumentData("BSE", "AUDITBSE", "Audit BSE Equity", 9002, "EQ"),
            InstrumentData("NSE", "AUDITGOOD", "Audit NSE Equity", 9003, "EQ"),
        ]

        class MixedInstrumentProvider(MockMarketDataProvider):
            def search_stocks(self, query, limit=20):
                return candidates[:limit]

        provider = MixedInstrumentProvider()
        client = create_app(provider).test_client()
        response = client.post("/api/stocks/search", json={"query": "Audit"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["symbol"] for row in response.get_json()["results"]], ["AUDITGOOD"])
        rejected = client.post("/api/watchlist", json={"symbol": "AUDITIDX"})
        self.assertEqual(rejected.status_code, 404)
        self.assertEqual(rejected.get_json()["error"]["code"], "STOCK_NOT_FOUND")
        with SessionLocal() as session:
            self.assertIsNone(session.scalar(select(Instrument).where(Instrument.symbol == "AUDITIDX")))
            self.assertIsNone(session.scalar(select(Instrument).where(Instrument.symbol == "AUDITBSE")))

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            seed_instruments(session, provider)
            self.assertEqual([row.symbol for row in session.scalars(select(Instrument)).all()], ["AUDITGOOD"])
        engine.dispose()

    def test_news_and_llm_provider_protocols_are_implementable(self):
        self.assertIsInstance(MockNewsProvider(), NewsProvider)
        self.assertIsInstance(MockLLMProvider(), LLMProvider)

    def test_existing_conversation_tables_gain_only_the_additive_exchange_table(self):
        engine = create_engine("sqlite:///:memory:")
        existing_tables = [table for table in Base.metadata.sorted_tables
                           if table.name != "ai_conversation_exchanges"]
        Base.metadata.create_all(engine, tables=existing_tables)
        before = {name: {column["name"] for column in inspect(engine).get_columns(name)}
                  for name in ("ai_conversations", "ai_conversation_messages")}

        Base.metadata.create_all(engine)
        after = {name: {column["name"] for column in inspect(engine).get_columns(name)}
                 for name in before}
        self.assertEqual(after, before)
        self.assertIn("ai_conversation_exchanges", inspect(engine).get_table_names())
        Base.metadata.create_all(engine)
        engine.dispose()

    def test_article_conversation_retains_context_and_full_turn_history(self):
        class EchoHistoryLLM(MockLLMProvider):
            def converse(self, *, system_instructions, context, messages):
                users = [message.content for message in messages if message.role == "user"]
                return ConversationReply(f"Context included: {'TCS' in context}. Earlier question: {users[-2] if len(users) > 1 else 'none'}", self.provider_name)

        client = create_app(news_provider=MockNewsProvider(), llm_provider=EchoHistoryLLM()).test_client()
        feed = client.get("/api/news?scope=market").get_json()
        article_id = feed["articles"][0]["article_id"] if isinstance(feed, list) else feed["articles"][0]["article_id"]
        created = client.post("/api/conversations", json={"context_type": "article", "article_id": article_id})
        self.assertEqual(created.status_code, 201, created.get_json())
        conversation_id = created.get_json()["conversation_id"]
        first = client.post(f"/api/conversations/{conversation_id}/messages", json={
            "request_id": "00000000-0000-4000-8000-000000000001", "content": "Why did margins decline?"})
        self.assertEqual(first.status_code, 200, first.get_json())
        second = client.post(f"/api/conversations/{conversation_id}/messages", json={
            "request_id": "00000000-0000-4000-8000-000000000002", "content": "Is that serious?"})
        self.assertEqual(second.status_code, 200, second.get_json())
        body = second.get_json()
        self.assertEqual([turn["role"] for turn in body["messages"]], ["user", "assistant", "user", "assistant"])
        self.assertIn("Why did margins decline?", body["messages"][-1]["content"])
        self.assertEqual(client.get(f"/api/conversations/{conversation_id}").get_json(), body)
        with SessionLocal() as session:
            record = session.scalar(select(ConversationRecord).where(ConversationRecord.conversation_id == conversation_id))
            self.assertIn(article_id, record.context_snapshot)
            self.assertEqual(session.query(ConversationMessageRecord).filter_by(conversation_id=conversation_id).count(), 4)

    def test_research_conversation_creation_pins_stock_report_context(self):
        client = create_app(news_provider=MockNewsProvider(), llm_provider=MockLLMProvider()).test_client()
        research_context = {"symbol": "TCS", "provider": "mock-llm",
            "thesis": "The cited news supports no directional conclusion.",
            "risks": ["Coverage is limited."], "evidence_article_ids": [],
            "generated_at": "2026-11-11T00:00:00Z", "reported_facts": [],
            "positive_implications": [], "negative_implications": [],
            "uncertainty": "High", "informational_only": True}
        response = client.post("/api/conversations", json={"context_type": "research", "symbol": "TCS",
            "article_id": None, "research_context": research_context})
        self.assertEqual(response.status_code, 201, response.get_json())
        body = response.get_json()
        self.assertEqual(body["context_type"], "research")
        self.assertEqual(body["context_reference"], "TCS")
        with SessionLocal() as session:
            record = session.scalar(select(ConversationRecord).where(ConversationRecord.conversation_id == body["conversation_id"]))
            self.assertIn('"report"', record.context_snapshot)
            self.assertIn(research_context["thesis"], record.context_snapshot)

    def test_failed_conversation_generation_does_not_persist_orphan_user_turn(self):
        class FailingConversationLLM(MockLLMProvider):
            fail = True

            def converse(self, **kwargs):
                if self.fail:
                    raise LLMProviderUnavailable("offline")
                return ConversationReply("Recovered response.", self.provider_name)

        llm = FailingConversationLLM()
        client = create_app(news_provider=MockNewsProvider(), llm_provider=llm).test_client()
        feed = client.get("/api/news?scope=market").get_json()
        article_id = feed["articles"][0]["article_id"]
        created = client.post("/api/conversations", json={"context_type": "article", "article_id": article_id,
            "symbol": None, "research_context": None})
        conversation_id = created.get_json()["conversation_id"]
        message = {"request_id": "00000000-0000-4000-8000-000000000003", "content": "Follow up?"}
        response = client.post(f"/api/conversations/{conversation_id}/messages", json=message)
        self.assertEqual(response.status_code, 503)
        history = client.get(f"/api/conversations/{conversation_id}").get_json()
        self.assertEqual(history["messages"], [])
        llm.fail = False
        retry = client.post(f"/api/conversations/{conversation_id}/messages", json=message)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual([turn["role"] for turn in retry.get_json()["messages"]], ["user", "assistant"])

    def test_conversation_message_request_id_replay_and_conflicts(self):
        class CountingLLM(MockLLMProvider):
            calls = 0

            def converse(self, **kwargs):
                self.calls += 1
                return super().converse(**kwargs)

        llm = CountingLLM()
        client = create_app(news_provider=MockNewsProvider(), llm_provider=llm).test_client()
        feed = client.get("/api/news?scope=market").get_json()
        article_id = feed["articles"][0]["article_id"]
        conversation_id = client.post("/api/conversations", json={
            "context_type": "article", "article_id": article_id}).get_json()["conversation_id"]
        second_conversation_id = client.post("/api/conversations", json={
            "context_type": "article", "article_id": article_id}).get_json()["conversation_id"]
        message = {"request_id": "00000000-0000-4000-8000-000000000004", "content": "What changed?"}

        first = client.post(f"/api/conversations/{conversation_id}/messages", json=message)
        self.assertEqual(first.status_code, 200)
        replay = client.post(f"/api/conversations/{conversation_id}/messages", json=message)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.get_json(), first.get_json())
        self.assertEqual(llm.calls, 1)
        with SessionLocal() as session:
            self.assertEqual(session.query(ConversationMessageRecord).filter_by(conversation_id=conversation_id).count(), 2)
            self.assertEqual(session.query(ConversationExchangeRecord).filter_by(request_id=message["request_id"]).count(), 1)

        reused_content = client.post(f"/api/conversations/{conversation_id}/messages", json={
            **message, "content": "A different question"})
        reused_conversation = client.post(f"/api/conversations/{second_conversation_id}/messages", json=message)
        for conflict in (reused_content, reused_conversation):
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(conflict.get_json()["error"]["code"], "MESSAGE_IDEMPOTENCY_CONFLICT")

    def test_concurrent_messages_are_serialized_against_latest_history(self):
        from threading import Event, Lock, get_ident
        from concurrent.futures import ThreadPoolExecutor

        entered_provider = Event()
        release_provider = Event()
        second_request_thread_ready = Event()
        second_begin_attempted = Event()
        calls_lock = Lock()
        provider_transcripts = []
        second_thread_id = None

        class SlowHistoryLLM(MockLLMProvider):
            def converse(self, *, system_instructions, context, messages):
                with calls_lock:
                    provider_transcripts.append(list(messages))
                    call_number = len(provider_transcripts)
                if call_number == 1:
                    entered_provider.set()
                    if not release_provider.wait(5):
                        raise RuntimeError("test synchronization timed out")
                return ConversationReply(f"Answer to {messages[-1].content}", self.provider_name)

        app = create_app(news_provider=MockNewsProvider(), llm_provider=SlowHistoryLLM())
        client = app.test_client()
        feed = client.get("/api/news?scope=market").get_json()
        article_id = feed["articles"][0]["article_id"]
        conversation_id = client.post("/api/conversations", json={
            "context_type": "article", "article_id": article_id}).get_json()["conversation_id"]
        payloads = [
            {"request_id": "00000000-0000-4000-8000-000000000005", "content": "Question one?"},
            {"request_id": "00000000-0000-4000-8000-000000000006", "content": "Question two?"},
        ]

        with SessionLocal() as session:
            engine = session.get_bind()

        def observe_second_begin(_connection, _cursor, statement, _parameters, _context, _many):
            if (statement.strip().upper() == "BEGIN IMMEDIATE"
                    and get_ident() == second_thread_id):
                second_begin_attempted.set()

        event.listen(engine, "before_cursor_execute", observe_second_begin)

        def post(index):
            if index == 1:
                nonlocal second_thread_id
                second_thread_id = get_ident()
                second_request_thread_ready.set()
            with app.test_client() as request_client:
                return request_client.post(f"/api/conversations/{conversation_id}/messages", json=payloads[index])

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first_future = pool.submit(post, 0)
                self.assertTrue(entered_provider.wait(3), "first request did not reach its provider")
                second_future = pool.submit(post, 1)
                self.assertTrue(second_request_thread_ready.wait(3), "second request thread did not start")
                self.assertTrue(second_begin_attempted.wait(3), "second request did not attempt BEGIN IMMEDIATE")

                # The provider is still blocked, so the first request must still own
                # SQLite's reservation. A zero-timeout independent writer probes that
                # the database is genuinely contended before we release the provider.
                with engine.connect() as probe:
                    probe.exec_driver_sql("PRAGMA busy_timeout=0")
                    with self.assertRaises(OperationalError):
                        probe.exec_driver_sql("BEGIN IMMEDIATE")

                release_provider.set()
                first_response = first_future.result(timeout=10)
                second_response = second_future.result(timeout=10)
        finally:
            release_provider.set()
            event.remove(engine, "before_cursor_execute", observe_second_begin)

        self.assertEqual(first_response.status_code, 200, first_response.get_json())
        self.assertEqual(second_response.status_code, 200, second_response.get_json())
        self.assertEqual(len(provider_transcripts), 2)
        self.assertEqual([turn.content for turn in provider_transcripts[1]], [
            "Question one?", "Answer to Question one?", "Question two?",
        ])
        final_turns = second_response.get_json()["messages"]
        self.assertEqual([turn["content"] for turn in final_turns], [
            "Question one?", "Answer to Question one?", "Question two?", "Answer to Question two?",
        ])

        with SessionLocal() as session:
            self.assertEqual(session.query(ConversationMessageRecord).filter_by(
                conversation_id=conversation_id).count(), 4)
            self.assertEqual(session.query(ConversationExchangeRecord).filter_by(
                conversation_id=conversation_id).count(), 2)

    def test_concurrent_same_conversation_request_id_is_processed_once(self):
        from threading import Event, Lock, get_ident
        from concurrent.futures import ThreadPoolExecutor

        entered_provider = Event()
        release_provider = Event()
        second_request_thread_ready = Event()
        second_begin_attempted = Event()
        calls_lock = Lock()
        second_thread_id = None

        class CountingSlowLLM(MockLLMProvider):
            calls = 0

            def converse(self, *, system_instructions, context, messages):
                with calls_lock:
                    self.calls += 1
                entered_provider.set()
                if not release_provider.wait(5):
                    raise RuntimeError("test synchronization timed out")
                return ConversationReply("Only one generated answer.", self.provider_name)

        llm = CountingSlowLLM()
        app = create_app(news_provider=MockNewsProvider(), llm_provider=llm)
        client = app.test_client()
        article_id = client.get("/api/news?scope=market").get_json()["articles"][0]["article_id"]
        conversation_id = client.post("/api/conversations", json={
            "context_type": "article", "article_id": article_id}).get_json()["conversation_id"]
        payload = {"request_id": "00000000-0000-4000-8000-000000000007", "content": "Same question?"}

        with SessionLocal() as session:
            engine = session.get_bind()

        def observe_second_begin(_connection, _cursor, statement, _parameters, _context, _many):
            if (statement.strip().upper() == "BEGIN IMMEDIATE"
                    and get_ident() == second_thread_id):
                second_begin_attempted.set()

        event.listen(engine, "before_cursor_execute", observe_second_begin)

        def post(is_second):
            if is_second:
                nonlocal second_thread_id
                second_thread_id = get_ident()
                second_request_thread_ready.set()
            with app.test_client() as request_client:
                return request_client.post(f"/api/conversations/{conversation_id}/messages", json=payload)

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first_future = pool.submit(post, False)
                self.assertTrue(entered_provider.wait(3), "first request did not reach its provider")
                second_future = pool.submit(post, True)
                self.assertTrue(second_request_thread_ready.wait(3), "second request thread did not start")
                self.assertTrue(second_begin_attempted.wait(3), "second request did not attempt BEGIN IMMEDIATE")

                with engine.connect() as probe:
                    probe.exec_driver_sql("PRAGMA busy_timeout=0")
                    with self.assertRaises(OperationalError):
                        probe.exec_driver_sql("BEGIN IMMEDIATE")

                release_provider.set()
                responses = [first_future.result(timeout=10), second_future.result(timeout=10)]
        finally:
            release_provider.set()
            event.remove(engine, "before_cursor_execute", observe_second_begin)

        self.assertEqual([response.status_code for response in responses], [200, 200])
        self.assertEqual(llm.calls, 1)
        self.assertEqual(responses[0].get_json(), responses[1].get_json())
        messages = responses[0].get_json()["messages"]
        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])
        self.assertEqual([message["content"] for message in messages], [
            "Same question?", "Only one generated answer.",
        ])
        with SessionLocal() as session:
            self.assertEqual(session.query(ConversationExchangeRecord).filter_by(
                request_id=payload["request_id"]).count(), 1)
            self.assertEqual(session.query(ConversationMessageRecord).filter_by(
                conversation_id=conversation_id).count(), 2)

    def test_conversation_validation_and_unknown_ids_use_standard_errors(self):
        invalid = self.client.post("/api/conversations", json={"context_type": "article", "symbol": "TCS"})
        self.assertEqual(invalid.status_code, 400)
        missing = self.client.get("/api/conversations/no-such-conversation")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.get_json()["error"]["code"], "CONVERSATION_NOT_FOUND")
        valid_id = self.client.get("/api/news?scope=market").get_json()["articles"][0]["article_id"]
        conversation_id = self.client.post("/api/conversations", json={
            "context_type": "article", "article_id": valid_id}).get_json()["conversation_id"]
        missing_request_id = self.client.post(f"/api/conversations/{conversation_id}/messages", json={"content": "Question"})
        self.assertEqual(missing_request_id.status_code, 400)
        self.assertEqual(missing_request_id.get_json()["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(missing_request_id.get_json()["error"]["field"], "request_id")

        invalid_request_id = self.client.post(f"/api/conversations/{conversation_id}/messages", json={
            "request_id": "not-a-uuid", "content": "Question"})
        self.assertEqual(invalid_request_id.status_code, 400)
        self.assertEqual(invalid_request_id.get_json()["error"]["field"], "request_id")

        invalid_content = self.client.post(f"/api/conversations/{conversation_id}/messages", json={
            "request_id": "00000000-0000-4000-8000-000000000008", "content": ""})
        self.assertEqual(invalid_content.status_code, 400)
        self.assertEqual(invalid_content.get_json()["error"]["field"], "content")

        missing_content = self.client.post(f"/api/conversations/{conversation_id}/messages", json={
            "request_id": "00000000-0000-4000-8000-000000000009"})
        self.assertEqual(missing_content.status_code, 400)
        self.assertEqual(missing_content.get_json()["error"]["field"], "content")

    def test_money_and_order_models_reject_incompatible_representations(self):
        Quote(price="123.40", as_of=datetime.now(timezone.utc), simulated=True)
        for value in (123.4, "123.4", "0.00", "-1.00"):
            with self.assertRaises(Exception):
                Quote(price=value, as_of=datetime.now(timezone.utc), simulated=True)
        OrderRequest(symbol="TCS", side="BUY", quantity=2, idempotency_key="req-1")
        with self.assertRaises(Exception):
            OrderRequest(symbol="TCS", side="HOLD", quantity=2, idempotency_key="req-1")
        with self.assertRaises(Exception):
            OrderRequest(symbol="TCS", side="BUY", quantity=1.5, idempotency_key="req-2")
        self.assertIn("gross_amount", Transaction.model_fields)
        with self.assertRaises(Exception):
            Transaction(transaction_id="t", order_id="o", symbol="TCS", side="BUY", quantity="2.5",
                        price="1.00", gross_amount="1.00", currency="INR", occurred_at=datetime.now(timezone.utc))
        self.assertEqual(set(ErrorResponse.model_fields), {"error"})

    def test_watchlist_api_wire_shapes(self):
        response = self.client.post("/api/stocks/search", json={"query": "Tata", "limit": 20})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(set(body), {"results"})
        self.assertEqual(set(body["results"][0]), {"symbol", "name", "exchange", "instrument_token"})
        response = self.client.post("/api/watchlist", json={"symbol": "TCS"})
        self.assertIn(response.status_code, (200, 201))
        item = response.get_json()["item"]
        self.assertEqual(set(item), {"stock", "quote"})
        self.assertEqual(set(item["quote"]), {"price", "currency", "as_of", "simulated"})
        self.assertIsInstance(item["quote"]["price"], str)
        self.assertRegex(item["quote"]["price"], r"^\d+\.\d{2}$")
        self.assertTrue(item["quote"]["as_of"].endswith("Z"))
        listed = self.client.get("/api/watchlist").get_json()
        self.assertEqual(set(listed), {"items"})

    def test_account_retrieval_and_configured_initial_cash_persistence(self):
        response = self.client.get("/api/account")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"account_id": DEMO_USER_ID, "currency": "INR",
                                               "cash_balance": f"{INITIAL_CASH:.2f}"})
        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            self.assertIsNotNone(account)
            self.assertEqual(account.initial_cash, INITIAL_CASH)

    def test_empty_portfolio(self):
        response = self.client.get("/api/portfolio")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["holdings"], [])
        self.assertEqual(data["total_portfolio_value"], f"{INITIAL_CASH:.2f}")

    def test_multiple_holdings_valuation_and_persistence(self):
        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            session.query(Holding).delete()
            instruments = {x.symbol: x for x in session.scalars(select(Instrument).where(Instrument.symbol.in_(["TCS", "INFY"]))).all()}
            session.add_all([
                Holding(account_id=account.id, instrument_id=instruments["TCS"].id, quantity=2,
                        average_purchase_price=Decimal("3800.00"), realized_pnl=Decimal("0.00")),
                Holding(account_id=account.id, instrument_id=instruments["INFY"].id, quantity=3,
                        average_purchase_price=Decimal("1500.00"), realized_pnl=Decimal("25.00")),
            ])
            session.commit()
        data = self.client.get("/api/portfolio").get_json()
        self.assertEqual([x["symbol"] for x in data["holdings"]], ["INFY", "TCS"])
        by_symbol = {x["symbol"]: x for x in data["holdings"]}
        self.assertEqual(by_symbol["TCS"]["market_value"], "7730.50")
        self.assertEqual(by_symbol["INFY"]["market_value"], "4538.25")
        self.assertEqual(data["total_portfolio_value"], f"{INITIAL_CASH + Decimal('12268.75'):.2f}")
        with SessionLocal() as session:
            self.assertEqual(session.scalar(select(Holding).where(Holding.quantity == 2)).quantity, 2)

    def test_missing_quotes_keep_positions_and_null_total_valuation(self):
        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            session.query(Holding).delete()
            instruments = {x.symbol: x for x in session.scalars(select(Instrument).where(Instrument.symbol.in_(["TCS", "INFY"]))).all()}
            session.add_all([Holding(account_id=account.id, instrument_id=instruments[symbol].id, quantity=1,
                                     average_purchase_price=Decimal("100.00"), realized_pnl=Decimal("0.00"))
                             for symbol in ("TCS", "INFY")])
            session.commit()
        class MissingQuoteProvider(MockMarketDataProvider):
            def get_quotes(self, instruments):
                data = super().get_quotes(instruments)
                data.pop(("NSE", "TCS"), None)
                return data
        response = create_app(MissingQuoteProvider()).test_client().get("/api/portfolio")
        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        tcs = next(item for item in data["holdings"] if item["symbol"] == "TCS")
        self.assertIsNone(tcs["current_price"])
        self.assertIsNone(tcs["market_value"])
        self.assertIsNone(tcs["unrealized_pnl"])
        self.assertIsNone(data["total_portfolio_value"])
        self.assertEqual(len(data["holdings"]), 2)

    def test_provider_outage_keeps_portfolio_response(self):
        from provider import ProviderUnavailable
        with SessionLocal() as session:
            account = session.scalar(select(Account).where(Account.account_id == DEMO_USER_ID))
            session.query(Holding).delete()
            instruments = {x.symbol: x for x in session.scalars(select(Instrument).where(Instrument.symbol.in_(["TCS", "INFY"]))).all()}
            session.add_all([Holding(account_id=account.id, instrument_id=instruments[symbol].id, quantity=1,
                                     average_purchase_price=Decimal("100.00"), realized_pnl=Decimal("0.00"))
                             for symbol in ("TCS", "INFY")])
            session.commit()
        class UnavailableProvider(MockMarketDataProvider):
            def get_quotes(self, instruments):
                raise ProviderUnavailable()
        response = create_app(UnavailableProvider()).test_client().get("/api/portfolio")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()["holdings"]), 2)
        self.assertIsNone(response.get_json()["total_portfolio_value"])

    def test_watchlist_regression_after_account_tables(self):
        response = self.client.post("/api/watchlist", json={"symbol": "TCS"})
        self.assertIn(response.status_code, (200, 201))
        self.assertTrue(any(x["stock"]["symbol"] == "TCS" for x in self.client.get("/api/watchlist").get_json()["items"]))

    def test_buy_additional_partial_and_full_sell(self):
        self.reset_trading_state()
        buy = self.submit("BUY", 2, "trade-flow-1")
        self.assertEqual(buy.status_code, 201)
        self.assertEqual(buy.get_json()["status"], "FILLED")
        self.assertEqual(self.client.get("/api/account").get_json()["cash_balance"], "992269.50")
        self.assertEqual(self.client.get("/api/portfolio").get_json()["holdings"][0]["quantity"], "2")
        self.assertEqual(self.submit("BUY", 1, "trade-flow-2").status_code, 201)
        data = self.client.get("/api/portfolio").get_json()
        self.assertEqual(data["holdings"][0]["quantity"], "3")
        self.assertEqual(data["holdings"][0]["average_purchase_price"], "3865.25")
        self.assertEqual(self.submit("SELL", 1, "trade-flow-3").status_code, 201)
        self.assertEqual(self.client.get("/api/portfolio").get_json()["holdings"][0]["quantity"], "2")
        self.assertEqual(self.submit("SELL", 2, "trade-flow-4").status_code, 201)
        self.assertEqual(self.client.get("/api/portfolio").get_json()["holdings"], [])
        self.assertEqual(self.client.get("/api/account").get_json()["cash_balance"], "1000000.00")
        self.assertEqual(len(self.client.get("/api/transactions").get_json()), 4)
        self.assertEqual(len(self.client.get("/api/orders").get_json()), 4)

    def test_simulated_order_can_use_live_market_quote_without_broker_execution(self):
        self.reset_trading_state()

        class LiveQuoteProvider(MockMarketDataProvider):
            def get_quotes(self, instruments):
                now = datetime.now(timezone.utc)
                return {(item.exchange, item.symbol): QuoteData(Decimal("123.45"), now, False)
                        for item in instruments}

        client = create_app(LiveQuoteProvider()).test_client()
        response = client.post("/api/orders", json={"symbol": "TCS", "side": "BUY", "quantity": 2,
            "order_type": "MARKET", "idempotency_key": "live-quote-paper-order"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["status"], "FILLED")
        self.assertEqual(response.get_json()["execution_price"], "123.45")
        transactions = client.get("/api/transactions").get_json()
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]["price"], "123.45")
        self.assertEqual(client.get("/api/account").get_json()["cash_balance"],
                         f"{INITIAL_CASH - Decimal('246.90'):.2f}")

    def test_idempotency_replay_and_conflict_do_not_double_apply(self):
        self.reset_trading_state()
        first = self.submit("BUY", 2, "same-key")
        replay = self.submit("BUY", 2, "same-key")
        conflict = self.submit("BUY", 3, "same-key")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.get_json()["order_id"], first.get_json()["order_id"])
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(self.client.get("/api/account").get_json()["cash_balance"], "992269.50")
        self.assertEqual(len(self.client.get("/api/transactions").get_json()), 1)

    def test_weighted_average_cost_with_different_execution_prices(self):
        self.reset_trading_state()
        class SteppedProvider(MockMarketDataProvider):
            calls = 0
            def get_quotes(self, instruments):
                self.calls += 1
                price = Decimal("10.00") if self.calls == 1 else Decimal("20.00")
                return {(i.exchange, i.symbol): QuoteData(price, datetime.now(timezone.utc), True) for i in instruments}
        client = create_app(SteppedProvider()).test_client()
        for quantity, key in ((2, "weighted-a"), (1, "weighted-b")):
            self.assertEqual(client.post("/api/orders", json={"symbol": "TCS", "side": "BUY", "quantity": quantity,
                "idempotency_key": key}).status_code, 201)
        holding = client.get("/api/portfolio").get_json()["holdings"][0]
        self.assertEqual(holding["average_purchase_price"], "13.33")

    def test_realized_profit_after_sale_uses_weighted_cost_basis(self):
        self.reset_trading_state()
        class ChangingProvider(MockMarketDataProvider):
            calls = 0
            def get_quotes(self, instruments):
                self.calls += 1
                price = Decimal("10.00") if self.calls == 1 else Decimal("15.00")
                return {(i.exchange, i.symbol): QuoteData(price, datetime.now(timezone.utc), True) for i in instruments}
        client = create_app(ChangingProvider()).test_client()
        self.assertEqual(client.post("/api/orders", json={"symbol":"TCS","side":"BUY","quantity":2,"idempotency_key":"pnl-buy"}).status_code, 201)
        self.assertEqual(client.post("/api/orders", json={"symbol":"TCS","side":"SELL","quantity":1,"idempotency_key":"pnl-sell"}).status_code, 201)
        holding = client.get("/api/portfolio").get_json()["holdings"][0]
        self.assertEqual(holding["realized_pnl"], "5.00")
        self.assertEqual(holding["quantity"], "1")

    def test_concurrent_idempotent_requests_execute_only_once(self):
        self.reset_trading_state()
        def submit_once(_):
            with create_app().test_client() as client:
                response = client.post("/api/orders", json={"symbol": "TCS", "side": "BUY", "quantity": 2,
                    "idempotency_key": "concurrent-key"})
                return response.status_code, response.get_json()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit_once, range(2)))
        self.assertEqual(sorted(status for status, _ in results), [200, 201])
        self.assertEqual(len(self.client.get("/api/transactions").get_json()), 1)
        self.assertEqual(self.client.get("/api/portfolio").get_json()["holdings"][0]["quantity"], "2")

    def test_business_rejections_and_invalid_requests(self):
        self.reset_trading_state(Decimal("10.00"))
        cash = self.submit("BUY", 1, "poor")
        self.assertEqual(cash.status_code, 201)
        self.assertEqual(cash.get_json()["rejection_reason"], "INSUFFICIENT_CASH")
        shares = self.submit("SELL", 1, "none-owned")
        self.assertEqual(shares.get_json()["rejection_reason"], "INSUFFICIENT_SHARES")
        unknown = self.client.post("/api/orders", json={"symbol": "ZZZZ", "side": "BUY", "quantity": 1,
            "order_type": "MARKET", "idempotency_key": "unknown"})
        self.assertEqual(unknown.status_code, 404)
        invalid = self.client.post("/api/orders", json={"symbol": "TCS", "side": "BUY", "quantity": 0,
            "idempotency_key": "bad"})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(len(self.client.get("/api/transactions").get_json()), 0)

    def test_missing_quote_is_recorded_as_rejected_order(self):
        self.reset_trading_state()
        class MissingProvider(MockMarketDataProvider):
            def get_quotes(self, instruments): return {}
        response = create_app(MissingProvider()).test_client().post("/api/orders", json={
            "symbol": "TCS", "side": "BUY", "quantity": 1, "idempotency_key": "no-quote"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["rejection_reason"], "QUOTE_UNAVAILABLE")
        self.assertEqual(self.client.get("/api/account").get_json()["cash_balance"], f"{INITIAL_CASH:.2f}")
        self.assertEqual(self.client.get("/api/transactions").get_json(), [])

    def test_database_failure_rolls_back_order_cash_holding_and_transaction(self):
        from sqlalchemy import event
        self.reset_trading_state()
        def fail_commit(session):
            raise RuntimeError("injected commit failure")
        event.listen(SessionLocal.class_, "before_commit", fail_commit)
        try:
            response = self.submit("BUY", 1, "rollback")
        finally:
            event.remove(SessionLocal.class_, "before_commit", fail_commit)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.client.get("/api/account").get_json()["cash_balance"], f"{INITIAL_CASH:.2f}")
        self.assertEqual(self.client.get("/api/transactions").get_json(), [])
        self.assertEqual(self.client.get("/api/orders").get_json(), [])
        self.assertEqual(self.client.get("/api/portfolio").get_json()["holdings"], [])

    def test_errors_have_common_shape(self):
        for response in (self.client.get("/missing"), self.client.post("/api/stocks/search", json={"query": " "}),
                         self.client.post("/api/watchlist", json={"symbol": "NOTREAL"})):
            self.assertEqual(set(response.get_json()), {"error"})
            self.assertEqual(set(response.get_json()["error"]), {"code", "message", "field"})

    def test_openapi_document_contract_artifact(self):
        path = os.path.join(os.path.dirname(__file__), "..", "openapi.json")
        with open(path, encoding="utf-8") as f:
            spec = json.load(f)
        self.assertEqual(spec["openapi"], "3.1.0")
        self.assertIn("/api/stocks/search", spec["paths"])
        self.assertIn("OrderRequest", spec["components"]["schemas"])
        quote = spec["components"]["schemas"]["Quote"]
        self.assertEqual(quote["properties"]["price"]["type"], "string")
        for operations in spec["paths"].values():
            for operation in operations.values():
                if "responses" in operation:
                    self.assertIn("405", operation["responses"])
                    self.assertIn("500", operation["responses"])
        self.assertIn("503", spec["paths"]["/api/watchlist"]["post"]["responses"])
        self.assertIn("422", spec["paths"]["/api/news/{article_id}/summary"]["post"]["responses"])
        for path in ("/api/news", "/api/news/{article_id}", "/api/news/{article_id}/summary", "/api/research/suggestions"):
            self.assertTrue(spec["paths"][path])

    def reset_news_state(self):
        with SessionLocal() as session:
            session.query(ArticleSummaryRecord).delete()
            session.query(ArticleRecord).delete()
            session.commit()

    def test_market_news_pagination_persistence_and_canonical_deduplication(self):
        self.reset_news_state()
        first = self.client.get("/api/news?scope=market&page_size=2").get_json()
        self.assertEqual(first["scope"], "market")
        self.assertEqual(len(first["articles"]), 2)
        self.assertIsNotNone(first["next_page_token"])
        second = self.client.get("/api/news?scope=market&page_size=2&page_token=" + first["next_page_token"]).get_json()
        self.assertEqual(len(second["articles"]), 2)
        with SessionLocal() as session:
            self.assertEqual(session.query(ArticleRecord).count(), 4)
        article_id = second["articles"][-1]["article_id"]
        article = self.client.get("/api/news/" + article_id).get_json()
        self.assertIsNone(article["content"])

        class DuplicateNewsProvider(MockNewsProvider):
            def search_articles(self, **kwargs):
                page = super().search_articles(**kwargs)
                if page.articles:
                    return NewsPage([page.articles[0], page.articles[0]], None)
                return page
        self.reset_news_state()
        duplicate_client = create_app(news_provider=DuplicateNewsProvider()).test_client()
        result = duplicate_client.get("/api/news?scope=market&page_size=3").get_json()
        self.assertEqual(len(result["articles"]), 1)
        with SessionLocal() as session:
            self.assertEqual(session.query(ArticleRecord).count(), 1)

    def test_personal_feed_includes_watched_stock_and_summary_separates_facts_from_implications(self):
        self.reset_news_state()
        with SessionLocal() as session:
            session.query(Holding).delete()
            session.commit()
        self.client.post("/api/watchlist", json={"symbol": "TCS"})
        feed = self.client.get("/api/news?scope=personal").get_json()
        self.assertTrue(feed["articles"])
        self.assertTrue(all("TCS" in article["symbols"] for article in feed["articles"]))
        article_id = feed["articles"][0]["article_id"]
        response = self.client.post(f"/api/news/{article_id}/summary")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["provider"], "mock-llm")
        self.assertTrue(data["reported_facts"])
        self.assertTrue(data["positive_implications"])
        self.assertTrue(data["negative_implications"])
        self.assertIn("AI-generated", data["disclaimer"])
        self.assertEqual(self.client.post(f"/api/news/{article_id}/summary").get_json(), data)

    def test_research_cites_ingested_articles_and_reports_uncertainty(self):
        self.reset_news_state()
        response = self.client.post("/api/research/suggestions", json={"symbol": "TCS"})
        self.assertEqual(response.status_code, 200)
        suggestion = response.get_json()["suggestions"][0]
        self.assertEqual(suggestion["symbol"], "TCS")
        self.assertEqual(suggestion["provider"], "mock-llm")
        self.assertTrue(suggestion["evidence_article_ids"])
        self.assertTrue(suggestion["uncertainty"])
        self.assertTrue(response.get_json()["disclaimer"])

    def test_summary_research_and_conversation_share_provider_and_report_actual_name(self):
        class NamedLLM:
            provider_name = "integration-genuine-test"

            def summarize_article(self, article: ArticleInput) -> SummaryDraft:
                return SummaryDraft("Summary", ["Development"], ["Fact"], ["Upside"], ["Risk"])

            def research_stock(self, *, symbol, current_price, evidence) -> ResearchDraft:
                return ResearchDraft("Thesis", ["Risk"], ["Fact"], ["Upside"], ["Downside"], "Limited evidence")

            def converse(self, *, system_instructions, context, messages) -> ConversationReply:
                return ConversationReply("The report supports that interpretation with uncertainty.", self.provider_name)

        llm = NamedLLM()
        client = create_app(provider=MockMarketDataProvider(), news_provider=MockNewsProvider(),
                            llm_provider=llm).test_client()
        article_id = client.get("/api/news?scope=market").get_json()["articles"][0]["article_id"]
        summary = client.post(f"/api/news/{article_id}/summary")
        research = client.post("/api/research/suggestions", json={"symbol": "TCS"})
        conversation = client.post("/api/conversations", json={
            "context_type": "article", "article_id": article_id}).get_json()
        turn = client.post(f"/api/conversations/{conversation['conversation_id']}/messages", json={
            "request_id": "00000000-0000-4000-8000-000000000101", "content": "Explain the risk."})

        self.assertEqual(summary.status_code, 200, summary.get_json())
        self.assertEqual(research.status_code, 200, research.get_json())
        self.assertEqual(summary.get_json()["provider"], llm.provider_name)
        self.assertEqual(research.get_json()["suggestions"][0]["provider"], llm.provider_name)
        self.assertEqual(turn.status_code, 200, turn.get_json())
        self.assertEqual(turn.get_json()["messages"][-1]["provider"], llm.provider_name)

    def test_summary_cache_is_replaced_when_it_came_from_a_different_provider(self):
        self.reset_news_state()
        news_provider = MockNewsProvider()
        first_client = create_app(news_provider=news_provider, llm_provider=MockLLMProvider()).test_client()
        article_id = first_client.get("/api/news?scope=market").get_json()["articles"][0]["article_id"]
        first = first_client.post(f"/api/news/{article_id}/summary")
        self.assertEqual(first.get_json()["provider"], "mock-llm")

        class NamedLLM(MockLLMProvider):
            provider_name = "groq/openai/gpt-oss-20b"

            def summarize_article(self, article):
                return SummaryDraft("Fresh genuine-provider summary", [], ["Fresh fact"], [], [])

        second_client = create_app(news_provider=news_provider, llm_provider=NamedLLM()).test_client()
        second = second_client.post(f"/api/news/{article_id}/summary")
        self.assertEqual(second.status_code, 200, second.get_json())
        self.assertEqual(second.get_json()["provider"], "groq/openai/gpt-oss-20b")
        self.assertEqual(second.get_json()["summary"], "Fresh genuine-provider summary")

    def test_offline_conversation_providers_do_not_echo_internal_article_metadata(self):
        context = json.dumps({"kind": "article", "article_id": "internal-article-id",
            "title": "TCS reports margin pressure", "source": "Private source label",
            "url": "https://example.test/internal", "content": "Operating margins fell as integration costs increased."})
        messages = [ConversationMessage("user", "Why did margins fall?")]
        for llm in (MockLLMProvider(), HeuristicFinancialLLMProvider()):
            with self.subTest(provider=llm.provider_name):
                reply = llm.converse(system_instructions="Be careful", context=context, messages=messages)
                self.assertNotIn("internal-article-id", reply.content)
                self.assertNotIn("Private source label", reply.content)
                self.assertNotIn("https://example.test/internal", reply.content)
                self.assertIn("integration costs", reply.content)

    def test_llm_unavailability_is_an_error_for_summary_research_and_conversation(self):
        class UnavailableLLM(MockLLMProvider):
            def summarize_article(self, article):
                raise LLMProviderUnavailable("provider unavailable")

            def research_stock(self, **kwargs):
                raise LLMProviderUnavailable("provider unavailable")

            def converse(self, **kwargs):
                raise LLMProviderUnavailable("provider unavailable")

        client = create_app(news_provider=MockNewsProvider(), llm_provider=UnavailableLLM()).test_client()
        article_id = client.get("/api/news?scope=market").get_json()["articles"][0]["article_id"]
        summary = client.post(f"/api/news/{article_id}/summary")
        research = client.post("/api/research/suggestions", json={"symbol": "TCS"})
        conversation = client.post("/api/conversations", json={
            "context_type": "article", "article_id": article_id}).get_json()
        message = client.post(f"/api/conversations/{conversation['conversation_id']}/messages", json={
            "request_id": "00000000-0000-4000-8000-000000000102", "content": "Follow up?"})
        for response in (summary, research, message):
            self.assertEqual(response.status_code, 503, response.get_json())
            self.assertIn("LLM_PROVIDER_UNAVAILABLE", response.get_json()["error"]["code"])

    def test_news_llm_failures_and_unknown_article_use_standard_errors(self):
        self.reset_news_state()
        class FailingNews(MockNewsProvider):
            def search_articles(self, **kwargs): raise NewsProviderUnavailable()
        class FailingLLM(MockLLMProvider):
            def summarize_article(self, article): raise LLMProviderUnavailable()
        self.assertEqual(create_app(news_provider=FailingNews()).test_client().get("/api/news?scope=market").status_code, 503)
        feed = self.client.get("/api/news?scope=market").get_json()
        aid = feed["articles"][0]["article_id"]
        response = create_app(llm_provider=FailingLLM()).test_client().post(f"/api/news/{aid}/summary")
        self.assertEqual(response.status_code, 503)
        missing = self.client.get("/api/news/no-such-article")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(set(missing.get_json()), {"error"})

    def test_openapi_live_paths_match_flask_routes(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "openapi.json"), encoding="utf-8") as f:
            paths = json.load(f)["paths"]
        live_spec_paths = {path for path, ops in paths.items()
                           if any(op.get("x-implementation-status") != "planned" for op in ops.values())}
        live_app_paths = {__import__("re").sub(r"<([^>]+)>", r"{\1}", rule.rule)
                          for rule in self.app.url_map.iter_rules() if rule.rule.startswith("/api/")}
        self.assertEqual(live_spec_paths, live_app_paths)

    def test_root_serves_react_production_build(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<div id="root"></div>', response.data)

    def test_root_explains_missing_react_build(self):
        with patch("app.Path.is_file", return_value=False):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"npm run frontend:build", response.data)

    def test_legacy_route_is_removed(self):
        response = self.client.get("/legacy")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
