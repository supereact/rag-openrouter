"""Admin-only budget endpoints and allowance checks before calling OpenRouter."""
from fastapi.testclient import TestClient
from app import main, settings, security
from app.security import Principal

ADMIN = Principal(1,12,'admin','admin')
READER = Principal(2,12,'reader','reader')


def _client(monkeypatch):
    monkeypatch.setattr(main, 'warmup_local_models', lambda:None)
    return TestClient(main.app)


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
    monkeypatch.setattr(main,'search_documents',lambda *a,**k:[])
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
