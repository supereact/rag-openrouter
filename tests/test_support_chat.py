"""Support SQL/auth regressions using a temporary relational fixture, never live DB."""
from contextlib import contextmanager
import sqlite3
from uuid import uuid4, UUID

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app import main, security, settings, support_chat
from app.security import Principal
from scripts import migrate_support

USER = Principal(2, 7, 'reader', 'reader')
NEIGHBOR = Principal(3, 7, 'admin', 'tenant-admin')
OTHER = Principal(9, 8, 'reader', 'outside')
STAFF = Principal(10, 99, 'admin', 'support-agent')


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:', check_same_thread=False)
        self.calls = []
        self.conn.executescript('''
          PRAGMA foreign_keys=ON;
          CREATE TABLE app_users(id INTEGER PRIMARY KEY,tenant_id INTEGER,username TEXT,is_active BOOLEAN,
            UNIQUE(id,tenant_id));
          INSERT INTO app_users VALUES (2,7,'reader',1),(3,7,'tenant-admin',1),
            (9,8,'outside',1),(10,99,'support-agent',1);
          CREATE TABLE support_chats(id INTEGER PRIMARY KEY,tenant_id INTEGER,user_id INTEGER,
            subject TEXT,status TEXT DEFAULT 'open',request_key TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(id,tenant_id,user_id),UNIQUE(tenant_id,user_id,request_key),
            FOREIGN KEY(user_id,tenant_id) REFERENCES app_users(id,tenant_id));
          CREATE TABLE support_messages(id INTEGER PRIMARY KEY,chat_id INTEGER,tenant_id INTEGER,
            user_id INTEGER,sender_user_id INTEGER REFERENCES app_users(id),author_kind TEXT,
            body TEXT,request_key TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(chat_id,request_key),
            CHECK(author_kind='staff' OR sender_user_id=user_id),
            FOREIGN KEY(chat_id,tenant_id,user_id) REFERENCES support_chats(id,tenant_id,user_id));
        ''')

    def execute(self, sql, args=()):
        self.calls.append((sql, args))
        query = sql.replace(' FOR UPDATE OF c', '').replace(' FOR UPDATE', '')
        query = query.replace('%s', '?').replace('now()', 'CURRENT_TIMESTAMP')
        return self.conn.execute(query, tuple(str(value) if isinstance(value, UUID) else value for value in args))

    @contextmanager
    def connect(self):
        with self.conn: yield self


@pytest.fixture
def db(monkeypatch):
    db = Database()
    monkeypatch.setattr(settings, 'RAG_SUPPORT_STAFF_USER_IDS', '10')
    monkeypatch.setattr(support_chat, 'db_connection', db.connect)
    yield db
    db.conn.close()


def create(principal=USER, subject='Upload help', body='Please help with my document.'):
    return support_chat.create_chat(principal, subject, body, uuid4())


def test_private_chats_are_owner_scoped_and_only_allowlisted_staff_cross_tenants(db):
    a = create()
    b = create(OTHER, 'Other tenant issue', 'Private outside message')
    assert support_chat.list_chats(USER)['total'] == 1
    assert support_chat.list_chats(NEIGHBOR)['total'] == 0
    assert support_chat.list_chats(OTHER)['items'][0]['id'] == b['id']
    assert support_chat.list_chats(STAFF)['total'] == 2
    assert support_chat.list_chats(STAFF)['is_staff']
    for principal, chat in [(NEIGHBOR, a), (OTHER, a), (USER, b)]:
        for action in [lambda: support_chat.read_messages(principal, chat['id']),
                       lambda: support_chat.send_message(principal, chat['id'], 'Unauthorized', uuid4())]:
            with pytest.raises(HTTPException) as error: action()
            assert error.value.status_code == 404
    # Users' source queries are owner- and tenant-constrained before pagination.
    selects = [(sql, args) for sql, args in db.calls if 'c.tenant_id=%s AND c.user_id=%s' in sql]
    assert selects and all('WHERE' in sql for sql, _ in selects)


def test_staff_replies_are_plain_messages_not_document_or_tenant_permissions(db):
    chat = create()
    sent = support_chat.send_message(STAFF, chat['id'], 'I can help you.', uuid4())
    assert sent['author_kind'] == 'staff' and sent['sender_user_id'] == STAFF.user_id
    messages = support_chat.read_messages(USER, chat['id'])['messages']
    assert [m['author_kind'] for m in messages] == ['user', 'staff']
    assert not any('documents' in sql or 'document_acl' in sql for sql, _ in db.calls)
    assert security.Principal(STAFF.user_id, STAFF.tenant_id, STAFF.role, STAFF.username) == STAFF


