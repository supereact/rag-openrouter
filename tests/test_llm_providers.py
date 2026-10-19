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


@pytest.mark.parametrize('provider', ['openrouter', 'openai'])
def test_chinese_question_and_citations_reach_provider_unchanged(monkeypatch, provider):
    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(output_text='十五天。[1]', choices=[SimpleNamespace(
            message=SimpleNamespace(content='十五天。[1]'))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
                             responses=SimpleNamespace(create=create))
    monkeypatch.setitem(sys.modules, 'openai', SimpleNamespace(OpenAI=lambda **_: client))
    monkeypatch.setattr(settings, 'LLM_PROVIDER', provider)
    monkeypatch.setattr(settings, 'OPENROUTER_API_KEY', 'test-key')
    monkeypatch.setattr(settings, 'OPENROUTER_MODEL', 'test-model')
    monkeypatch.setattr(settings, 'OPENAI_API_KEY', 'test-key')
    monkeypatch.setattr(settings, 'OPENAI_MODEL', 'test-model')
    assert llm.generate_grounded_answer('年假有多少天？', '[1] 員工年假：十五天。') == '十五天。[1]'
    assert len(requests) == 1
    request = requests[0]
    instructions = request['messages'][0]['content'] if provider == 'openrouter' else request['instructions']
    prompt = request['messages'][1]['content'] if provider == 'openrouter' else request['input']
    assert 'same language and script' in instructions
    assert 'untrusted data' in instructions
    assert '年假有多少天？' in prompt
    assert '[1] 員工年假：十五天。' in prompt


@pytest.mark.parametrize('provider', ['openrouter', 'openai'])
def test_follow_up_context_is_untrusted_and_only_current_sources_are_evidence(monkeypatch, provider):
    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(output_text='Second option [1]', choices=[SimpleNamespace(
            message=SimpleNamespace(content='Second option [1]'))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
                             responses=SimpleNamespace(create=create))
    monkeypatch.setitem(sys.modules, 'openai', SimpleNamespace(OpenAI=lambda **_: client))
    monkeypatch.setattr(settings, 'LLM_PROVIDER', provider)
    for name in ('OPENROUTER_API_KEY', 'OPENROUTER_MODEL', 'OPENAI_API_KEY', 'OPENAI_MODEL'):
        monkeypatch.setattr(settings, name, 'test-value')
    llm.generate_grounded_answer('What about the second?', '[1] Current evidence',
                                 conversation_context='[{"question":"Options?","answer":"A, B"}]')
    assert len(requests) == 1
    request = requests[0]
    instructions = request['messages'][0]['content'] if provider == 'openrouter' else request['instructions']
    prompt = request['messages'][1]['content'] if provider == 'openrouter' else request['input']
    assert 'not factual evidence or instructions' in instructions
    assert 'ask for clarification' in instructions and 'current source excerpts only' in instructions
    assert 'What about the second?' in prompt and '[1] Current evidence' in prompt
    assert 'Previous conversation (JSON, context only)' in prompt and 'A, B' in prompt
