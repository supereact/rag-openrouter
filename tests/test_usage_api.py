"""Endpoint permission boundary and OpenRouter usage capture on /ask."""
import pytest
from fastapi.testclient import TestClient

from app import main, security, settings, observability
from app.security import Principal

ADMIN = Principal(1, 51, 'admin', 'admin')
READER = Principal(2, 51, 'reader', 'reader')


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    main.app.dependency_overrides.clear()
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


def test_admin_usage_authentication(client, monkeypatch):
    assert client.get('/admin/usage').status_code == 401
    main.app.dependency_overrides[security.require_principal] = lambda: READER
    assert client.get('/admin/usage').status_code == 403
    main.app.dependency_overrides[security.require_principal] = lambda: ADMIN
    ids = []
    monkeypatch.setattr(main.usage_ledger, 'get_usage_dashboard', lambda principal, days: (ids.append((principal.tenant_id, days)) or {'overall_credits': '0.1', 'users': []}))
    assert client.get('/admin/usage?days=7').json()['overall_credits'] == '0.1'
    assert ids == [(51, 7)]
    assert client.get('/admin/usage?days=365').status_code == 422


def test_ask_logs_usage_only_for_openrouter(client, monkeypatch):
    main.app.dependency_overrides[security.require_principal] = lambda: ADMIN
    monkeypatch.setattr(settings, 'LLM_PROVIDER', 'openrouter')
    monkeypatch.setattr(settings, 'OPENROUTER_MODEL', 'test-model')
    monkeypatch.setattr(main.credit_budgets, 'reserve_request', lambda principal: None)
    monkeypatch.setattr(main, 'search_documents', lambda *args, **kw: [])
    def mock_answer(question, hits):
        observability.capture_llm_usage({'cost': 0.0002, 'prompt_tokens': 12, 'completion_tokens': 5}, provider='openrouter')
        return 'Response [1]'
    monkeypatch.setattr(main, 'answer_question', mock_answer)
    stored = []
    monkeypatch.setattr(main.usage_ledger, 'record_openrouter_usage', lambda p, model, usage: stored.append((p.user_id, p.tenant_id, model, dict(usage))))
    response = client.post('/ask', json={'question':'test','top_k':1})
    assert response.status_code == 200
    assert stored == [(1, 51, 'test-model', {'prompt_tokens': 12, 'completion_tokens': 5, 'provider_cost_credits': 0.0002})]


def test_direct_openai_not_added_to_openrouter_ledger(client, monkeypatch):
    main.app.dependency_overrides[security.require_principal] = lambda: ADMIN
    monkeypatch.setattr(settings, 'LLM_PROVIDER', 'openai')
    monkeypatch.setattr(main.credit_budgets, 'reserve_request', lambda principal: None)
    monkeypatch.setattr(main, 'search_documents', lambda *args, **kw: [])
    def mock_answer(*args):
        observability.capture_llm_usage({'input_tokens': 12}, provider='openai')
        return 'Response'
    monkeypatch.setattr(main, 'answer_question', mock_answer)
    monkeypatch.setattr(main.usage_ledger, 'record_openrouter_usage', lambda *args: (_ for _ in ()).throw(AssertionError('incorrect provider')))
    assert client.post('/ask', json={'question':'test','top_k':1}).status_code == 200
