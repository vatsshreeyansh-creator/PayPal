"""Unit and integration tests for News Providers (Developer 3)."""
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from mock_research_providers import MockNewsProvider
from news_provider import (
    ArticleData,
    LiveNewsProvider,
    NewsPage,
    NewsProvider,
    NewsProviderUnavailable,
    get_default_news_provider,
)


class TestNewsProviders(unittest.TestCase):
    def test_mock_provider_conformance(self):
        """Verify MockNewsProvider conforms to NewsProvider Protocol."""
        provider = MockNewsProvider()
        self.assertIsInstance(provider, NewsProvider)
        page = provider.search_articles(query=None, symbols=["TCS"], page_token=None, page_size=10)
        self.assertIsInstance(page, NewsPage)
        self.assertGreater(len(page.articles), 0)

    def test_live_news_provider_conformance(self):
        """Verify LiveNewsProvider conforms to NewsProvider Protocol."""
        provider = LiveNewsProvider()
        self.assertIsInstance(provider, NewsProvider)

    def test_live_news_search_general_market(self):
        """Verify general market news search returns real articles with valid metadata."""
        provider = LiveNewsProvider()
        page = provider.search_articles(query=None, symbols=[], page_token=None, page_size=5)

        self.assertIsInstance(page, NewsPage)
        self.assertGreater(len(page.articles), 0)
        article = page.articles[0]

        self.assertIsInstance(article, ArticleData)
        self.assertTrue(article.provider_article_id.startswith("gn-") or article.provider_article_id.startswith("live-"))
        self.assertTrue(len(article.title) > 0)
        self.assertTrue(len(article.source) > 0)
        self.assertTrue(article.url.startswith("http"))
        self.assertIsInstance(article.published_at, datetime)
        self.assertEqual(article.published_at.tzinfo, timezone.utc)
        self.assertIsNotNone(article.summary)

    def test_live_news_search_symbol_targeted(self):
        """Verify searching for a specific stock returns articles associated with that symbol."""
        provider = LiveNewsProvider()
        page = provider.search_articles(query=None, symbols=["TCS"], page_token=None, page_size=5)

        self.assertGreater(len(page.articles), 0)
        for article in page.articles:
            self.assertIn("TCS", article.symbols)

    def test_live_news_pagination(self):
        """Verify cursor-based pagination works."""
        provider = LiveNewsProvider()
        page1 = provider.search_articles(query=None, symbols=[], page_token="0", page_size=2)
        self.assertEqual(len(page1.articles), 2)
        self.assertIsNotNone(page1.next_page_token)

        page2 = provider.search_articles(query=None, symbols=[], page_token=page1.next_page_token, page_size=2)
        self.assertGreater(len(page2.articles), 0)
        # Verify page 2 is different from page 1
        self.assertNotEqual(page1.articles[0].provider_article_id, page2.articles[0].provider_article_id)

    def test_live_news_get_article(self):
        """Verify retrieving an article by source and provider article ID."""
        provider = LiveNewsProvider()
        page = provider.search_articles(query=None, symbols=[], page_token=None, page_size=2)
        target = page.articles[0]

        retrieved = provider.get_article(source=target.source, provider_article_id=target.provider_article_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.provider_article_id, target.provider_article_id)
        self.assertEqual(retrieved.title, target.title)

    def test_live_news_fallback_resilience(self):
        """Verify fallback articles are returned if network is unavailable."""
        provider = LiveNewsProvider()
        with patch("urllib.request.urlopen", side_effect=Exception("Network down")):
            page = provider.search_articles(query=None, symbols=[], page_token=None, page_size=5)
            self.assertGreater(len(page.articles), 0)
            self.assertTrue(any(a.provider_article_id.startswith("live-fallback") for a in page.articles))

    def test_news_provider_factory(self):
        """Verify get_default_news_provider respects configuration."""
        with patch.dict(os.environ, {"TRADEPOINT_NEWS_PROVIDER": "mock"}):
            self.assertIsInstance(get_default_news_provider(), MockNewsProvider)

        with patch.dict(os.environ, {"TRADEPOINT_NEWS_PROVIDER": "live"}):
            self.assertIsInstance(get_default_news_provider(), LiveNewsProvider)


if __name__ == "__main__":
    unittest.main()

