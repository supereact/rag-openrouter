"""M10 account security invariants; does not need a running database."""
from contextlib import contextmanager
import pytest
from fastapi import HTTPException

from app import account_auth
from app.security import Principal

ADMIN = Principal(1, 1, 'admin', 'admin')
READER = Principal(2, 1, 'reader', 'reader')


def test_password_hash_is_salted_and_verifiable():
    a = account_auth.hash_password('correct horse battery staple')
    b = account_auth.hash_password('correct horse battery staple')
    assert a != b
    assert 'correct horse' not in a
    assert account_auth.verify_password('correct horse battery staple', a)
    assert not account_auth.verify_password('wrong password', a)
    assert not account_auth.verify_password('wrong password', None)


def test_password_length_and_email_validation():
    for password in ('weak', ' ' * 129):
        with pytest.raises(ValueError):
            account_auth.hash_password(password)
    assert account_auth.normalize_email(' Test@EXAMPLE.org ') == 'test@example.org'
    with pytest.raises(ValueError):
        account_auth.normalize_email('invalidaddress')


def test_login_throttle():
    limiter = account_auth.LoginThrottle()
    for _ in range(8):
        assert limiter.allowed('ip:email')
        limiter.failure('ip:email')
    assert not limiter.allowed('ip:email')
    limiter.success('ip:email')
    assert limiter.allowed('ip:email')


def test_registration_rejects_invalid_token_without_db(monkeypatch):
    monkeypatch.setattr(account_auth, 'db_connection', lambda: (_ for _ in ()).throw(AssertionError('DB must not be queried')))
    with pytest.raises(ValueError, match='Invalid or expired invitation'):
        account_auth.register('forged', 'someone@example.com', 'someone', 'long password 12345')


def test_only_admin_can_operate_admin_services(monkeypatch):
    monkeypatch.setattr(account_auth, 'db_connection', lambda: (_ for _ in ()).throw(AssertionError('DB must not be queried')))
    with pytest.raises(HTTPException) as exc:
        account_auth.invitation(READER, 'person@example.com', 'reader')
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException):
        account_auth.dashboard(READER)
    with pytest.raises(HTTPException):
        account_auth.list_users(READER)
    with pytest.raises(HTTPException):
        account_auth.update_user(READER, 1, 'admin', None)
    with pytest.raises(HTTPException):
        account_auth.revoke_sessions(READER, 1)


def test_admin_cannot_change_self_or_issue_admin_invite(monkeypatch):
    monkeypatch.setattr(account_auth, 'db_connection', lambda: (_ for _ in ()).throw(AssertionError('DB must not be queried')))
    with pytest.raises(ValueError, match='your own'):
        account_auth.update_user(ADMIN, 1, 'reader', None)
    with pytest.raises(ValueError, match='reader or editor'):
        account_auth.invitation(ADMIN, 'person@example.com', 'admin')


def test_disable_other_account_revokes_sessions_and_is_tenant_scoped(monkeypatch):
    queries = []
    class FakeConn:
        def execute(self, sql, args=()):
            queries.append((sql,args))
            if 'SELECT username,email,role,is_active' in sql:
                return self
            if 'SELECT id FROM tenants' in sql:
                return self
            return self
        def fetchone(self):
            return ('employee','employee@example.com','reader',True)
    @contextmanager
    def fake_db():
        yield FakeConn()
    monkeypatch.setattr(account_auth, 'db_connection', fake_db)
    updated = account_auth.update_user(ADMIN, 2, None, False)
    assert updated['is_active'] is False
    assert any('UPDATE login_sessions SET revoked_at' in q for q,_ in queries)
    assert any('WHERE id=%s AND tenant_id=%s' in q and args==(2,1) for q,args in queries)


def test_last_admin_guard(monkeypatch):
    class FakeConn:
        def execute(self, sql, args=()):
            self.query = sql
            return self
        def fetchone(self):
            if 'COUNT(*)' in self.query:
                return (1,)
            return ('otheradmin','other@example.com','admin',True)
    @contextmanager
    def fake_db():
        yield FakeConn()
    monkeypatch.setattr(account_auth, 'db_connection', fake_db)
    with pytest.raises(ValueError, match='last active'):
        account_auth.update_user(ADMIN, 3, 'reader', None)


def test_session_logout_does_not_revoke_legacy_api_key(monkeypatch):
    monkeypatch.setattr(account_auth, 'db_connection', lambda: (_ for _ in ()).throw(AssertionError('API keys stay valid')))
    account_auth.logout('rag_legacy_key')
