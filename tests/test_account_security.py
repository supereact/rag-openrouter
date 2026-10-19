"""Self-service controls against a temporary relational fixture; no live data."""
from contextlib import contextmanager
import sqlite3
from threading import Event, Lock, Thread

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app import account_auth, account_security as service, main, security
from app.security import Principal, key_digest

USER = Principal(2, 7, 'reader', 'reader')
STAFF = Principal(10, 99, 'admin', 'support')
CURRENT = 'rags_' + 's' * 40
OTHER = 'rags_' + 'o' * 40
FOREIGN = 'rags_' + 'f' * 40
API_KEY = 'rag_' + 'k' * 40
STAFF_KEY = 'rag_' + 'a' * 40
PASSWORD = 'old-password-for-tests'
NEW_PASSWORD = 'new-password-for-tests'


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:', check_same_thread=False)
        self.calls = []
        self.fail_audit = False
        self.conn.executescript('''
          PRAGMA foreign_keys=ON;
          CREATE TABLE tenants(id INTEGER PRIMARY KEY);
          INSERT INTO tenants VALUES(7),(8),(99);
          CREATE TABLE app_users(id INTEGER PRIMARY KEY,tenant_id INTEGER,username TEXT,
            role TEXT,email TEXT,password_hash TEXT,is_active BOOLEAN);
          CREATE TABLE login_sessions(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES app_users(id),
            token_hash TEXT UNIQUE,created_at TEXT DEFAULT '2026-10-19 00:00:00+00:00',
            expires_at TEXT,revoked_at TEXT);
          CREATE TABLE api_keys(id INTEGER PRIMARY KEY,user_id INTEGER,key_hash TEXT,revoked_at TEXT);
          CREATE TABLE audit_events(tenant_id INTEGER,user_id INTEGER,action TEXT);
        ''')
        encoded = account_auth.hash_password(PASSWORD)
        self.conn.executemany('INSERT INTO app_users VALUES(?,?,?,?,?,?,?)', [
            (2, 7, 'reader', 'reader', 'reader@example.org', encoded, True),
            (3, 7, 'neighbor', 'admin', 'neighbor@example.org', encoded, True),
            (9, 8, 'outside', 'reader', 'outside@example.org', encoded, True),
            (10, 99, 'support', 'admin', 'support@example.org', encoded, True),
        ])
        self.conn.executemany('INSERT INTO login_sessions(id,user_id,token_hash,expires_at,revoked_at) VALUES(?,?,?,?,?)', [
            (101, 2, key_digest(CURRENT), '2099-01-01 00:00:00+00:00', None),
            (102, 2, key_digest(OTHER), '2099-01-01 00:00:00+00:00', None),
            (103, 2, key_digest('expired'), '2000-01-01 00:00:00+00:00', None),
            (104, 2, key_digest('revoked'), '2099-01-01 00:00:00+00:00', '2026-01-01'),
            (201, 3, key_digest('neighbor'), '2099-01-01 00:00:00+00:00', None),
            (301, 9, key_digest(FOREIGN), '2099-01-01 00:00:00+00:00', None),
        ])
        self.conn.executemany('INSERT INTO api_keys VALUES(?,?,?,NULL)', [(1, 2, key_digest(API_KEY)), (2, 10, key_digest(STAFF_KEY))])
        self.conn.commit()

    def execute(self, query, args=()):
        self.calls.append((query, args))
        if query.startswith('SET TRANSACTION'): return self.conn.execute('SELECT 1')
        if self.fail_audit and 'INSERT INTO audit_events' in query:
            raise RuntimeError('Synthetic audit failure')
        query = query.replace(' FOR UPDATE', '').replace(' FOR KEY SHARE', '').replace('%s', '?')
        query = query.replace("now() + (? * interval '1 hour')", "datetime('now', ? || ' hours')")
        query = query.replace('now()', 'CURRENT_TIMESTAMP')
        return self.conn.execute(query, args)

    @contextmanager
    def connect(self):
        with self.conn: yield self


@pytest.fixture
def db(monkeypatch):
    db = Database()
    for module in (service, account_auth, security):
        monkeypatch.setattr(module, 'db_connection', db.connect)
    monkeypatch.setattr(service, 'password_throttle', account_auth.LoginThrottle())
    monkeypatch.setattr(account_auth, 'login_throttle', account_auth.LoginThrottle())
    yield db
    db.conn.close()


