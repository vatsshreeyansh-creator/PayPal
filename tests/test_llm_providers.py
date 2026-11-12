"""Unit and integration tests for Open-Source LLM Providers (Developer 3)."""
import json
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch
import urllib.error
from io import BytesIO

from llm_provider import (
    ArticleInput,
    ConversationMessage,
    ConversationReply,
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
    prepare_conversation,
    _provider_for_choice,
    get_default_llm_provider,
)
from mock_research_providers import MockLLMProvider
from config import load_local_environment


class TestOpenSourceLLMProviders(unittest.TestCase):
    def test_conversation_adapters_send_context_and_history_in_chronological_order(self):
        history = [ConversationMessage("user", "Why did margins decline?"),
                   ConversationMessage("assistant", "Costs rose, according to the report."),
                   ConversationMessage("user", "Is that serious?")]
        for provider in (GroqOpenSourceLLMProvider(api_key="test"),
                         HuggingFaceOpenSourceLLMProvider(api_key="test"),
                         OllamaOpenSourceLLMProvider(host="http://localhost:11434")):
            with self.subTest(provider=provider.provider_name), patch.object(provider, "_generate", return_value={"answer": "The source does not quantify the impact."}) as generate:
                result = provider.converse(system_instructions="Be careful", context="TCS report context", messages=history)
                self.assertIsInstance(result, ConversationReply)
                self.assertEqual(result.content, "The source does not quantify the impact.")
                prompt = generate.call_args.args[1]
                self.assertIn("TCS report context", prompt)
                self.assertLess(prompt.index("Why did margins decline?"), prompt.index("Costs rose, according to the report."))
                self.assertLess(prompt.index("Costs rose, according to the report."), prompt.index("Is that serious?"))

    def test_conversation_adapters_use_the_shared_context_budget_preparation(self):
        history = [ConversationMessage("user", "Why did margins decline?"),
                   ConversationMessage("assistant", "Costs rose, according to the report."),
                   ConversationMessage("user", "Is that serious?")]
        for provider in (GroqOpenSourceLLMProvider(api_key="test"),
                         HuggingFaceOpenSourceLLMProvider(api_key="test"),
                         OllamaOpenSourceLLMProvider(host="http://localhost:11434")):
            with self.subTest(provider=provider.provider_name), patch.object(provider, "_generate", return_value={"answer": "The source does not quantify the impact."}) as generate:
                expected = prepare_conversation("TCS report context", history)
                result = provider.converse(system_instructions="Be careful", context="TCS report context", messages=history)
                self.assertIsInstance(result, ConversationReply)
                self.assertEqual(result.content, "The source does not quantify the impact.")
                self.assertEqual(generate.call_args.args[1], expected.prompt)

    def test_conversation_prompt_budget_preserves_latest_question_and_pinned_metadata(self):
        long_body = " ".join(f"Reported development {index} changed operating costs." for index in range(800))
        context = json.dumps({"kind": "article", "article_id": "a-1", "title": "Pinned title",
            "source": "Pinned source", "url": "https://example.test/a", "summary": "Essential provider summary.",
            "content": long_body, "ai_summary": "Saved AI summary.", "reported_facts": ["Saved fact."]})
        history = []
        for index in range(10):
            history.extend([ConversationMessage("user", f"Older question {index}? " + "u" * 1200),
                            ConversationMessage("assistant", f"Older answer {index}. " + "a" * 1200)])
        latest_question = "What is the context? " + ("margin impact " * 330)
        latest_question = latest_question[:4000]
        history.append(ConversationMessage("user", latest_question))

        prepared = prepare_conversation(context, history)
        self.assertLessEqual(len(prepared.prompt), 25_000)
        self.assertLessEqual(len(prepared.context), 12_000)
        self.assertIn("Pinned title", prepared.prompt)
        self.assertIn("Essential provider summary.", prepared.prompt)
        self.assertIn(latest_question, prepared.prompt)
        self.assertEqual(prepared.prompt.count(latest_question), 1)
        self.assertTrue(prepared.source_truncated)
        self.assertGreater(prepared.omitted_turns, 0)
        self.assertIn("omitted", prepared.prompt)

    def test_context_budget_keeps_short_conversations_and_accepts_maximum_question(self):
        question = "Q" * 4000
        prepared = prepare_conversation("Pinned report and source facts.", [
            ConversationMessage("user", "First question?"),
            ConversationMessage("assistant", "First answer."),
            ConversationMessage("user", question),
        ])
        self.assertEqual(prepared.messages[-1].content, question)
        self.assertEqual(prepared.prompt.count(question), 1)
        self.assertFalse(prepared.source_truncated)
        self.assertEqual(prepared.omitted_turns, 0)

    def test_context_budget_selects_recent_complete_turns(self):
        messages = []
        for index in range(5):
            messages.extend([ConversationMessage("user", f"Question {index}: " + "x" * 3000),
                             ConversationMessage("assistant", f"Answer {index}: " + "y" * 3000)])
        messages.append(ConversationMessage("user", "Newest question?"))
        prepared = prepare_conversation("Pinned source fact.", messages)
        self.assertIn("Newest question?", prepared.prompt)
        self.assertIn("Question 4:", prepared.prompt)
        self.assertNotIn("Question 0:", prepared.prompt)
        self.assertIn("Omitted", prepared.prompt)

    def test_composite_fallback_receives_the_same_context_and_history(self):
        class UnavailableConversation:
            provider_name = "unavailable-test"
            api_key = "configured"

            def __init__(self):
                self.received = None

            def converse(self, **kwargs):
                self.received = kwargs
                raise LLMProviderUnavailable("temporary outage")

        composite = CompositeLiveLLMProvider()
        failed = UnavailableConversation()
        composite._groq = failed
        composite._hf = None
        composite._ollama = None
        messages = [ConversationMessage("user", "Earlier question?"),
                    ConversationMessage("assistant", "Earlier answer."),
                    ConversationMessage("user", "Latest question?")]
        reply = composite.converse(system_instructions="Cautious", context="Pinned facts.", messages=messages)
        self.assertEqual(failed.received["context"], "Pinned facts.")
        self.assertEqual(failed.received["messages"], messages)
        self.assertEqual(reply.provider, composite._heuristic.provider_name)

    def test_composite_fallback_labels_actual_summary_and_research_provider(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "", "HF_TOKEN": "",
                                     "HUGGINGFACE_API_KEY": "", "OLLAMA_HOST": ""}):
            composite = CompositeLiveLLMProvider()
        article = ArticleInput("TCS update", "Source", "Summary", "TCS reported a new contract.")
        summary = composite.summarize_article(article)
        research = composite.research_stock(symbol="TCS", current_price=None, evidence=[])
        self.assertEqual(summary.provider, composite._heuristic.provider_name)
        self.assertEqual(research.provider, composite._heuristic.provider_name)
        self.assertEqual(composite.provider_name, "tradepoint-composite")

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
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            provider = GroqOpenSourceLLMProvider(api_key="")
            article = ArticleInput("Title", "Source", "Summary", "Content")
            with self.assertRaises(LLMProviderUnavailable):
                provider.summarize_article(article)

    @patch("urllib.request.urlopen")
    def test_groq_llama_provider_mocked_response(self, mock_urlopen):
        """Verify open-source Llama response parsing via Groq."""
        provider = GroqOpenSourceLLMProvider(api_key="fake-groq-key", model="openai/gpt-oss-20b")
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
        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(payload["model"], "openai/gpt-oss-20b")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["reasoning_format"], "hidden")
        self.assertEqual(payload["max_completion_tokens"], 1024)
        self.assertNotIn("max_tokens", payload)

    @patch("urllib.request.urlopen")
    def test_groq_conversation_uses_pinned_context_and_ordered_history(self, mock_urlopen):
        response_data = {"choices": [{"message": {"content": json.dumps({
            "answer": "The report attributes the decline to higher integration costs; it does not quantify duration."
        })}}]}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        provider = GroqOpenSourceLLMProvider(api_key="fake-groq-key", model="openai/gpt-oss-20b")
        messages = [ConversationMessage("user", "Why did margins fall?"),
                    ConversationMessage("assistant", "Costs rose during integration."),
                    ConversationMessage("user", "Is that serious?")]

        reply = provider.converse(system_instructions="Be cautious.", context=json.dumps({
            "kind": "article", "title": "TCS margins", "content": "Margins declined due to integration costs."
        }), messages=messages)

        self.assertEqual(reply.provider, provider.provider_name)
        self.assertIn("does not quantify", reply.content)
        payload = json.loads(mock_urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["messages"][0]["content"], "Be cautious.")
        prompt = payload["messages"][1]["content"]
        self.assertLess(prompt.index("Why did margins fall?"), prompt.index("Costs rose during integration."))
        self.assertLess(prompt.index("Costs rose during integration."), prompt.index("Is that serious?"))
        self.assertIn("TCS margins", prompt)
        self.assertIn("Do not repeat internal metadata", prompt)

    @patch("urllib.request.urlopen")
    def test_groq_http_failure_is_a_provider_unavailable_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://api.groq.com/openai/v1/chat/completions", 401, "Unauthorized", {}, BytesIO(b"bad key")
        )
        provider = GroqOpenSourceLLMProvider(api_key="fake-groq-key")
        with self.assertRaisesRegex(LLMProviderUnavailable, "HTTP 401"):
            provider.summarize_article(ArticleInput("Title", "Source", "Summary", "Text"))

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
        """The opt-in composite labels its heuristic fallback instead of claiming a remote model."""
        with patch.dict(os.environ, {"GROQ_API_KEY": "", "HF_TOKEN": "",
                                     "HUGGINGFACE_API_KEY": "", "OLLAMA_HOST": ""}):
            provider = CompositeLiveLLMProvider()
        self.assertEqual(provider.provider_name, "tradepoint-composite")
        article = ArticleInput("TCS Wins Contract", "Source", "Deal win", "TCS signed a $500M deal.")
        draft = provider.summarize_article(article)
        self.assertIsInstance(draft, SummaryDraft)
        self.assertTrue(len(draft.summary) > 0)
        self.assertEqual(draft.provider, "tradepoint-financial-nlp")

    def test_llm_provider_factory(self):
        """Verify get_default_llm_provider respects environment controls."""
        self.assertIsInstance(get_default_llm_provider(), MockLLMProvider)
        with patch.dict(os.environ, {"TRADEPOINT_LLM_PROVIDER": "", "GROQ_API_KEY": "",
                                     "TRADEPOINT_GROQ_MODEL": "openai/gpt-oss-20b"}):
            selected = get_default_llm_provider(testing=False)
        self.assertIsInstance(selected, GroqOpenSourceLLMProvider)
        self.assertEqual(selected.model, "openai/gpt-oss-20b")

        self.assertIsInstance(_provider_for_choice("mock"), MockLLMProvider)
        self.assertIsInstance(_provider_for_choice("heuristic"), HeuristicFinancialLLMProvider)
        with patch.dict(os.environ, {"GROQ_API_KEY": "k"}):
            self.assertIsInstance(_provider_for_choice("groq"), GroqOpenSourceLLMProvider)
        with patch.dict(os.environ, {"HF_TOKEN": "k"}):
            self.assertIsInstance(_provider_for_choice("huggingface"), HuggingFaceOpenSourceLLMProvider)
        self.assertIsInstance(_provider_for_choice("ollama"), OllamaOpenSourceLLMProvider)
        self.assertIsInstance(_provider_for_choice("composite"), CompositeLiveLLMProvider)
        with self.assertRaisesRegex(ValueError, "TRADEPOINT_LLM_PROVIDER"):
            _provider_for_choice("grok")

    def test_local_environment_file_loads_without_overriding_host_environment(self):
        env_key = "TRADEPOINT_DOTENV_TEST_" + os.urandom(8).hex().upper()
        host_key = env_key + "_HOST"
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, ".env.local").write_text(
                f"{env_key}=loaded-from-file\n{host_key}=file-value\n", encoding="utf-8"
            )
            with patch.dict(os.environ, {host_key: "host-value"}):
                load_local_environment(Path(temp_dir))
                self.assertEqual(os.getenv(env_key), "loaded-from-file")
                self.assertEqual(os.getenv(host_key), "host-value")



if __name__ == "__main__":
    unittest.main()
