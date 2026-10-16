"""FastAPI behavior tests for tenant-scoped collection filters and budgets."""
import pytest
pytest.importorskip('psycopg')
pytest.importorskip('pgvector')

from fastapi import HTTPException
from fastapi.testclient import TestClient
from app import main, security
from app.security import Principal

EDITOR = Principal(2, 10, 'editor', 'editor')
READER = Principal(3, 10, 'reader', 'reader')


def client(monkeypatch):
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    return TestClient(main.app)


def test_collections_need_authentication(monkeypatch):
    main.app.dependency_overrides.clear()
    with client(monkeypatch) as c:
        assert c.get('/knowledge-bases').status_code == 401
        assert c.post('/knowledge-bases', json={'name':'IT Support'}).status_code == 401


def test_reader_cannot_create_collection(monkeypatch):
    main.app.dependency_overrides[security.require_principal] = lambda: READER
    try:
        with client(monkeypatch) as c:
            assert c.post('/knowledge-bases', json={'name':'IT Support'}).status_code == 403
    finally:
        main.app.dependency_overrides.clear()


def test_invalid_collection_does_not_spend_budget(monkeypatch):
    main.app.dependency_overrides[security.require_principal] = lambda: READER
    monkeypatch.setattr(main.knowledge_bases, 'assert_tenant_collection',
                        lambda *_: (_ for _ in ()).throw(HTTPException(status_code=404, detail='Not found')))
    monkeypatch.setattr(main.credit_budgets, 'reserve_request',
                        lambda *_: (_ for _ in ()).throw(AssertionError('Spent credits')))
    try:
        with client(monkeypatch) as c:
            direct = c.post('/ask', json={'question':'What is backup?', 'knowledge_base_id':123})
            assert direct.status_code == 404
    finally:
        main.app.dependency_overrides.clear()


def test_forward_collection_to_search(monkeypatch):
    main.app.dependency_overrides[security.require_principal] = lambda: READER
    received=[]
    monkeypatch.setattr(main,'search_documents',lambda question,top_k,**kwargs:(received.append(kwargs) or []))
    monkeypatch.setattr(main, 'measure', lambda *_: __import__('contextlib').nullcontext())
    try:
        with client(monkeypatch) as c:
            resp=c.post('/search',json={'question':'Is VPN up?', 'top_k':5, 'knowledge_base_id':9})
            assert resp.status_code==200
            assert received[0]['knowledge_base_id']==9
    finally:
        main.app.dependency_overrides.clear()