def revoked(db, session_id):
    return db.conn.execute('SELECT revoked_at IS NOT NULL FROM login_sessions WHERE id=?', (session_id,)).fetchone()[0]


def test_session_list_is_private_active_paged_and_never_exposes_hashes(db):
    result = service.list_sessions(USER, CURRENT)
    assert result['total'] == 2 and result['password_session'] and result['password_enabled']
    assert [s['id'] for s in result['sessions']] == [102, 101]
    assert [s['id'] for s in result['sessions'] if s['current']] == [101]
    assert all(set(s) == {'id', 'created_at', 'expires_at', 'current'} for s in result['sessions'])
    assert service.list_sessions(STAFF, STAFF_KEY)['sessions'] == []
    key_result = service.list_sessions(USER, API_KEY)
    assert not key_result['password_session'] and not any(s['current'] for s in key_result['sessions'])
    for i in range(25):
        db.conn.execute('INSERT INTO login_sessions(user_id,token_hash,expires_at) VALUES(?,?,?)',
                        (2, key_digest(f'extra-{i}'), '2099-01-01'))
    a, b = service.list_sessions(USER, CURRENT), service.list_sessions(USER, CURRENT, page=2)
    assert a['total'] == b['total'] == 27
    assert not {s['id'] for s in a['sessions']} & {s['id'] for s in b['sessions']}
    assert service.list_sessions(USER, CURRENT, page=999)['page'] == 2


def test_password_change_updates_hash_revokes_all_sessions_and_preserves_keys(db):
    result = service.change_password(USER, CURRENT, PASSWORD, NEW_PASSWORD)
    assert result == {'sign_in_required': True}
    stored = db.conn.execute('SELECT password_hash FROM app_users WHERE id=2').fetchone()[0]
    assert stored != NEW_PASSWORD and account_auth.verify_password(NEW_PASSWORD, stored)
    assert not account_auth.verify_password(PASSWORD, stored)
    assert all(revoked(db, s) for s in (101, 102, 103, 104))
    assert not revoked(db, 201) and not revoked(db, 301)
    assert security.principal_from_api_key(CURRENT) is None
    assert security.principal_from_api_key(OTHER) is None
    assert security.principal_from_api_key(API_KEY) == USER
    with pytest.raises(HTTPException) as error:
        account_auth.login('reader@example.org', PASSWORD, 'test-client')
    assert error.value.status_code == 401
    fresh = account_auth.login('reader@example.org', NEW_PASSWORD, 'test-client')
    assert security.principal_from_api_key(fresh['access_token']) == USER
    audit = db.conn.execute('SELECT * FROM audit_events').fetchall()
    assert audit == [(7, 2, 'account.password.changed')]


def test_incorrect_current_password_does_not_revoke_auth_and_is_throttled(db):
    for _ in range(8):
        with pytest.raises(HTTPException) as error:
            service.change_password(USER, CURRENT, 'incorrect-value', NEW_PASSWORD)
        assert error.value.status_code == 400
    with pytest.raises(HTTPException) as error:
        service.change_password(USER, CURRENT, PASSWORD, NEW_PASSWORD)
    assert error.value.status_code == 429
    assert not revoked(db, 101) and not revoked(db, 102)
    assert not db.conn.execute('SELECT * FROM audit_events').fetchall()


@pytest.mark.parametrize('password', ['short', 'x' * 129, '\ud800' * 12])
def test_invalid_new_password_never_changes_credentials(db, password):
    with pytest.raises(HTTPException) as error:
        service.change_password(USER, CURRENT, PASSWORD, password)
    assert error.value.status_code == 422
    assert not revoked(db, 101)


def test_initial_password_is_operator_only_and_current_password_reuse_is_rejected(db):
    with pytest.raises(HTTPException) as error:
        service.change_password(USER, API_KEY, PASSWORD, PASSWORD)
    assert error.value.status_code == 400
    db.conn.execute('UPDATE app_users SET password_hash=NULL WHERE id=2')
    assert not service.list_sessions(USER, API_KEY)['password_enabled']
    with pytest.raises(HTTPException) as error:
        service.change_password(USER, API_KEY, PASSWORD, NEW_PASSWORD)
    assert error.value.status_code == 409


