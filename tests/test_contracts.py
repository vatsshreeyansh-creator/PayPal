import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
DB_FILE.close()
os.environ["TRADEPOINT_DATABASE_URL"] = "sqlite:///" + DB_FILE.name.replace("\\", "/")

from app import create_app
from provider import MarketDataProvider, MockMarketDataProvider, QuoteData, InstrumentData
from news_provider import NewsProvider, NewsProviderUnavailable
from llm_provider import LLMProvider, LLMProviderUnavailable
from schemas import Quote, OrderRequest, OrderResponse, Transaction, ErrorResponse
from config import DEMO_USER_ID, INITIAL_CASH
from database import SessionLocal
from models import Account, ArticleRecord, ArticleSummaryRecord, CashLedgerEntry, Holding, Instrument, Order, TransactionRecord
from mock_research_providers import MockNewsProvider, MockLLMProvider
from news_provider import NewsPage
from sqlalchemy import select
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

    def test_news_and_llm_provider_protocols_are_implementable(self):
        self.assertIsInstance(MockNewsProvider(), NewsProvider)
        self.assertIsInstance(MockLLMProvider(), LLMProvider)

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
        for path in ("/api/news", "/api/news/{article_id}", "/api/news/{article_id}/summary", "/api/research/suggestions"):
            self.assertTrue(any(op.get("x-implementation-status") != "planned" for op in spec["paths"][path].values()))

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
        self.assertTrue(suggestion["evidence_article_ids"])
        self.assertTrue(suggestion["uncertainty"])
        self.assertTrue(response.get_json()["disclaimer"])

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

    def test_frontend_calls_and_reads_contract_fields(self):
        path = os.path.join(os.path.dirname(__file__), "..", "templates", "index.html")
        with open(path, encoding="utf-8") as f:
            source = f.read()
        for required in ("/api/stocks/search", "/api/watchlist", "data.results", "data.items",
                         "item.stock.name", "item.stock.symbol", "item.quote.price",
                         "item.quote.currency", "item.quote.simulated", "body.error?.message"):
            self.assertIn(required, source)


if __name__ == "__main__":
    unittest.main()
