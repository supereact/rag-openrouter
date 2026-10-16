"""Document access deltas, validation, and transactional tenant boundaries."""
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app import document_access as access, main, security
from app.security import Principal

ADMIN = Principal(1, 7, 'admin', 'admin')
OWNER = Principal(2, 7, 'editor', 'owner')
EDITOR = Principal(4, 7, 'editor', 'editor')
READER = Principal(3, 7, 'reader', 'reader')
OTHER = Principal(9, 8, 'admin', 'outside')


class Result:
    def __init__(self, one=None, many=None):
        self.one, self.many = one, many or []

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.many


class Database:
    def __init__(self):
        self.calls = []
        self.connections = 0
        self.acl = {(11, 7, 3), (11, 7, 6), (12, 7, 3)}
        self.audit = []
        self.fail_audit = False
        # id -> tenant, username, active, role
        self.users = {
            1: (7, 'admin', True, 'admin'), 2: (7, 'owner', True, 'editor'),
            3: (7, 'reader', True, 'reader'), 4: (7, 'editor', True, 'editor'),
            5: (7, 'another', True, 'reader'), 6: (7, 'inactive-shared', False, 'reader'),
            7: (7, 'inactive', False, 'reader'), 8: (7, 'other-admin', True, 'admin'),
            9: (8, 'outside', True, 'admin'),
        }

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if 'SELECT owner_user_id' in sql:
            doc, tenant, user, role = params
            return Result((2,) if doc == 11 and tenant == 7 and (user == 2 or role == 'admin') else None)
        if 'SELECT u.id,u.username' in sql:
            doc, tenant = params
            return Result(many=[(uid, name, f'{name}@example.org', active, role,
                                 (doc, tenant, uid) in self.acl)
                                for uid, (tid, name, active, role) in self.users.items() if tid == tenant])
        if 'SELECT id,role,is_active' in sql:
            tenant, ids = params
            assert 'FOR SHARE' in sql
            return Result(many=[(uid, self.users[uid][3], self.users[uid][2]) for uid in ids
                                if uid in self.users and self.users[uid][0] == tenant])
        if 'DELETE FROM document_acl' in sql:
            doc, tenant, ids = params
            self.acl.difference_update((doc, tenant, uid) for uid in ids)
            return Result()
        if 'INSERT INTO document_acl' in sql:
            doc, tenant, target_tenant, ids = params
            assert tenant == target_tenant
            self.acl.update((doc, tenant, uid) for uid in ids)
            return Result()
        if 'INSERT INTO audit_events' in sql:
            if self.fail_audit:
                raise RuntimeError('Synthetic audit failure')
            self.audit.append(params)
            return Result()
        raise AssertionError('Unexpected SQL')

    @contextmanager
    def connect(self):
        self.connections += 1
        acl, audit = self.acl.copy(), self.audit.copy()
        try:
            yield self
        except BaseException:
            self.acl, self.audit = acl, audit
            raise


@pytest.fixture
def db(monkeypatch):
    database = Database()
    monkeypatch.setattr(access, 'db_connection', database.connect)
    return database


@pytest.mark.parametrize('principal', [ADMIN, OWNER])
def test_owner_and_admin_read_minimal_same_tenant_directory(db, principal):
    users = access.get_access(principal, 11)['users']
    by_id = {user['id']: user for user in users}
    assert 9 not in by_id
    assert by_id[2]['automatic_access'] == 'owner'
    assert by_id[1]['automatic_access'] == 'admin'
    assert by_id[3]['shared'] is True
    assert by_id[6]['is_active'] is False
    assert set(by_id[3]) == {'id', 'username', 'email', 'is_active', 'shared', 'automatic_access'}


@pytest.mark.parametrize('principal,doc', [(EDITOR, 11), (OTHER, 11), (OWNER, 999)])
def test_inaccessible_document_hides_directory_and_blocks_writes(db, principal, doc):
    with pytest.raises(PermissionError):
        access.get_access(principal, doc)
    with pytest.raises(PermissionError):
        access.update_access(principal, doc, [5], [3])
    assert not any('FROM app_users' in sql or 'DELETE FROM document_acl' in sql for sql, _ in db.calls)


def test_reader_is_rejected_before_opening_database(db):
    with pytest.raises(PermissionError):
        access.get_access(READER, 11)
    with pytest.raises(PermissionError):
        access.update_access(READER, 11, [5], [])
    assert db.connections == 0


