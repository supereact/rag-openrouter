"""Registration/accounting integration using a temporary relational database.

No live PostgreSQL, models or provider calls. The fixture lock models the
production tenant advisory transaction lock for concurrent reservations.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
import sqlite3
from threading import RLock

from fastapi import HTTPException
from fastapi.testclient import TestClient
import psycopg
import pytest

from app import account_auth, credit_budgets, main, security, settings, starter_allowances
from app.security import Principal, key_digest

PASSWORD = 'test-only-long-password'


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:', check_same_thread=False)
        self.lock = RLock()
        self.fail = None
        self.calls = []
        self.conn.executescript('''
            PRAGMA foreign_keys=ON;
            CREATE TABLE tenants(id INTEGER PRIMARY KEY,slug TEXT UNIQUE);
            INSERT INTO tenants VALUES(1,'existing');
            CREATE TABLE app_users(id INTEGER PRIMARY KEY,tenant_id INTEGER,username TEXT,
                role TEXT,email TEXT UNIQUE,password_hash TEXT,is_active BOOLEAN DEFAULT TRUE,
                UNIQUE(id,tenant_id),UNIQUE(tenant_id,username));
            INSERT INTO app_users VALUES(1,1,'existing-admin','admin','old@example.org',NULL,TRUE);
            CREATE TABLE signup_invitations(id INTEGER PRIMARY KEY,tenant_id INTEGER,email TEXT,
                role TEXT,code_hash TEXT,used_at TEXT,expires_at TEXT);
            CREATE TABLE login_sessions(id INTEGER PRIMARY KEY,user_id INTEGER,token_hash TEXT,
                expires_at TEXT,revoked_at TEXT);
            CREATE TABLE user_starter_allowances(tenant_id INTEGER,user_id INTEGER,
                limit_credits NUMERIC,PRIMARY KEY(tenant_id,user_id),
                FOREIGN KEY(user_id,tenant_id) REFERENCES app_users(id,tenant_id));
            CREATE TABLE tenant_credit_budgets(tenant_id INTEGER,monthly_limit_credits NUMERIC,
                paused BOOLEAN,reservation_credits NUMERIC);
            CREATE TABLE user_credit_budgets(tenant_id INTEGER,user_id INTEGER,
                monthly_limit_credits NUMERIC,paused BOOLEAN);
            CREATE TABLE openrouter_usage_events(id TEXT,tenant_id INTEGER,user_id INTEGER,model TEXT,
                prompt_tokens INTEGER,completion_tokens INTEGER,cost_credits NUMERIC,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE credit_reservations(id TEXT,tenant_id INTEGER,user_id INTEGER,
                reserved_credits NUMERIC,actual_cost_credits NUMERIC,status TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,finalized_at TEXT);
        ''')

    def execute(self, query, args=()):
        self.calls.append((query, args))
        if self.fail and self.fail in query:
            raise RuntimeError('Synthetic transaction failure')
        if 'pg_advisory_xact_lock' in query:
            return self.conn.execute('SELECT 1')
        query = query.replace(' FOR UPDATE', '').replace('%s', '?')
        query = query.replace("now() + (? * interval '1 hour')", "datetime('now', ? || ' hours')")
        query = query.replace('now()', 'CURRENT_TIMESTAMP')
        args = tuple(value if isinstance(value, (str, int, float, type(None))) else str(value) for value in args)
        try:
            return self.conn.execute(query, args)
        except sqlite3.IntegrityError as exc:
            raise psycopg.errors.UniqueViolation('Synthetic uniqueness violation') from exc

    @contextmanager
    def connect(self):
        with self.lock:
            with self.conn:
                yield self

    def count(self, table):
        return self.conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]


@pytest.fixture
def db(monkeypatch):
    db = Database()
    for module in (account_auth, credit_budgets, security):
        monkeypatch.setattr(module, 'db_connection', db.connect)
    monkeypatch.setattr(settings, 'RAG_PUBLIC_REGISTRATION_ENABLED', 'true')
    monkeypatch.setattr(settings, 'RAG_PAYMENTS_MODE', 'disabled')
    monkeypatch.setattr(settings, 'RAG_WALLET_ENFORCEMENT', 'false')
    monkeypatch.setattr(account_auth, 'registration_throttle', account_auth.LoginThrottle())
    monkeypatch.setattr(account_auth, 'login_throttle', account_auth.LoginThrottle())
    yield db
    db.conn.close()


def signup(email='new@example.org', code=''):
    token = account_auth.register(code, email, 'new-user', PASSWORD)
    return security.principal_from_api_key(token['access_token'])


def test_public_registration_creates_isolated_editor_workspaces_and_allowances(db):
    first, second = signup(), signup('second@example.org')
    assert first.tenant_id != second.tenant_id and first.tenant_id != 1
    assert first.role == second.role == 'editor'
    assert db.count('tenants') == 3
    assert db.count('user_starter_allowances') == 2
    assert starter_allowances.remaining(db, first) == Decimal('0.001')
    assert starter_allowances.remaining(db, second) == Decimal('0.001')
    assert starter_allowances.remaining(db, Principal(1, 1, 'admin', 'existing-admin')) is None


def test_invitations_keep_tenant_role_and_email_binding(db):
    code = 'invite_' + 'a' * 40
    db.conn.execute('INSERT INTO signup_invitations VALUES(1,1,?,?,?,NULL,?)',
                    ('new@example.org', 'reader', key_digest(code), '2099-01-01'))
    db.conn.commit()
    with pytest.raises(ValueError, match='invitation'):
        signup('wrong@example.org', code)
    assert db.count('tenants') == 1
    invited = signup(code=code)
    assert invited.tenant_id == 1 and invited.role == 'reader'
    assert starter_allowances.remaining(db, invited) == Decimal('0.001')
    with pytest.raises(ValueError, match='invitation'):
        signup('second@example.org', code)
    assert db.count('user_starter_allowances') == 1


@pytest.mark.parametrize('value', ['false', 'invalid'])
def test_public_registration_can_be_disabled_without_changing_invites(db, monkeypatch, value):
    monkeypatch.setattr(settings, 'RAG_PUBLIC_REGISTRATION_ENABLED', value)
    with pytest.raises(HTTPException) as exc:
        signup()
    assert exc.value.status_code == 403
    assert db.count('tenants') == 1
    code = 'invite_' + 'b' * 40
    db.conn.execute('INSERT INTO signup_invitations VALUES(1,1,?,?,?,NULL,?)',
                    ('new@example.org', 'editor', key_digest(code), '2099-01-01'))
    db.conn.commit()
    assert signup(code=code).tenant_id == 1


@pytest.mark.parametrize('failure', ['INSERT INTO user_starter_allowances', 'INSERT INTO login_sessions'])
def test_failed_signup_rolls_back_workspace_user_allowance_and_session(db, failure):
    db.fail = failure
    with pytest.raises(RuntimeError):
        signup()
    assert db.count('tenants') == db.count('app_users') == 1
    assert db.count('user_starter_allowances') == db.count('login_sessions') == 0


def test_duplicate_email_rolls_back_new_tenant_and_login_never_refills(db):
    principal = signup()
    with pytest.raises(ValueError, match='already registered'):
        signup()
    assert db.count('tenants') == db.count('app_users') == 2
    hold = credit_budgets.reserve_request(principal)
    credit_budgets.settle_request(hold, principal, 'synthetic/model', {'provider_cost_credits': Decimal('0.001')})
    account_auth.login('new@example.org', PASSWORD, 'synthetic-ip')
    assert db.count('user_starter_allowances') == 1
    assert starter_allowances.remaining(db, principal) == 0


def test_known_costs_consume_only_remaining_allowance_then_block(db):
    principal = signup()
    first = credit_budgets.reserve_request(principal)
    amount = db.conn.execute('SELECT reserved_credits FROM credit_reservations').fetchone()[0]
    assert Decimal(str(amount)) == Decimal('0.001')
    credit_budgets.settle_request(first, principal, 'synthetic/model', {'provider_cost_credits': Decimal('0.0004')})
    second = credit_budgets.reserve_request(principal)
    credit_budgets.settle_request(second, principal, 'synthetic/model', {'provider_cost_credits': Decimal('0.0006')})
    with pytest.raises(HTTPException) as exc:
        credit_budgets.reserve_request(principal)
    assert exc.value.status_code == 429
    assert db.count('openrouter_usage_events') == 2


def test_concurrent_requests_cannot_reserve_the_same_starter_credit(db):
    principal = signup()
    def attempt(_):
        try:
            return credit_budgets.reserve_request(principal)
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert results.count(429) == 1
    assert db.count('credit_reservations') == 1


def test_unused_hold_releases_but_unknown_cost_survives_month_rollover(db):
    principal = signup()
    hold = credit_budgets.reserve_request(principal)
    credit_budgets.release_before_generation(hold, principal)
    assert starter_allowances.remaining(db, principal) == Decimal('0.001')
    hold = credit_budgets.reserve_request(principal)
    assert credit_budgets.settle_request(hold, principal, 'synthetic/model', None) == 'unknown'
    db.conn.execute("UPDATE credit_reservations SET created_at='2000-01-01'")
    db.conn.commit()
    with pytest.raises(HTTPException):
        credit_budgets.reserve_request(principal)
    assert db.count('openrouter_usage_events') == 0
    # Another tenant's allowance remains entirely available.
    other = signup('other@example.org')
    assert starter_allowances.remaining(db, other) == Decimal('0.001')


def test_reported_overage_blocks_future_requests_and_monthly_policies_still_apply(db):
    principal = signup()
    db.conn.execute('INSERT INTO user_credit_budgets VALUES(?,?,0,TRUE)', (principal.tenant_id, principal.user_id))
    db.conn.commit()
    with pytest.raises(HTTPException, match='paused'):
        credit_budgets.reserve_request(principal)
    db.conn.execute('DELETE FROM user_credit_budgets')
    db.conn.commit()
    hold = credit_budgets.reserve_request(principal)
    credit_budgets.settle_request(hold, principal, 'synthetic/model', {'provider_cost_credits': Decimal('0.002')})
    with pytest.raises(HTTPException):
        credit_budgets.reserve_request(principal)


@pytest.mark.parametrize('route', ['/auth/register', '/auth/browser/register'])
def test_public_api_signup_without_invite_and_rejects_tenant_role_injection(db, monkeypatch, route):
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    body = dict(email='new@example.org', username='new-user', password=PASSWORD)
    headers = {'X-RAG-CSRF': '1', 'Origin': 'https://workspace.example'}
    with TestClient(main.app, base_url='https://workspace.example') as client:
        for extra in ({'tenant_id': 1}, {'role': 'admin'}):
            assert client.post(route, json={**body, **extra}, headers=headers).status_code == 422
        response = client.post(route, json=body, headers=headers)
        assert response.status_code == 201
        if '/browser/' in route:
            assert response.json()['role'] == 'editor'
            assert response.json()['tenant_id'] != 1
            assert 'access_token' not in response.json()
            assert 'Secure' in response.headers['set-cookie']


def test_signup_attempt_throttle_is_shared_by_both_transports(db, monkeypatch):
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    monkeypatch.setattr(account_auth, 'register', lambda *args: (_ for _ in ()).throw(ValueError('synthetic invalid invitation')))
    body = dict(email='new@example.org', username='new-user', password=PASSWORD)
    with TestClient(main.app, base_url='https://workspace.example') as client:
        for i in range(8):
            route = '/auth/register' if i % 2 else '/auth/browser/register'
            assert client.post(route, json=body, headers={'X-RAG-CSRF': '1'}).status_code == 400
        assert client.post('/auth/register', json=body).status_code == 429


def test_registration_attempts_are_consumed_atomically():
    throttle = account_auth.LoginThrottle()
    with ThreadPoolExecutor(max_workers=16) as pool:
        assert sum(pool.map(lambda _: throttle.consume('same-ip'), range(32))) == 8


@pytest.mark.parametrize('address,status', [('172.30.72.10', 201), ('203.0.113.10', 403)])
def test_production_proxy_trust_preserves_https_cookie_and_csrf(db, monkeypatch, address, status):
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    app = ProxyHeadersMiddleware(main.app, trusted_hosts=['172.30.72.10'])
    with TestClient(app, base_url='http://workspace.example', client=(address, 55000)) as client:
        response = client.post('/auth/browser/register',
            json=dict(email='new@example.org', username='new-user', password=PASSWORD),
            headers={'X-RAG-CSRF': '1', 'Origin': 'https://workspace.example',
                     'X-Forwarded-Proto': 'https', 'X-Forwarded-For': '198.51.100.3'})
        assert response.status_code == status
        if status == 201:
            assert 'Secure' in response.headers['set-cookie']
            assert response.json()['role'] == 'editor'
        else:
            assert db.count('user_starter_allowances') == 0


def test_public_editor_can_queue_more_than_three_documents(db, monkeypatch):
    from datetime import datetime, timezone
    from uuid import uuid4
    principal = signup()
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    seen = []
    def queue(name, data, owner):
        seen.append(owner)
        return dict(id=uuid4(), filename=name, status='queued', created_at=datetime.now(timezone.utc))
    monkeypatch.setattr(main, 'queue_upload', queue)
    monkeypatch.setattr(main.app, 'dependency_overrides', {security.require_principal: lambda: principal})
    with TestClient(main.app) as client:
        for filename in ('one.pdf', 'two.txt', 'three.md', 'four.pdf'):
            assert client.post('/documents/upload-async', files={'file': (filename, b'synthetic-content')}).status_code == 202
    assert seen == [principal] * 4
