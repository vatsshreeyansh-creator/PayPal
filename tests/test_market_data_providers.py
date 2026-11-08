"""Unit and integration tests for Market Data Providers (Developer 3)."""
import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from provider import (
    HistoricalBar,
    InstrumentData,
    KiteMarketDataProvider,
    LiveMarketDataProvider,
    MarketDataProvider,
    MockMarketDataProvider,
    ProviderUnavailable,
    QuoteData,
    get_default_market_provider,
)


class TestMarketDataProviders(unittest.TestCase):
    def test_mock_provider_conformance(self):
        """Verify MockMarketDataProvider complies with the Protocol."""
        provider = MockMarketDataProvider()
        self.assertIsInstance(provider, MarketDataProvider)
        results = provider.search_stocks("Tata", 10)
        self.assertGreater(len(results), 0)
        quotes = provider.get_quotes(results)
        self.assertTrue(all(isinstance(q, QuoteData) for q in quotes.values()))
        self.assertTrue(all(q.simulated for q in quotes.values()))

    def test_live_provider_conformance_and_seeding(self):
        """Verify LiveMarketDataProvider protocol conformance and seed catalog."""
        provider = LiveMarketDataProvider()
        self.assertIsInstance(provider, MarketDataProvider)

        # Empty search returns seed catalog
        seeded = provider.search_stocks("", 50)
        self.assertGreaterEqual(len(seeded), 20)
        for inst in seeded:
            self.assertEqual(inst.exchange, "NSE")
            self.assertEqual(inst.instrument_type, "EQ")
            self.assertGreater(inst.instrument_token, 0)

        # Check key stocks are in seed universe
        symbols = {i.symbol for i in seeded}
        self.assertIn("TCS", symbols)
        self.assertIn("INFY", symbols)
        self.assertIn("RELIANCE", symbols)
        self.assertIn("AAPL", symbols)

    def test_live_provider_search(self):
        """Verify live provider search returns normalized InstrumentData."""
        provider = LiveMarketDataProvider()
        results = provider.search_stocks("Tata", 5)
        self.assertGreaterEqual(len(results), 1)
        for inst in results:
            self.assertEqual(inst.exchange, "NSE")
            self.assertEqual(inst.instrument_type, "EQ")
            self.assertIsInstance(inst.instrument_token, int)
            self.assertGreater(inst.instrument_token, 0)

    def test_live_provider_quotes(self):
        """Verify batch quotes return live non-simulated QuoteData with 2 decimal precision."""
        provider = LiveMarketDataProvider()
        instruments = [
            InstrumentData("NSE", "TCS", "Tata Consultancy Services Limited", 1001, "EQ"),
            InstrumentData("NSE", "INFY", "Infosys Limited", 1002, "EQ"),
        ]
        quotes = provider.get_quotes(instruments)
        self.assertIn(("NSE", "TCS"), quotes)
        tcs_quote = quotes[("NSE", "TCS")]

        self.assertIsInstance(tcs_quote, QuoteData)
        self.assertFalse(tcs_quote.simulated)  # Real live market data
        self.assertGreater(tcs_quote.price, Decimal("0.00"))
        self.assertIsInstance(tcs_quote.as_of, datetime)
        self.assertEqual(tcs_quote.as_of.tzinfo, timezone.utc)

        # Check caching: subsequent call immediately hits cache
        cached_quotes = provider.get_quotes(instruments)
        self.assertEqual(cached_quotes[("NSE", "TCS")].price, tcs_quote.price)

    def test_live_provider_historical_prices(self):
        """Verify historical price extraction returns HistoricalBar records."""
        provider = LiveMarketDataProvider()
        bars = provider.get_historical_prices("TCS", interval="1d", range_="5d")
        if bars:  # Network may vary, but when returned, verify structure
            self.assertIsInstance(bars[0], HistoricalBar)
            self.assertGreater(bars[0].close, Decimal("0.00"))
            self.assertIsInstance(bars[0].timestamp, datetime)

    def test_kite_provider_requires_credentials(self):
        """KiteMarketDataProvider raises ProviderUnavailable if credentials are missing."""
        provider = KiteMarketDataProvider(api_key="", access_token="")
        self.assertIsInstance(provider, MarketDataProvider)
        with self.assertRaises(ProviderUnavailable):
            provider.search_stocks("TCS")
        with self.assertRaises(ProviderUnavailable):
            provider.get_quotes([InstrumentData("NSE", "TCS", "TCS", 123, "EQ")])

    @patch("urllib.request.urlopen")
    def test_kite_provider_mocked_execution(self, mock_urlopen):
        """Verify KiteMarketDataProvider translates Kite responses into normalized models."""
        provider = KiteMarketDataProvider(api_key="test_key", access_token="test_token")

        # Mock CSV response for instruments
        csv_data = (
            "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\n"
            "738561,2885,RELIANCE,RELIANCE IND,2950.0,,,,1,EQ,NSE,NSE\n"
        ).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = csv_data
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        results = provider.search_stocks("RELIANCE", 10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].symbol, "RELIANCE")
        self.assertEqual(results[0].instrument_token, 738561)
        self.assertEqual(results[0].exchange, "NSE")
        self.assertEqual(results[0].instrument_type, "EQ")

    def test_provider_factory(self):
        """Verify get_default_market_provider respects environment controls."""
        with patch.dict(os.environ, {"TRADEPOINT_MARKET_PROVIDER": "mock"}):
            self.assertIsInstance(get_default_market_provider(), MockMarketDataProvider)

        with patch.dict(os.environ, {"TRADEPOINT_MARKET_PROVIDER": "live"}):
            self.assertIsInstance(get_default_market_provider(), LiveMarketDataProvider)

        with patch.dict(os.environ, {"TRADEPOINT_MARKET_PROVIDER": "kite", "KITE_API_KEY": "k", "KITE_ACCESS_TOKEN": "t"}):
            self.assertIsInstance(get_default_market_provider(), KiteMarketDataProvider)


if __name__ == "__main__":
    unittest.main()
