"""Normalized text generation boundary; no LLM credentials/client in MVP."""
from typing import Protocol, runtime_checkable


class LLMProviderUnavailable(Exception):
    pass


@runtime_checkable
class LLMProvider(Protocol):
    def summarize(self, text: str, *, max_words: int) -> str: ...
    def generate_research(self, *, question: str, evidence: list[str]) -> str: ...
