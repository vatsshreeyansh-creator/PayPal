"""Unit and integration tests for Open-Source LLM Providers (Developer 3)."""
import json
import os
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from llm_provider import (
    ArticleInput,
    CompositeLiveLLMProvider,
    GroqOpenSourceLLMProvider,
    HeuristicFinancialLLMProvider,
    HuggingFaceOpenSourceLLMProvider,
    LLMProvider,
    LLMProviderUnavailable,
    OllamaOpenSourceLLMProvider,
    ResearchDraft,
    ResearchEvidence,
    SummaryDraft,
    get_default_llm_provider,
)
from mock_research_providers import MockLLMProvider


class TestOpenSourceLLMProviders(unittest.TestCase):
    def test_mock_provider_conformance(self):
        """Verify MockLLMProvider conforms to LLMProvider Protocol."""
        provider = MockLLMProvider()
        self.assertIsInstance(provider, LLMProvider)
        self.assertEqual(provider.provider_name, "mock-llm")

    def test_heuristic_provider_conformance(self):
        """Verify HeuristicFinancialLLMProvider conforms to LLMProvider Protocol."""
        provider = HeuristicFinancialLLMProvider()
        self.assertIsInstance(provider, LLMProvider)
        self.assertEqual(provider.provider_name, "tradepoint-financial-nlp")

    def test_heuristic_summarize_article(self):
        """Verify structured summarization separates reported facts from implications."""
        provider = HeuristicFinancialLLMProvider()
        article = ArticleInput(
            title="TCS announces ₹15,000 crore quarterly profit, expanding cloud deals",
            source="Moneycontrol",
            summary="TCS reports steady earnings growth across North America.",
            content=(
                "Tata Consultancy Services reported a consolidated quarterly net profit of ₹15,000 crore, "
                "marking a 5% year-on-year increase. The tech giant highlighted record deal wins in cloud "
                "transformation, while noting margin pressure from software integration costs."
            ),
        )
        draft = provider.summarize_article(article)
        self.assertIsInstance(draft, SummaryDraft)
        self.assertTrue(len(draft.summary) > 0)
        self.assertGreaterEqual(len(draft.reported_facts), 1)
        self.assertGreaterEqual(len(draft.key_developments), 1)
        self.assertGreaterEqual(len(draft.positive_implications), 1)
        self.assertGreaterEqual(len(draft.negative_implications), 1)

    def test_heuristic_research_stock(self):
        """Verify research thesis generation with evidence."""
        provider = HeuristicFinancialLLMProvider()
        evidence = [
            ResearchEvidence(
                article_id="art-1",
                title="TCS signs multi-year digital transformation deal",
                source="Reuters",
                published_at="2026-11-08T10:00:00Z",
                summary="TCS expands presence in European banking sector.",
            ),
            ResearchEvidence(
                article_id="art-2",
                title="Indian IT equities face currency fluctuations",
                source="Bloomberg",
                published_at="2026-11-07T14:00:00Z",
                summary="Currency volatility impacts quarterly margins.",
            ),
        ]
        draft = provider.research_stock(symbol="TCS", current_price=Decimal("3865.25"), evidence=evidence)
        self.assertIsInstance(draft, ResearchDraft)
        self.assertIn("TCS", draft.thesis)
        self.assertGreaterEqual(len(draft.risks), 1)
        self.assertGreaterEqual(len(draft.reported_facts), 1)
        self.assertGreaterEqual(len(draft.positive_implications), 1)
        self.assertGreaterEqual(len(draft.negative_implications), 1)
        self.assertTrue(len(draft.uncertainty) > 0)

    def test_heuristic_empty_evidence(self):
        """Verify handling empty evidence gracefully."""
        provider = HeuristicFinancialLLMProvider()
        draft = provider.research_stock(symbol="INFY", current_price=None, evidence=[])
        self.assertIn("Insufficient news evidence", draft.thesis)
        self.assertTrue(draft.uncertainty.startswith("High"))

    def test_groq_llama_provider_requires_key(self):
        """GroqOpenSourceLLMProvider raises LLMProviderUnavailable if key is absent."""
        provider = GroqOpenSourceLLMProvider(api_key="")
        article = ArticleInput("Title", "Source", "Summary", "Content")
        with self.assertRaises(LLMProviderUnavailable):
            provider.summarize_article(article)

    @patch("urllib.request.urlopen")
    def test_groq_llama_provider_mocked_response(self, mock_urlopen):
        """Verify open-source Llama response parsing via Groq."""
        provider = GroqOpenSourceLLMProvider(api_key="fake-groq-key")
        mock_payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "summary": "TCS reports solid performance with Llama 3.",
                            "key_developments": ["Cloud contract expansion"],
                            "reported_facts": ["Revenue rose 5%"],
                            "positive_implications": ["Sustained enterprise demand"],
                            "negative_implications": ["Execution wage pressure"],
                        })
                    }
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        article = ArticleInput("TCS Q2", "Source", "Summary", "Content")
        draft = provider.summarize_article(article)
        self.assertEqual(draft.summary, "TCS reports solid performance with Llama 3.")
        self.assertEqual(draft.reported_facts, ["Revenue rose 5%"])

    def test_huggingface_provider_requires_key(self):
        """HuggingFaceOpenSourceLLMProvider raises LLMProviderUnavailable if key is absent."""
        provider = HuggingFaceOpenSourceLLMProvider(api_key="")
        article = ArticleInput("Title", "Source", "Summary", "Content")
        with self.assertRaises(LLMProviderUnavailable):
            provider.summarize_article(article)

    def test_ollama_provider_conformance(self):
        """Verify Ollama local open-source provider protocol conformance."""
        provider = OllamaOpenSourceLLMProvider()
        self.assertIsInstance(provider, LLMProvider)
        self.assertEqual(provider.provider_name, "opensource-ollama-local")

    def test_composite_provider_automatic_fallback(self):
        """Verify CompositeLiveLLMProvider falls back to local open-source NLP engine when no remote keys are set."""
        provider = CompositeLiveLLMProvider()
        self.assertEqual(provider.provider_name, "tradepoint-financial-nlp")
        article = ArticleInput("TCS Wins Contract", "Source", "Deal win", "TCS signed a $500M deal.")
        draft = provider.summarize_article(article)
        self.assertIsInstance(draft, SummaryDraft)
        self.assertTrue(len(draft.summary) > 0)

    def test_llm_provider_factory(self):
        """Verify get_default_llm_provider respects environment controls."""
        with patch.dict(os.environ, {"TRADEPOINT_LLM_PROVIDER": "mock"}):
            self.assertIsInstance(get_default_llm_provider(), MockLLMProvider)

        with patch.dict(os.environ, {"TRADEPOINT_LLM_PROVIDER": "heuristic"}):
            self.assertIsInstance(get_default_llm_provider(), HeuristicFinancialLLMProvider)

        with patch.dict(os.environ, {"TRADEPOINT_LLM_PROVIDER": "groq", "GROQ_API_KEY": "k"}):
            self.assertIsInstance(get_default_llm_provider(), GroqOpenSourceLLMProvider)

        with patch.dict(os.environ, {"TRADEPOINT_LLM_PROVIDER": "huggingface", "HF_TOKEN": "k"}):
            self.assertIsInstance(get_default_llm_provider(), HuggingFaceOpenSourceLLMProvider)

        with patch.dict(os.environ, {"TRADEPOINT_LLM_PROVIDER": "ollama"}):
            self.assertIsInstance(get_default_llm_provider(), OllamaOpenSourceLLMProvider)


if __name__ == "__main__":
    unittest.main()
