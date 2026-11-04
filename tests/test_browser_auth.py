"""Cookie sessions, CSRF, and legacy bearer compatibility; no real database."""
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from fastapi.middleware.cors import CORSMiddleware

from app import account_auth, browser_auth, main, security
from app.security import key_digest

TOKEN = 'rags_' + 'x' * 40
API_KEY = 'rag_' + 'k' * 40
HEADERS = {'X-RAG-CSRF': '1', 'Origin': 'http://localhost:5173'}
IDENTITY = {'user_id': 2, 'tenant_id': 7, 'role': 'editor', 'username': 'writer'}
BODY = {'email': 'user@example.org', 'password': 'synthetic-password-123'}

FRONTEND = 'https://app.example.com'
DIRECT_HEADERS = {'X-RAG-CSRF': '1', 'Origin': FRONTEND, 'Sec-Fetch-Site': 'same-site'}


@pytest.fixture
def split_client(state, monkeypatch):
    monkeypatch.setattr(browser_auth.settings, 'RAG_ALLOWED_ORIGINS', FRONTEND)
    wrapped = CORSMiddleware(main.app, **browser_auth.cors_options())
    with TestClient(wrapped, base_url='https://api.example.com') as client:
        yield client


def test_direct_frontend_preflight_login_restore_and_logout(split_client, state):
    response = split_client.options('/auth/browser/login', headers={
        'Origin': FRONTEND, 'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'content-type,x-rag-csrf'})
    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == FRONTEND
    assert response.headers['access-control-allow-credentials'] == 'true'
    assert 'Origin' in response.headers['vary']
    assert not state['calls']
    response = split_client.post('/auth/browser/login', json=BODY, headers=DIRECT_HEADERS)
    assert response.status_code == 200
    cookie = response.headers['set-cookie']
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=strict' in cookie
    assert 'Domain=' not in cookie
    assert TOKEN not in response.text
    response = split_client.get('/auth/session', headers=DIRECT_HEADERS)
    assert response.json() == IDENTITY
    assert response.headers['access-control-allow-origin'] == FRONTEND
    assert response.headers['cache-control'] == 'no-store'
    assert split_client.post('/auth/browser/logout', headers=DIRECT_HEADERS).status_code == 204
    assert state['revoked']


@pytest.mark.parametrize('origin', ['https://evil.example.com', 'https://app.example.com.attacker.test', 'null'])
def test_unlisted_siblings_and_spoofed_origins_cannot_read_or_write(split_client, state, origin):
    response = split_client.options('/auth/browser/login', headers={
        'Origin': origin, 'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'content-type,x-rag-csrf'})
    assert response.status_code == 400
    assert 'access-control-allow-origin' not in response.headers
    response = split_client.post('/auth/browser/login', json=BODY,
        headers={**DIRECT_HEADERS, 'Origin': origin})
    assert response.status_code == 403
    account_auth.login.assert_not_called()
    assert not state['calls']


def test_direct_requests_keep_csrf_requirement_and_cross_site_cookie_rejection(split_client, state):
    for headers in ({'Origin': FRONTEND, 'Sec-Fetch-Site': 'same-site'},
                    {**DIRECT_HEADERS, 'Sec-Fetch-Site': 'cross-site'},
                    {'X-RAG-CSRF': '1', 'Sec-Fetch-Site': 'same-site'}):
        assert split_client.post('/auth/browser/login', json=BODY, headers=headers).status_code == 403
    account_auth.login.assert_not_called()
    assert not state['calls']


def test_direct_multipart_and_bearer_auth_preserve_server_identity(split_client, state, monkeypatch):
    split_client.post('/auth/browser/login', json=BODY, headers=DIRECT_HEADERS)
    seen = []
    monkeypatch.setattr(main, 'queue_upload', lambda name, data, principal:
        (seen.append(principal) or dict(id='11111111-1111-4111-8111-111111111111', filename=name,
                                       status='queued', created_at='2026-10-22T00:00:00Z')))
    response = split_client.post('/documents/upload-async', files={'file': ('policy.md', b'synthetic')}, headers=DIRECT_HEADERS)
    assert response.status_code == 202
    assert seen[0].tenant_id == IDENTITY['tenant_id']
    assert seen[0].role == 'editor'
    response = split_client.get('/me', headers={'Origin': FRONTEND, 'Authorization': f'Bearer {API_KEY}'})
    assert response.json()['tenant_id'] == 9  # Explicit bearer still overrides cookie.
    response = split_client.get('/me', headers={'Origin': FRONTEND, 'Authorization': 'Bearer invalid'})
    assert response.status_code == 401
    assert response.headers['access-control-allow-origin'] == FRONTEND


@pytest.mark.parametrize('value', ['*', 'https://*.example.com', 'https://app.example.com/path',
    'https://user:secret@app.example.com', 'https://app.example.com?query=yes',
    'https://app.example.com#fragment', 'http://app.example.com', 'null',
    'https://app.example.com:99999'])
def test_origin_configuration_rejects_unsafe_values(monkeypatch, value):
    monkeypatch.setattr(browser_auth.settings, 'RAG_ALLOWED_ORIGINS', value)
    with pytest.raises(ValueError, match='RAG_ALLOWED_ORIGINS'):
        browser_auth.allowed_origins()


def test_origin_configuration_accepts_explicit_https_and_loopback(monkeypatch):
    monkeypatch.setattr(browser_auth.settings, 'RAG_ALLOWED_ORIGINS',
        f'{FRONTEND}/, http://127.0.0.1:5173, {FRONTEND},http://localhost:5173')
    assert browser_auth.allowed_origins() == [FRONTEND, 'http://127.0.0.1:5173', 'http://localhost:5173']


@pytest.fixture
def state(monkeypatch):
    monkeypatch.setattr(browser_auth.settings, 'RAG_ALLOWED_ORIGINS', '')
    state = {'active': True, 'revoked': False, 'expired': False, 'role': 'editor', 'calls': []}
    class Connection:
        def execute(self, sql, args):
            state['calls'].append((sql, args))
            self.sql, self.args = sql, args
            return self

        def fetchone(self):
            assert 'u.is_active' in self.sql
            if self.args == (key_digest(API_KEY),) and 'FROM api_keys' in self.sql:
                return 8, 9, 'reader', 'api-user'
            assert 's.expires_at>now()' in self.sql
            assert 's.revoked_at IS NULL' in self.sql
            if (self.args == (key_digest(TOKEN),) and state['active'] and
                    not state['revoked'] and not state['expired']):
                return 2, 7, state['role'], 'writer'
            return None
    @contextmanager
    def connect():
        yield Connection()
    monkeypatch.setattr(security, 'db_connection', connect)
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    monkeypatch.setattr(main.app, 'dependency_overrides', {})
    monkeypatch.setattr(account_auth, 'registration_throttle', account_auth.LoginThrottle())
    monkeypatch.setattr(account_auth, 'login', Mock(return_value={
        'access_token': TOKEN, 'token_type': 'bearer', 'expires_in': 43200}))
    monkeypatch.setattr(account_auth, 'register', Mock(return_value={
        'access_token': TOKEN, 'token_type': 'bearer', 'expires_in': 43200}))
    def revoke(token):
        assert token == TOKEN
        state['revoked'] = True
    monkeypatch.setattr(account_auth, 'logout', Mock(side_effect=revoke))
    return state


@pytest.fixture
def client(state):
    with TestClient(main.app, base_url='http://localhost:5173') as client:
        yield client


@pytest.mark.parametrize('method,path', [
    ('GET', '/me'), ('GET', '/health'), ('GET', '/openapi.json'),
    ('POST', '/auth/login'), ('POST', '/documents/upload-async'),
    ('DELETE', '/documents/1'), ('OPTIONS', '/auth/login'),
])
@pytest.mark.parametrize('headers', [
    {'Origin': 'https://attacker.example'},
    {'Origin': 'http://localhost:5173.attacker.example'},
    {'Origin': 'null'},
    {'Sec-Fetch-Site': 'cross-site'},
    {'Origin': 'http://localhost:5173', 'Sec-Fetch-Site': 'cross-site'},
])
def test_cross_site_requests_rejected_before_handlers(client, state, method, path, headers):
    response = client.request(method, path, headers={
        **headers, 'Authorization': f'Bearer {API_KEY}'})
    assert response.status_code == 403
    assert response.json()['detail'] == 'Cross-site access forbidden'
    assert 'access-control-allow-origin' not in response.headers
    assert 'x-request-id' in response.headers
    account_auth.login.assert_not_called()
    assert not state['calls']


def test_cross_site_preflight_rejected_by_actual_app(client):
    response = client.options('/auth/login', headers={
        'Origin': 'https://attacker.example',
        'Access-Control-Request-Method': 'POST'})
    assert response.status_code == 403
    assert 'access-control-allow-origin' not in response.headers


def test_browser_login_cookie_only_identity_and_refresh_restoration(client):
    response = client.post('/auth/browser/login', json=BODY, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == IDENTITY
    assert TOKEN not in response.text
    cookie = response.headers['set-cookie']
    for flag in ('HttpOnly', 'SameSite=strict', 'Max-Age=43200', 'Path=/'):
        assert flag in cookie
    assert 'Domain=' not in cookie
    assert 'Secure' not in cookie  # localhost HTTP exception only
    assert response.headers['cache-control'] == 'no-store'
    # Simulated fresh frontend knows no token: identity and APIs use the cookie.
    assert client.get('/auth/session', headers=HEADERS).json() == IDENTITY
    assert client.get('/me').json() == IDENTITY
    assert client.get('/auth/session', headers=HEADERS).headers.get('set-cookie') is None


def test_signup_uses_cookie_and_keeps_invitation_errors(client):
    body = {**BODY, 'username': 'new-user', 'invitation_code': 'invite_' + 'a' * 40}
    response = client.post('/auth/browser/register', json=body, headers=HEADERS)
    assert response.status_code == 201
    assert response.json() == IDENTITY
    assert 'HttpOnly' in response.headers['set-cookie']
    account_auth.register.side_effect = ValueError('Invalid or expired invitation')
    assert client.post('/auth/browser/register', json=body, headers=HEADERS).status_code == 400


def test_https_cookie_is_secure_and_non_loopback_http_login_fails(state):
    with TestClient(main.app, base_url='https://workspace.example') as client:
        response = client.post('/auth/browser/login', json=BODY, headers={
            'X-RAG-CSRF': '1', 'Origin': 'https://workspace.example'})
        assert response.status_code == 200
        assert 'Secure' in response.headers['set-cookie']
        assert client.get('/me').json() == IDENTITY
    account_auth.login.reset_mock()
    with TestClient(main.app, base_url='http://workspace.example') as client:
        assert client.post('/auth/browser/login', json=BODY, headers={
            'X-RAG-CSRF': '1', 'Origin': 'http://workspace.example'}).status_code == 400
    account_auth.login.assert_not_called()


@pytest.mark.parametrize('headers', [
    {}, {'Origin': 'http://localhost:5173'}, {'X-RAG-CSRF': '0'},
    {'X-RAG-CSRF': '1', 'Origin': 'https://attacker.example'},
    {'X-RAG-CSRF': '1', 'Origin': 'null'},
    {'X-RAG-CSRF': '1', 'Sec-Fetch-Site': 'same-site'},
    {'X-RAG-CSRF': '1', 'Sec-Fetch-Site': 'cross-site'},
])
def test_csrf_rejected_before_login_or_cookie_writes(client, headers, state, monkeypatch):
    assert client.post('/auth/browser/login', json=BODY, headers=headers).status_code == 403
    account_auth.login.assert_not_called()
    client.cookies.set(browser_auth.COOKIE_NAME, TOKEN)
    # Includes multipart write routes, not just JSON APIs.
    for path in ('/auth/browser/logout', '/auth/logout', '/documents/upload-async'):
        assert client.post(path, headers=headers).status_code == 403
    assert client.get('/auth/session', headers=headers).status_code == 403
    assert not state['calls']
    account_auth.logout.assert_not_called()


def test_cookie_authorization_retains_writer_and_tenant_identity(client, state, monkeypatch):
    client.cookies.set(browser_auth.COOKIE_NAME, TOKEN)
    seen = []
    monkeypatch.setattr(main, 'queue_upload', lambda name, data, principal:
                        (seen.append(principal) or {'id': '11111111-1111-4111-8111-111111111111',
                            'filename': name, 'status': 'queued', 'created_at': '2026-10-17T00:00:00Z'}))
    response = client.post('/documents/upload-async', files={'file': ('policy.md', b'synthetic')}, headers=HEADERS)
    assert response.status_code == 202
    assert (seen[0].user_id, seen[0].tenant_id, seen[0].role) == (2, 7, 'editor')
    state['role'] = 'reader'
    assert client.post('/documents/upload-async', files={'file': ('policy.md', b'synthetic')}, headers=HEADERS).status_code == 403
    assert client.get('/admin/dashboard').status_code == 403


@pytest.mark.parametrize('flag', ['expired', 'revoked', 'active'])
def test_expired_revoked_or_deactivated_sessions_cannot_restore_or_access(client, state, flag):
    client.cookies.set(browser_auth.COOKIE_NAME, TOKEN)
    state[flag] = flag != 'active'
    assert client.get('/me').status_code == 401
    response = client.get('/auth/session', headers=HEADERS)
    assert response.status_code == 401
    assert 'set-cookie' not in response.headers
    assert response.headers['cache-control'] == 'no-store'


def test_logout_revokes_and_clears_cookie_and_is_idempotent(client, state):
    client.post('/auth/browser/login', json=BODY, headers=HEADERS)
    response = client.post('/auth/browser/logout', headers=HEADERS)
    assert response.status_code == 204
    assert state['revoked'] is True
    assert 'Max-Age=0' in response.headers['set-cookie']
    assert client.get('/me').status_code == 401
    assert client.post('/auth/browser/logout', headers=HEADERS).status_code == 204


def test_existing_logout_also_revokes_cookie_session(client, state):
    client.post('/auth/browser/login', json=BODY, headers=HEADERS)
    response = client.post('/auth/logout', headers=HEADERS)
    assert response.status_code == 204 and state['revoked']
    assert 'Max-Age=0' in response.headers['set-cookie']


def test_failed_logout_does_not_clear_cookie_or_claim_success(client):
    client.cookies.set(browser_auth.COOKIE_NAME, TOKEN)
    account_auth.logout.side_effect = RuntimeError('Synthetic DB failure')
    with pytest.raises(RuntimeError, match='Synthetic DB failure'):
        client.post('/auth/browser/logout', headers=HEADERS)
    assert client.cookies.get(browser_auth.COOKIE_NAME) == TOKEN


def test_bearer_precedence_and_legacy_contracts(client):
    client.cookies.set(browser_auth.COOKIE_NAME, TOKEN)
    assert client.get('/me', headers={'Authorization': f'Bearer {API_KEY}'}).json()['tenant_id'] == 9
    assert client.get('/me', headers={'Authorization': 'Bearer invalid'}).status_code == 401
    assert client.get('/me', headers={'Authorization': 'Basic invalid'}).status_code == 401
    assert client.get('/me', headers={'Authorization': 'Bearer'}).status_code == 401
    # Legacy programmatic clients still receive the original bearer contract.
    result = client.post('/auth/login', json=BODY)
    assert result.json()['access_token'] == TOKEN
    assert 'set-cookie' not in result.headers
    client.cookies.clear()
    client.cookies.set(browser_auth.COOKIE_NAME, API_KEY)
    assert client.get('/me').status_code == 401
    assert client.get('/auth/session', headers=HEADERS).status_code == 401
