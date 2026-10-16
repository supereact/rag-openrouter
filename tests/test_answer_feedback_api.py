from fastapi.testclient import TestClient
from app import main, security
from app.security import Principal

USER = Principal(3, 1, 'reader', 'user')
ADMIN = Principal(1, 1, 'admin', 'admin')


def _client(monkeypatch):
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    return TestClient(main.app)


def test_feedback_routes_require_auth(monkeypatch):
    main.app.dependency_overrides.clear()
    with _client(monkeypatch) as c:
        assert c.get('/conversations/10/feedback').status_code == 401
        assert c.put('/conversations/10/messages/15/feedback',json={'rating':'up'}).status_code == 401
        assert c.get('/admin/feedback').status_code == 401


def test_feedback_put_and_delete_calls_owner_scoped_service(monkeypatch):
    main.app.dependency_overrides[security.require_principal] = lambda: USER
    calls=[]
    monkeypatch.setattr(main.answer_feedback,'save_feedback',lambda p,c,m,r,reason: (
        calls.append(('put',p.tenant_id,p.user_id,c,m,r,reason)) or {'message_id':m,'rating':r,'reason':reason}))
    monkeypatch.setattr(main.answer_feedback,'remove_feedback',lambda p,c,m: calls.append(('delete',p.user_id,c,m)))
    try:
        with _client(monkeypatch) as c:
            assert c.put('/conversations/10/messages/15/feedback',json={'rating':'down','reason':'incorrect'}).status_code == 200
            assert c.delete('/conversations/10/messages/15/feedback').status_code == 204
    finally: main.app.dependency_overrides.clear()
    assert calls[:2] == [('put',1,3,10,15,'down','incorrect'),('delete',3,10,15)]


def test_admin_api_is_restricted(monkeypatch):
    main.app.dependency_overrides[security.require_principal] = lambda: USER
    def admin_stats(p,days):
        if p.role!='admin':
            from fastapi import HTTPException
            raise HTTPException(403,'Admin access required')
        return {'scope':'tenant'}
    monkeypatch.setattr(main.answer_feedback,'admin_quality',admin_stats)
    try:
        with _client(monkeypatch) as c:
            assert c.get('/admin/feedback').status_code == 403
        main.app.dependency_overrides[security.require_principal] = lambda: ADMIN
        with _client(monkeypatch) as c:
            assert c.get('/admin/feedback?days=30').json()['scope']=='tenant'
    finally: main.app.dependency_overrides.clear()
