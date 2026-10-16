"""Auth routes fail closed and admin routes enforce tenant-admin role."""
from fastapi.testclient import TestClient
from app import main, security
from app.security import Principal

READER = Principal(2,1,'reader','reader')
ADMIN = Principal(1,1,'admin','admin')


def _client(monkeypatch):
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    return TestClient(main.app)


def test_admin_routes_need_auth(monkeypatch):
    main.app.dependency_overrides.clear()
    with _client(monkeypatch) as client:
        assert client.get('/admin/users').status_code == 401
        assert client.get('/admin/dashboard').status_code == 401
        assert client.post('/admin/invitations',json={'email':'a@example.com','role':'reader'}).status_code == 401


def test_reader_cannot_use_admin_routes(monkeypatch):
    main.app.dependency_overrides[security.require_principal] = lambda: READER
    try:
        with _client(monkeypatch) as client:
            assert client.get('/admin/users').status_code == 403
            assert client.get('/admin/dashboard').status_code == 403
            assert client.post('/admin/invitations',json={'email':'a@example.com','role':'reader'}).status_code == 403
            assert client.patch('/admin/users/5',json={'role':'admin'}).status_code == 403
    finally:
        main.app.dependency_overrides.clear()


def test_public_login_does_not_require_existing_key(monkeypatch):
    main.app.dependency_overrides.clear()
    monkeypatch.setattr(main.account_auth, 'login', lambda email,password,ip: {
        'access_token':'rags_test', 'token_type':'bearer', 'expires_in':43200})
    with _client(monkeypatch) as client:
        r = client.post('/auth/login',json={'email':'person@example.com','password':'longpassword'})
        assert r.status_code == 200
        assert r.json()['token_type']=='bearer'


def test_admin_dashboard_uses_principal_tenant(monkeypatch):
    main.app.dependency_overrides[security.require_principal] = lambda: ADMIN
    seen=[]
    monkeypatch.setattr(main.account_auth,'dashboard',lambda p: (seen.append(p.tenant_id) or {'users_total':2}))
    try:
        with _client(monkeypatch) as client:
            r=client.get('/admin/dashboard')
            assert r.status_code==200 and r.json()['users_total']==2
            assert seen==[1]
    finally:
        main.app.dependency_overrides.clear()
