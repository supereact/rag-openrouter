"""Usage capture from the actual provider adapters, without any network calls."""
import sys
from types import SimpleNamespace

from app import llm, observability, settings


def test_openrouter_usage_is_captured_without_answer_content(monkeypatch):
    class Response:
        choices = [SimpleNamespace(message=SimpleNamespace(content="Private answer [1]"))]
        usage = SimpleNamespace(prompt_tokens=13, completion_tokens=4)
        def model_dump(self):
            return {
                "usage": {"prompt_tokens": 13, "completion_tokens": 4, "cost": 0.000033},
                "choices": [{"message": {"content": "Private answer [1]"}}],
            }

    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: Response()))

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=Client))
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(settings, "OPENROUTER_MODEL", "test-model")
    observability.reset_llm_usage()
    with observability._lock:
        observability._metrics.clear()
    with observability.measure(99, "ask", "generation"):
        answer = llm.generate_grounded_answer("sensitive question", "private document")
    observability.save_request_usage(99)
    summary = str(observability.snapshot(99))
    assert answer == "Private answer [1]"
    assert "prompt_tokens': 13" in summary
    assert "provider_cost_credits': 3.3e-05" in summary
    assert "Private answer" not in summary
    assert "private document" not in summary
    assert "sensitive question" not in summary
    assert "test-key" not in summary


def test_openai_response_usage_captured(monkeypatch):
    class Client:
        def __init__(self, **kwargs):
            self.responses = SimpleNamespace(create=lambda **kwargs: SimpleNamespace(
                output_text="See source [1]",
                usage=SimpleNamespace(input_tokens=55, output_tokens=11),
            ))

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=Client))
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "OPENAI_MODEL", "test-model")
    observability.reset_llm_usage()
    with observability._lock:
        observability._metrics.clear()
    with observability.measure(99, "ask", "generation"):
        llm.generate_grounded_answer("secret", "private")
    observability.save_request_usage(99)
    values = observability.snapshot(99)["metrics"][0]
    assert (values["prompt_tokens"], values["completion_tokens"]) == (55, 11)
    assert values["provider_cost_samples"] == 0
