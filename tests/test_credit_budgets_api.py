"""Admin-only budget endpoints and allowance checks before calling OpenRouter."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from app import main, settings, security, services, observability
from app.schemas import SearchHit
from app.security import Principal

ADMIN = Principal(1,12,'admin','admin')
READER = Principal(2,12,'reader','reader')
SOURCES = [SearchHit(
    source_number=1, document_id=11, title='Synthetic policy', chunk_index=0,
    content='Synthetic evidence for a test answer.', similarity=0.9,
)]


def _client(monkeypatch):
    monkeypatch.setattr(main, 'warmup_local_models', lambda:None)
    return TestClient(main.app)


@pytest.fixture
def ask_dependencies(monkeypatch):
    """Exercise the real ask/answer path without database or provider calls."""
    monkeypatch.setitem(main.app.dependency_overrides, security.require_principal, lambda: READER)
    monkeypatch.setattr(settings, 'LLM_PROVIDER', 'openrouter')
    monkeypatch.setattr(settings, 'OPENROUTER_MODEL', 'test/model')
    calls = SimpleNamespace(
        reserve=Mock(return_value='hold'), release=Mock(),
        settle=Mock(return_value='unknown'), record=Mock(),
        search=Mock(return_value=[]), provider=Mock(return_value='Grounded answer [1].'),
        owned=Mock(), append=Mock(return_value=22),
    )
    monkeypatch.setattr(main.credit_budgets, 'reserve_request', calls.reserve)
    monkeypatch.setattr(main.credit_budgets, 'release_before_generation', calls.release)
    monkeypatch.setattr(main.credit_budgets, 'settle_request', calls.settle)
    monkeypatch.setattr(main.usage_ledger, 'record_openrouter_usage', calls.record)
    monkeypatch.setattr(main, 'search_documents', calls.search)
    monkeypatch.setattr(services, 'generate_grounded_answer', calls.provider)
    monkeypatch.setattr(main.conversations, 'assert_owned', calls.owned)
    monkeypatch.setattr(main.conversations, 'append_exchange', calls.append)
    with _client(monkeypatch) as client:
        yield client, calls


@pytest.mark.parametrize('path', ['/ask', '/conversations/7/ask'])
def test_empty_sources_release_unused_reservation(ask_dependencies, path):
    client, calls = ask_dependencies
    question = 'Synthetic inspection question?'
    response = client.post(path, json={'question': question, 'top_k': 1})
    assert response.status_code == 200
    expected = {
        'question': question,
        'answer': 'No indexed sources are available to answer that question.',
        'sources': [],
    }
    if path != '/ask':
        expected['message_id'] = 22
        calls.owned.assert_called_once_with(READER, 7)
        calls.append.assert_called_once_with(READER, 7, question, expected['answer'], [])
    else:
        calls.append.assert_not_called()
    assert response.json() == expected
    calls.reserve.assert_called_once_with(READER)
    calls.release.assert_called_once_with('hold', READER)
    calls.provider.assert_not_called()
    calls.settle.assert_not_called()
    calls.record.assert_not_called()


@pytest.mark.parametrize('path', ['/ask', '/conversations/7/ask'])
@pytest.mark.parametrize('outcome', ['missing_cost', 'missing_usage', 'generation_failure'])
def test_attempted_generation_keeps_unknown_cost_hold(ask_dependencies, path, outcome):
    client, calls = ask_dependencies
    calls.search.return_value = SOURCES
    expected_usage = None
    if outcome == 'missing_cost':
        def generate(question, context):
            observability.capture_llm_usage({'prompt_tokens': 9, 'completion_tokens': 2}, provider='openrouter')
            return 'Grounded answer [1].'
        calls.provider.side_effect = generate
        expected_usage = {'prompt_tokens': 9, 'completion_tokens': 2}
    elif outcome == 'generation_failure':
        calls.provider.side_effect = RuntimeError('Synthetic provider failure')

    response = client.post(path, json={'question': 'Synthetic question?', 'top_k': 1})
    assert response.status_code == (503 if outcome == 'generation_failure' else 200)
    calls.provider.assert_called_once()
    calls.release.assert_not_called()
    calls.settle.assert_called_once_with('hold', READER, 'test/model', expected_usage)
    calls.record.assert_not_called()
    if outcome == 'generation_failure' or path == '/ask':
        calls.append.assert_not_called()
    else:
        assert response.json()['message_id'] == 22


def test_budget_admin_only(monkeypatch):
    main.app.dependency_overrides.clear()
    with _client(monkeypatch) as client:
        assert client.get('/admin/budgets').status_code == 401
        main.app.dependency_overrides[security.require_principal]=lambda:READER
        assert client.get('/admin/budgets').status_code == 403
        assert client.put('/admin/budgets/tenant',json={'monthly_limit_credits':'1'}).status_code == 403
        assert client.put('/admin/budgets/users/1',json={'paused':True}).status_code == 403
    main.app.dependency_overrides.clear()


def test_budget_api_scoped_to_principal(monkeypatch):
    main.app.dependency_overrides[security.require_principal]=lambda:ADMIN
    seen=[]
    monkeypatch.setattr(main.credit_budgets,'get_budget_dashboard',lambda p:(seen.append(('get',p.tenant_id)) or {'users':[]}))
    monkeypatch.setattr(main.credit_budgets,'update_tenant_budget',lambda p,cap,paused,reserve:seen.append(('tenant',p.tenant_id,cap,paused,reserve)))
    monkeypatch.setattr(main.credit_budgets,'update_user_budget',lambda p,user,cap,paused:seen.append(('user',p.tenant_id,user,cap,paused)))
    try:
        with _client(monkeypatch) as client:
            assert client.get('/admin/budgets').status_code==200
            assert client.put('/admin/budgets/tenant',json={'monthly_limit_credits':'2.5','paused':False,'reservation_credits':'0.01'}).status_code==200
            assert client.put('/admin/budgets/users/3',json={'monthly_limit_credits':'1','paused':True}).status_code==200
    finally: main.app.dependency_overrides.clear()
    assert ('tenant',12,'2.5',False,'0.01') in seen
    assert ('user',12,3,'1',True) in seen


def test_budget_rejection_makes_no_llm_calls(monkeypatch):
    main.app.dependency_overrides[security.require_principal] = lambda: READER
    monkeypatch.setattr(settings,'LLM_PROVIDER','openrouter')
    def blocked(principal):
        from fastapi import HTTPException
        raise HTTPException(429,'budget reached')
    monkeypatch.setattr(main.credit_budgets,'reserve_request',blocked)
    monkeypatch.setattr(main,'search_documents',lambda *a,**k: (_ for _ in ()).throw(AssertionError('retrieval ran')))
    monkeypatch.setattr(main,'answer_question',lambda *a,**k: (_ for _ in ()).throw(AssertionError('llm ran')))
    try:
        with _client(monkeypatch) as client:
            r=client.post('/ask',json={'question':'test','top_k':2})
            assert r.status_code==429
    finally: main.app.dependency_overrides.clear()


def test_paid_call_settles_before_return(monkeypatch):
    main.app.dependency_overrides[security.require_principal] = lambda: ADMIN
    monkeypatch.setattr(settings,'LLM_PROVIDER','openrouter')
    monkeypatch.setattr(main.credit_budgets,'reserve_request',lambda p:'reservation')
    monkeypatch.setattr(main,'search_documents',lambda *a,**k:SOURCES)
    monkeypatch.setattr(main,'answer_question',lambda *a,**k:'Answer')
    called=[]
    monkeypatch.setattr(main.credit_budgets,'settle_request',lambda rid,p,m,u:called.append((rid,p.user_id)))
    try:
        with _client(monkeypatch) as client:
            assert client.post('/ask',json={'question':'test','top_k':2}).status_code==200
    finally: main.app.dependency_overrides.clear()
    assert called==[('reservation',1)]


def test_failed_retrieval_releases_hold(monkeypatch):
    main.app.dependency_overrides[security.require_principal] = lambda: ADMIN
    monkeypatch.setattr(settings,'LLM_PROVIDER','openrouter')
    monkeypatch.setattr(main.credit_budgets,'reserve_request',lambda p:'hold')
    monkeypatch.setattr(main,'search_documents',lambda *a,**k: (_ for _ in ()).throw(RuntimeError('search unavailable')))
    monkeypatch.setattr(main.credit_budgets,'settle_request',lambda *a,**k: (_ for _ in ()).throw(AssertionError('Must not settle unknown')))
    released=[]
    monkeypatch.setattr(main.credit_budgets,'release_before_generation',lambda rid,p:released.append((rid,p.user_id)))
    try:
        with _client(monkeypatch) as client:
            assert client.post('/ask',json={'question':'test','top_k':2}).status_code==503
    finally: main.app.dependency_overrides.clear()
    assert released==[('hold',1)]
