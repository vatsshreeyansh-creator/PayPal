import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
DB_FILE.close()
os.environ["TRADEPOINT_DATABASE_URL"] = "sqlite:///" + DB_FILE.name.replace("\\", "/")

from app import create_app
from provider import MarketDataProvider, MockMarketDataProvider, QuoteData, InstrumentData
from news_provider import NewsProvider
from llm_provider import LLMProvider
from schemas import Quote, OrderRequest, OrderResponse, Transaction, ErrorResponse


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()

    def test_provider_protocol_and_batch_shape(self):
        provider = MockMarketDataProvider()
        self.assertIsInstance(provider, MarketDataProvider)
        stocks = provider.search_stocks("Tata", 20)
        quotes = provider.get_quotes(stocks)
        self.assertEqual(set(quotes), {(x.exchange, x.symbol) for x in stocks})
        self.assertTrue(all(isinstance(q, QuoteData) and q.simulated for q in quotes.values()))

    def test_news_and_llm_provider_protocols_are_implementable(self):
        class NewsMock:
            def search_articles(self, query, symbols, limit): return []
            def get_article(self, article_id): return None
        class LlmMock:
            def summarize(self, text, *, max_words): return "summary"
            def generate_research(self, *, question, evidence): return "research"
        self.assertIsInstance(NewsMock(), NewsProvider)
        self.assertIsInstance(LlmMock(), LLMProvider)

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
        for path in ("/api/account", "/api/portfolio", "/api/orders", "/api/transactions",
                     "/api/news", "/api/news/{article_id}", "/api/news/{article_id}/summary",
                     "/api/research/suggestions"):
            self.assertTrue(any(op.get("x-implementation-status") == "planned" for op in spec["paths"][path].values()))

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