def test_request_keys_prevent_duplicate_chats_and_replies_even_after_close(db):
    key = uuid4()
    a = support_chat.create_chat(USER, 'Help', 'Initial message', key)
    assert support_chat.create_chat(USER, 'Help', 'Initial message', key)['id'] == a['id']
    with pytest.raises(HTTPException) as error:
        support_chat.create_chat(USER, 'Different', 'Initial message', key)
    assert error.value.status_code == 409
    key = uuid4()
    reply = support_chat.send_message(STAFF, a['id'], 'Reply', key)
    support_chat.set_status(STAFF, a['id'], 'closed')
    assert support_chat.send_message(STAFF, a['id'], 'Reply', key)['id'] == reply['id']
    for principal, body in [(USER, 'Reply'), (STAFF, 'Different reply')]:
        with pytest.raises(HTTPException) as error:
            support_chat.send_message(principal, a['id'], body, key)
        assert error.value.status_code == 409
    assert len(support_chat.read_messages(USER, a['id'])['messages']) == 2


def test_closed_state_is_locked_and_rechecked_and_only_staff_can_reopen(db):
    chat = create()
    for principal in (USER, NEIGHBOR):
        with pytest.raises(HTTPException) as error:
            support_chat.set_status(principal, chat['id'], 'closed')
        assert error.value.status_code == 403
    assert support_chat.set_status(STAFF, chat['id'], 'closed')['status'] == 'closed'
    with pytest.raises(HTTPException) as error:
        support_chat.send_message(USER, chat['id'], 'Too late', uuid4())
    assert error.value.status_code == 409
    assert any('FOR UPDATE OF c' in sql for sql, _ in db.calls)
    support_chat.set_status(STAFF, chat['id'], 'open')
    assert support_chat.send_message(USER, chat['id'], 'Reopened', uuid4())['author_kind'] == 'user'


def test_creation_limit_and_owner_activation_are_checked_under_lock(db):
    for i in range(5): create(subject=f'Issue {i}')
    with pytest.raises(HTTPException) as error: create()
    assert error.value.status_code == 429
    assert any('is_active FOR UPDATE' in sql for sql, _ in db.calls)
    db.conn.execute('UPDATE app_users SET is_active=0 WHERE id=9')
    with pytest.raises(HTTPException) as error: create(OTHER)
    assert error.value.status_code == 401


def test_incremental_message_pages_and_stable_inbox_pagination(db):
    chat = create()
    for i in range(104): support_chat.send_message(USER, chat['id'], f'Message {i}', uuid4())
    page = support_chat.read_messages(STAFF, chat['id'])
    assert len(page['messages']) == 100 and page['has_more']
    next_page = support_chat.read_messages(USER, chat['id'], page['messages'][-1]['id'])
    assert len(next_page['messages']) == 5 and not next_page['has_more']
    assert not {m['id'] for m in page['messages']} & {m['id'] for m in next_page['messages']}
    for i in range(24):
        row = db.conn.execute('''INSERT INTO support_chats(tenant_id,user_id,subject,request_key)
            VALUES(8,9,?,?) RETURNING id''', (f'Outside {i}', str(uuid4()))).fetchone()
        if i % 2 == 0: support_chat.set_status(STAFF, row[0], 'closed')
    a, b = support_chat.list_chats(STAFF), support_chat.list_chats(STAFF, page=2)
    assert a['total'] == b['total'] == 25
    assert [c['id'] for c in a['items']] == sorted([c['id'] for c in a['items']], reverse=True)
    assert not {c['id'] for c in a['items']} & {c['id'] for c in b['items']}
    assert support_chat.list_chats(STAFF, page=999)['page'] == 2
    assert all(c['status'] == 'closed' for c in support_chat.list_chats(STAFF, status='closed')['items'])


def test_staff_removal_demotion_and_disabled_configuration_fail_closed(db, monkeypatch):
    chat = create()
    monkeypatch.setattr(settings, 'RAG_SUPPORT_STAFF_USER_IDS', '')
    assert not support_chat.list_chats(STAFF)['enabled']
    assert support_chat.list_chats(STAFF)['total'] == 0
    assert support_chat.read_messages(USER, chat['id'])['messages']
    with pytest.raises(HTTPException) as error: create()
    assert error.value.status_code == 503
    with pytest.raises(HTTPException) as error: support_chat.read_messages(STAFF, chat['id'])
    assert error.value.status_code == 404
    monkeypatch.setattr(settings, 'RAG_SUPPORT_STAFF_USER_IDS', '10')
    assert not support_chat.is_staff(Principal(10, 99, 'reader', 'demoted'))
    for invalid in ('all', '10,', '-1', '10,other', '１０'):
        monkeypatch.setattr(settings, 'RAG_SUPPORT_STAFF_USER_IDS', invalid)
        with pytest.raises(HTTPException) as error: support_chat.staff_ids()
        assert error.value.status_code == 503


