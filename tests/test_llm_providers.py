"""Unit tests for provider selection; no network calls are made."""
from types import SimpleNamespace
import sys

import pytest

from app import llm, settings


def test_openrouter_chat_completions(monkeypatch):
    seen = {}
    class FakeChat:
        class completions:
            @staticmethod
            def create(**kwargs):
                seen["request"] = kwargs
                return SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content="Use the VPN runbook [1].")
                )])

    class FakeClient:
        def __init__(self, **kwargs):
            seen["client"] = kwargs
            self.chat = FakeChat()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeClient))
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(settings, "OPENROUTER_MODEL", "google/gemini-3.1-flash-lite")
    answer = llm.generate_grounded_answer("VPN issue?", "[1] VPN help article")
    assert "runbook [1]" in answer
    assert seen["client"]["base_url"] == "https://openrouter.ai/api/v1"
    assert seen["request"]["model"] == "google/gemini-3.1-flash-lite"
    assert seen["request"]["messages"][0]["role"] == "system"


def test_openai_responses_api(monkeypatch):
    seen = {}
    class FakeResponses:
        def create(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(output_text="See the policy [1].")
    class FakeClient:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeClient))
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "OPENAI_MODEL", "gpt-5-mini")
    answer = llm.generate_grounded_answer("policy?", "[1] Policy text")
    assert "policy [1]" in answer
    assert seen["store"] is False


def test_missing_openrouter_key(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        llm.generate_grounded_answer("q", "ctx")


def test_unknown_provider(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "unknown")
    with pytest.raises(RuntimeError, match="LLM_PROVIDER"):
        llm.generate_grounded_answer("q", "ctx")