@pytest.mark.parametrize('principal', [ADMIN, OWNER])
def test_atomic_delta_grants_many_and_revokes_including_inactive_users(db, principal):
    users = access.update_access(principal, 11, [4, 5, 5], [3, 6])['users']
    assert db.acl == {(11, 7, 4), (11, 7, 5), (12, 7, 3)}
    assert {u['id'] for u in users if u['shared']} == {4, 5}
    assert db.connections == 1
    assert db.calls[0][0].endswith('FOR UPDATE')
    assert db.audit == [(7, principal.user_id, 'document.access.update', 11, 4)]


@pytest.mark.parametrize('target', [9, 999, 7, 1, 2, 8])
def test_all_targets_validated_before_any_acl_changes(db, target):
    before = db.acl.copy()
    with pytest.raises(ValueError):
        access.update_access(OWNER, 11, [4, target], [3])
    assert db.acl == before
    assert not any('DELETE FROM document_acl' in sql or 'INSERT INTO document_acl' in sql
                   for sql, _ in db.calls)
    assert not db.audit


@pytest.mark.parametrize('target', [1, 2, 8])
def test_automatic_access_cannot_be_revoked(db, target):
    with pytest.raises(ValueError, match='automatic'):
        access.update_access(OWNER, 11, [], [target])


def test_overlapping_grant_and_revoke_rejected_before_database(db):
    with pytest.raises(ValueError, match='same request'):
        access.update_access(OWNER, 11, [4], [4])
    assert db.connections == 0


def test_delta_preserves_unrelated_concurrent_grant_and_other_documents(db):
    db.acl.add((11, 7, 5))
    access.update_access(OWNER, 11, [4], [3])
    assert (11, 7, 5) in db.acl
    assert (12, 7, 3) in db.acl


def test_acl_changes_rollback_when_audit_fails(db):
    before = db.acl.copy()
    db.fail_audit = True
    with pytest.raises(RuntimeError, match='Synthetic audit failure'):
        access.update_access(OWNER, 11, [4], [3])
    assert db.acl == before
    assert db.audit == []


def test_repeated_delta_is_idempotent(db):
    access.update_access(OWNER, 11, [4], [3])
    before = db.acl.copy()
    access.update_access(OWNER, 11, [4], [3])
    assert db.acl == before


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    monkeypatch.setattr(main.app, 'dependency_overrides', {})
    with TestClient(main.app) as api_client:
        yield api_client


@pytest.mark.parametrize('principal,status', [(None, 401), (READER, 403)])
def test_access_routes_require_writer_authentication(client, db, principal, status):
    if principal is not None:
        main.app.dependency_overrides[security.require_principal] = lambda: principal
    assert client.get('/documents/11/access').status_code == status
    assert client.patch('/documents/11/access', json={}).status_code == status
    assert db.connections == 0


def test_owner_can_list_and_update_document_access(client, db):
    main.app.dependency_overrides[security.require_principal] = lambda: OWNER
    response = client.get('/documents/11/access')
    assert response.status_code == 200
    assert 9 not in {u['id'] for u in response.json()['users']}
    response = client.patch('/documents/11/access', json={'grant_user_ids': [4, 5], 'revoke_user_ids': [3]})
    assert response.status_code == 200
    assert {u['id'] for u in response.json()['users'] if u['shared']} == {4, 5, 6}


@pytest.mark.parametrize('principal', [EDITOR, OTHER])
def test_access_routes_hide_inaccessible_documents(client, principal):
    main.app.dependency_overrides[security.require_principal] = lambda: principal
    assert client.get('/documents/11/access').json() == {'detail': 'Document not found'}
    assert client.patch('/documents/11/access', json={}).status_code == 404


@pytest.mark.parametrize('ids', [[0], [-1], [True], ['4'], [4] * 1001])
def test_access_route_validates_user_ids(client, db, ids):
    main.app.dependency_overrides[security.require_principal] = lambda: ADMIN
    assert client.patch('/documents/11/access', json={'grant_user_ids': ids}).status_code == 422
    assert db.connections == 0


def test_foreign_recipient_and_conflicting_changes_are_rejected_atomically(client, db):
    main.app.dependency_overrides[security.require_principal] = lambda: ADMIN
    before = db.acl.copy()
    for body in ({'grant_user_ids': [4, 9], 'revoke_user_ids': [3]},
                 {'grant_user_ids': [4], 'revoke_user_ids': [4]}):
        assert client.patch('/documents/11/access', json=body).status_code == 400
    assert db.acl == before


def test_existing_single_username_share_endpoint_remains_compatible(client, monkeypatch):
    main.app.dependency_overrides[security.require_principal] = lambda: OWNER
    grant = Mock()
    monkeypatch.setattr(main, 'share_document', grant)
    response = client.post('/documents/11/share', json={'username': 'reader'})
    assert response.status_code == 200
    assert response.json() == {'status': 'granted'}
    grant.assert_called_once_with(OWNER, 11, 'reader')
