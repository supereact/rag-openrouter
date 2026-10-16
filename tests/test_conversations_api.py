"""Route-level regression tests; no external PostgreSQL or OpenRouter required."""
from fastapi.testclient import TestClient
from fastapi import HTTPException
from app import main, security
from app.security import Principal

OWNER = Principal(3, 1, 'reader', 'owner')
OUTSIDER = Principal(4, 2, 'admin', 'outside-admin')


def _client(monkeypatch):
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    return TestClient(main.app)


def test_routes_require_login(monkeypatch):
    main.app.dependency_overrides.clear()
    with _client(monkeypatch) as c:
        assert c.get('/conversations').status_code == 401
        assert c.post('/conversations', json={'title':'Test'}).status_code == 401
        assert c.get('/conversations/7').status_code == 401
        assert c.post('/conversations/7/ask', json={'question':'Question'}).status_code == 401


def test_owner_identity_is_passed_to_storage(monkeypatch):
    main.app.dependency_overrides[security.require_principal] = lambda: OWNER
    calls=[]
    monkeypatch.setattr(main.conversations,'list_conversations',lambda p:(calls.append(('list',p.user_id,p.tenant_id)) or []))
    monkeypatch.setattr(main.conversations,'create_conversation',lambda p,t:(calls.append(('create',p.user_id,p.tenant_id,t)) or {'id':3,'title':t}))
    try:
        with _client(monkeypatch) as c:
            assert c.get('/conversations').status_code==200
            assert c.post('/conversations',json={'title':'Policy'}).status_code==201
    finally:
        main.app.dependency_overrides.clear()
    assert calls == [('list',3,1),('create',3,1,'Policy')]


def test_unauthorized_conversation_blocks_llm_and_credit_usage(monkeypatch):
    main.app.dependency_overrides[security.require_principal] = lambda: OUTSIDER
    monkeypatch.setattr(main.conversations,'assert_owned',lambda *a:(_ for _ in ()).throw(HTTPException(404,'Conversation not found')))
    monkeypatch.setattr(main,'_run_ask',lambda *a:(_ for _ in ()).throw(AssertionError('Paid request reached')))
    try:
        with _client(monkeypatch) as c:
            assert c.post('/conversations/7/ask',json={'question':'Question here','top_k':5}).status_code==404
    finally: main.app.dependency_overrides.clear()


def test_saved_chat_uses_original_budgeted_ask_path(monkeypatch):
    main.app.dependency_overrides[security.require_principal] = lambda: OWNER
    seen=[]
    monkeypatch.setattr(main.conversations,'assert_owned',lambda p,c:seen.append(('auth',p.user_id,c)))
    monkeypatch.setattr(main,'_run_ask',lambda body,p:(seen.append(('ask',p.user_id)) or main.AskResponse(question=body.question,answer='Grounded',sources=[])))
    monkeypatch.setattr(main.conversations,'append_exchange',lambda p,c,q,a,s:(seen.append(('saved',p.user_id,c)) or 22))
    try:
        with _client(monkeypatch) as c:
            result=c.post('/conversations/7/ask',json={'question':'What is recovery?','top_k':4})
            assert result.status_code==200 and result.json()['message_id']==22
    finally: main.app.dependency_overrides.clear()
    assert seen == [('auth',3,7),('ask',3),('saved',3,7)]