def test_revocation_only_affects_the_authenticated_owner_and_identifies_current(db):
    for principal, token, session_id in [(USER, CURRENT, 201), (USER, CURRENT, 301),
                                         (STAFF, STAFF_KEY, 101), (USER, CURRENT, 103)]:
        with pytest.raises(HTTPException) as error:
            service.revoke_session(principal, token, session_id)
        assert error.value.status_code == 404
    assert service.revoke_session(USER, CURRENT, 102) == {'sign_in_required': False, 'revoked_count': 1}
    assert security.principal_from_api_key(CURRENT) == USER
    assert security.principal_from_api_key(OTHER) is None
    assert service.revoke_session(USER, CURRENT, 101)['sign_in_required']
    assert security.principal_from_api_key(CURRENT) is None


@pytest.mark.parametrize('token,count', [(CURRENT, 1), (API_KEY, 2)])
def test_bulk_revocation_keeps_current_password_session_or_api_key(db, token, count):
    result = service.revoke_other_sessions(USER, token)
    assert result == {'sign_in_required': False, 'revoked_count': count}
    assert revoked(db, 102) and not revoked(db, 201) and not revoked(db, 301)
    assert bool(revoked(db, 101)) == (token == API_KEY)
    assert security.principal_from_api_key(token) == USER


@pytest.mark.parametrize('operation', ['password', 'single', 'others'])
def test_audit_failure_rolls_back_all_security_changes(db, operation):
    old_hash = db.conn.execute('SELECT password_hash FROM app_users WHERE id=2').fetchone()[0]
    db.fail_audit = True
    with pytest.raises(RuntimeError):
        if operation == 'password': service.change_password(USER, CURRENT, PASSWORD, NEW_PASSWORD)
        elif operation == 'single': service.revoke_session(USER, CURRENT, 102)
        else: service.revoke_other_sessions(USER, CURRENT)
    assert db.conn.execute('SELECT password_hash FROM app_users WHERE id=2').fetchone()[0] == old_hash
    assert not revoked(db, 101) and not revoked(db, 102)


def test_mutations_recheck_current_credentials_after_acquiring_account_lock(db):
    db.conn.execute('UPDATE login_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE id=101')
    with pytest.raises(HTTPException) as error:
        service.change_password(USER, CURRENT, PASSWORD, NEW_PASSWORD)
    assert error.value.status_code == 401 and not revoked(db, 102)
    with pytest.raises(HTTPException):
        service.revoke_other_sessions(Principal(2, 8, 'admin', 'forged-tenant'), API_KEY)
    db.conn.execute('UPDATE app_users SET is_active=0 WHERE id=2')
    with pytest.raises(HTTPException): service.revoke_other_sessions(USER, API_KEY)


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    monkeypatch.setattr(main.app, 'dependency_overrides', {})
    with TestClient(main.app) as client: yield client


def test_endpoints_require_auth_csrf_and_never_echo_invalid_passwords(client):
    body = {'current_password': PASSWORD, 'new_password': NEW_PASSWORD}
    for method, path, payload in [('GET', '/auth/sessions', None), ('POST', '/auth/password', body),
                                 ('DELETE', '/auth/sessions/102', None), ('POST', '/auth/sessions/revoke-others', None)]:
        assert client.request(method, path, json=payload).status_code == 401
    client.cookies.set('rag_browser_session', CURRENT)
    assert client.post('/auth/password', json=body).status_code == 403
    assert client.delete('/auth/sessions/102').status_code == 403
    assert client.post('/auth/sessions/revoke-others').status_code == 403
    headers = {'X-RAG-CSRF': '1'}
    for changes in ({'new_password': 'private!'}, {'current_password': {}},
                    {'new_password': 'q' * 129}, {'user_id': 9}, {'tenant_id': 8}):
        response = client.post('/auth/password', json={**body, **changes}, headers=headers)
        assert response.status_code == 422
        assert PASSWORD not in response.text and NEW_PASSWORD not in response.text and 'private!' not in response.text
    for query in ('page=0', 'page_size=21'):
        assert client.get(f'/auth/sessions?{query}').status_code == 422
    response = client.get('/auth/sessions?page_size=50')
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert CURRENT not in response.text and key_digest(CURRENT) not in response.text
    assert 'password_hash' not in response.text and 'token_hash' not in response.text


def test_password_change_clears_only_its_cookie_and_returns_success_before_signout(client):
    client.cookies.set('rag_browser_session', CURRENT)
    response = client.post('/auth/password', json={'current_password': PASSWORD, 'new_password': NEW_PASSWORD},
                           headers={'X-RAG-CSRF': '1'})
    assert response.status_code == 200 and response.json() == {'sign_in_required': True}
    assert 'Max-Age=0' in response.headers['set-cookie']
    assert client.get('/auth/sessions').status_code == 401