def test_message_failure_rolls_back_entire_new_chat(db, monkeypatch):
    monkeypatch.setattr(support_chat, '_insert_message', lambda *a: (_ for _ in ()).throw(RuntimeError('Test failure')))
    with pytest.raises(RuntimeError): create()
    assert support_chat.list_chats(USER)['total'] == 0


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    monkeypatch.setattr(main.app, 'dependency_overrides', {})
    with TestClient(main.app) as client: yield client


def test_api_auth_validation_csrf_and_private_cache_headers(client, db, monkeypatch):
    chat = create()
    for method, path, body in [('GET', '/support/chats', None), ('POST', '/support/chats', {}),
                              ('GET', f'/support/chats/{chat["id"]}/messages', None),
                              ('POST', f'/support/chats/{chat["id"]}/messages', {}),
                              ('PATCH', f'/support/chats/{chat["id"]}', {'status': 'closed'})]:
        assert client.request(method, path, json=body).status_code == 401
    token = 'rags_' + 'x' * 40
    monkeypatch.setattr(security, 'principal_from_api_key', lambda t: USER if t == token else None)
    client.cookies.set('rag_browser_session', token)
    payload = {'subject': 'Question', 'body': 'Hi', 'request_key': str(uuid4())}
    assert client.post('/support/chats', json=payload).status_code == 403
    response = client.post('/support/chats', json=payload, headers={'X-RAG-CSRF': '1'})
    assert response.status_code == 201 and response.headers['cache-control'] == 'no-store'
    assert client.get('/support/chats?page_size=50').status_code == 200
    for query in ('page=0', 'page_size=17', 'status=unknown'):
        assert client.get(f'/support/chats?{query}').status_code == 422
    for changes in ({'user_id': 9}, {'tenant_id': 8}, {'author_kind': 'staff'}, {'body': ' '},
                    {'body': 'x' * 4001}, {'subject': ' '}, {'request_key': 'invalid'}):
        assert client.post('/support/chats', json={**payload, **changes},
                           headers={'X-RAG-CSRF': '1'}).status_code == 422
    assert client.get(f'/support/chats/{chat["id"]}/messages?after_id=-1').status_code == 422
    monkeypatch.setattr(security, 'principal_from_api_key', lambda t: None)
    assert client.get('/support/chats').status_code == 401


def test_api_cross_tenant_support_requires_explicit_designation(client, monkeypatch):
    chat = create()
    monkeypatch.setitem(main.app.dependency_overrides, security.require_principal, lambda: STAFF)
    url = f'/support/chats/{chat["id"]}/messages'
    assert client.get(url).status_code == 200
    response = client.post(url, json={'body': 'Support reply', 'request_key': str(uuid4())})
    assert response.status_code == 201 and response.json()['author_kind'] == 'staff'
    monkeypatch.setitem(main.app.dependency_overrides, security.require_principal, lambda: NEIGHBOR)
    assert client.get(url).status_code == 404
    assert client.patch(f'/support/chats/{chat["id"]}', json={'status': 'closed'}).status_code == 403


def test_support_migration_is_additive_repeatable_and_has_owner_constraints(monkeypatch):
    statements = []
    class Connection:
        def execute(self, sql): statements.append(' '.join(sql.lower().split()))
    @contextmanager
    def connect(*args, **kwargs): yield Connection()
    monkeypatch.setattr(migrate_support.psycopg, 'connect', connect)
    monkeypatch.setattr(migrate_support, '_database_url', lambda: 'unused-test-dsn')
    migrate_support.migrate()
    first = list(statements)
    migrate_support.migrate()
    assert statements[len(first):] == first
    assert sum(s.startswith('create table if not exists') for s in first) == 2
    assert all(s.startswith(('select pg_advisory_xact_lock', 'create table if not exists',
                             'create index if not exists')) for s in first)
    assert any('foreign key(chat_id,tenant_id,user_id)' in s for s in first)
    assert any("check (author_kind='staff' or sender_user_id=user_id)" in s for s in first)
    assert any('unique(chat_id,request_key)' in s for s in first)