def test_api_key_precedence_preserves_unrelated_cookie_and_legacy_auth(client):
    client.cookies.set('rag_browser_session', FOREIGN)
    response = client.post('/auth/password', json={'current_password': PASSWORD, 'new_password': NEW_PASSWORD},
                           headers={'Authorization': f'Bearer {API_KEY}'})
    assert response.status_code == 200 and response.json() == {'sign_in_required': False}
    assert 'set-cookie' not in response.headers
    assert client.get('/me', headers={'Authorization': f'Bearer {API_KEY}'}).json()['user_id'] == USER.user_id
    assert client.get('/me').json()['user_id'] == 9
    assert client.get('/auth/sessions', headers={'Authorization': 'Bearer invalid'}).status_code == 401


def test_wrong_password_is_a_form_error_and_current_revocation_clears_cookie(client):
    client.cookies.set('rag_browser_session', CURRENT)
    response = client.post('/auth/password', json={'current_password': 'wrong', 'new_password': NEW_PASSWORD},
                           headers={'X-RAG-CSRF': '1'})
    assert response.status_code == 400 and 'set-cookie' not in response.headers
    response = client.delete('/auth/sessions/101', headers={'X-RAG-CSRF': '1'})
    assert response.status_code == 200 and response.json()['sign_in_required']
    assert 'Max-Age=0' in response.headers['set-cookie']


def test_old_password_login_cannot_escape_password_change_revocation(monkeypatch):
    """Emulate PostgreSQL row locks with controlled concurrent transactions."""
    lock, login_checked, continue_login, change_blocked = Lock(), Event(), Event(), Event()
    state = {'password': 'encoded:' + PASSWORD, 'sessions': [key_digest(CURRENT)]}
    class Cursor:
        def __init__(self, row=None): self.row = row
        def fetchone(self): return self.row
    class Connection:
        held = False
        def execute(self, query, args=()):
            if 'FROM app_users' in query and 'FOR UPDATE' in query:
                if not lock.acquire(blocking=False):
                    change_blocked.set()
                    lock.acquire()
                self.held = True
            if 'WHERE lower(email)' in query:
                return Cursor((2, state['password'], True))
            if 'SELECT password_hash FROM app_users' in query:
                return Cursor((state['password'],))
            if 'SELECT id FROM login_sessions' in query:
                return Cursor((101,)) if args[0] in state['sessions'] else Cursor()
            if 'INSERT INTO login_sessions' in query: state['sessions'].append(args[1])
            if 'UPDATE app_users SET password_hash' in query: state['password'] = args[0]
            if 'UPDATE login_sessions SET revoked_at' in query: state['sessions'].clear()
            return Cursor()
    @contextmanager
    def connect():
        conn = Connection()
        try: yield conn
        finally:
            if conn.held: lock.release()
    for module in (account_auth, service): monkeypatch.setattr(module, 'db_connection', connect)
    monkeypatch.setattr(service, 'password_throttle', account_auth.LoginThrottle())
    monkeypatch.setattr(account_auth, 'login_throttle', account_auth.LoginThrottle())
    monkeypatch.setattr(account_auth, 'hash_password', lambda value: 'encoded:' + value)
    def verify(password, encoded):
        from threading import current_thread
        if current_thread().name == 'old-login':
            login_checked.set()
            assert continue_login.wait(5)
        return encoded == 'encoded:' + password
    monkeypatch.setattr(account_auth, 'verify_password', verify)
    results, errors = {}, []
    def login():
        try: results['login'] = account_auth.login('reader@example.org', PASSWORD, 'race-test')
        except Exception as exc: errors.append(exc)
    def change():
        try: results['change'] = service.change_password(USER, CURRENT, PASSWORD, NEW_PASSWORD)
        except Exception as exc: errors.append(exc)
    a, b = Thread(target=login, name='old-login'), Thread(target=change, name='change-password')
    a.start()
    try:
        assert login_checked.wait(5)
        b.start()
        assert change_blocked.wait(5), 'Password change must wait for a login checking the previous password'
    finally:
        continue_login.set()
        a.join(5)
        if b.ident is not None: b.join(5)
    assert not a.is_alive() and not b.is_alive() and not errors
    assert results['login']['access_token'] and results['change']['sign_in_required']
    assert state['password'] == 'encoded:' + NEW_PASSWORD and state['sessions'] == []
