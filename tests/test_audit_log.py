"""Audit SQL runs against a temporary relational fixture; no application data."""
from contextlib import contextmanager
from datetime import date, datetime
import sqlite3

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import audit_log, main, security
from app.security import Principal

ADMIN = Principal(1,7,'admin','admin')
READER = Principal(2,7,'reader','reader')
OTHER = Principal(9,8,'admin','outside')


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:', check_same_thread=False)
        self.calls = []
        self.conn.executescript('''
          CREATE TABLE app_users(id INTEGER,tenant_id INTEGER,username TEXT);
          CREATE TABLE documents(id INTEGER,tenant_id INTEGER,title TEXT);
          CREATE TABLE audit_events(id INTEGER,tenant_id INTEGER,user_id INTEGER,action TEXT,
            document_id INTEGER,result_count INTEGER,created_at TEXT);
          INSERT INTO app_users VALUES(1,7,'admin'),(2,7,'reader'),(9,8,'outside');
          INSERT INTO documents VALUES(11,7,'Policy.pdf'),(99,8,'Foreign.pdf');
          INSERT INTO audit_events VALUES
            (1,7,1,'document.create',11,5,'2026-10-16T00:00:00+00:00'),
            (2,7,2,'search',NULL,0,'2026-10-16T23:59:59.999999+00:00'),
            (3,7,1,'document.delete',12,NULL,'2026-10-17T00:00:00+00:00'),
            (4,7,1,'document.access.update',11,2,'2026-10-17T00:00:00+00:00'),
            (5,8,9,'outside-only',99,8,'2026-10-18T00:00:00+00:00');
        ''')

    def execute(self, sql, args=()):
        self.calls.append((sql,args))
        if sql.startswith('SET TRANSACTION'): return None
        return self.conn.execute(sql.replace('%s','?'), tuple(value.isoformat() if isinstance(value,datetime) else value for value in args))

    @contextmanager
    def connect(self):
        with self.conn: yield self


@pytest.fixture
def db(monkeypatch):
    database = Database()
    monkeypatch.setattr(audit_log,'db_connection',database.connect)
    yield database
    database.conn.close()


def test_admin_paged_history_preserves_ties_deleted_documents_and_zero_results(db):
    result = audit_log.list_events(ADMIN)
    assert result['total'] == 4
    assert [item['id'] for item in result['items']] == [4,3,2,1]
    assert result['items'][1]['document_id'] == 12
    assert result['items'][1]['document_title'] is None
    assert result['items'][2]['result_count'] == 0
    assert result['items'][3]['document_title'] == 'Policy.pdf'
    assert result['users'] == [{'id':1,'username':'admin'},{'id':2,'username':'reader'}]
    assert 'outside-only' not in result['actions']
    assert db.calls[0][0].endswith('REPEATABLE READ READ ONLY')
    assert not any(sql.lstrip().startswith(('INSERT','UPDATE','DELETE')) for sql,_ in db.calls)


def test_tenant_boundaries_filter_counts_options_and_document_titles(db):
    assert audit_log.list_events(OTHER)['total'] == 1
    assert audit_log.list_events(OTHER)['actions'] == ['outside-only']
    assert audit_log.list_events(ADMIN,user_id=9)['total'] == 0
    assert audit_log.list_events(ADMIN,action='outside-only')['total'] == 0
    # Malformed legacy references cannot expose a foreign user's name/title.
    db.conn.execute("INSERT INTO audit_events VALUES(6,7,9,'invalid-user',99,NULL,'2026-10-19T00:00:00+00:00')")
    db.conn.execute("INSERT INTO audit_events VALUES(7,7,1,'invalid-document',99,NULL,'2026-10-19T00:00:00+00:00')")
    result = audit_log.list_events(ADMIN)
    assert result['total'] == 5
    assert result['items'][0]['document_title'] is None
    assert all(item['username'] != 'outside' for item in result['items'])
    assert 'invalid-user' not in result['actions']


@pytest.mark.parametrize('principal',[READER,Principal(3,7,'editor','editor')])
def test_non_admin_rejected_before_database(db,principal):
    with pytest.raises(HTTPException) as error: audit_log.list_events(principal)
    assert error.value.status_code == 403
    assert db.calls == []


def test_action_user_and_inclusive_utc_date_filters(db):
    assert audit_log.list_events(ADMIN,date_from=date(2026,10,16),date_to=date(2026,10,16))['total'] == 2
    result = audit_log.list_events(ADMIN,action='search',user_id=2,date_from=date(2026,10,16),date_to=date(2026,10,16))
    assert [item['id'] for item in result['items']] == [2]
    assert audit_log.list_events(ADMIN,date_from=date(2026,10,17))['total'] == 2
    assert audit_log.list_events(ADMIN,action="search' OR 1=1 --")['total'] == 0
    with pytest.raises(ValueError): audit_log.list_events(ADMIN,date_from=date(2026,10,17),date_to=date(2026,10,16))


def test_pagination_and_stable_order_with_equal_timestamps(db):
    db.conn.executemany('INSERT INTO audit_events VALUES(?,?,?,?,?,?,?)',[(i,7,1,'search',None,1,'2026-10-17T00:00:00+00:00') for i in range(10,51)])
    first = audit_log.list_events(ADMIN)
    second = audit_log.list_events(ADMIN,page=2)
    assert first['total'] == second['total'] == 45
    assert first['items'][0]['id'] == 50
    assert len(first['items']) == len(second['items']) == 20
    assert not {i['id'] for i in first['items']} & {i['id'] for i in second['items']}
    assert audit_log.list_events(ADMIN,page=99)['page'] == 3
    assert audit_log.list_events(ADMIN,page_size=50)['pages'] == 1
    assert audit_log.list_events(ADMIN,action='none',page=99)['page'] == 1


@pytest.fixture
def client(db,monkeypatch):
    monkeypatch.setattr(main,'warmup_local_models',lambda:None)
    monkeypatch.setattr(main.app,'dependency_overrides',{})
    with TestClient(main.app) as client: yield client


def test_endpoint_requires_admin_and_validates_filters(client,db):
    assert client.get('/admin/audit-log').status_code == 401
    main.app.dependency_overrides[security.require_principal] = lambda: READER
    assert client.get('/admin/audit-log').status_code == 403
    assert db.calls == []
    main.app.dependency_overrides[security.require_principal] = lambda: ADMIN
    for query in ('page=0','page_size=21','page_size=500','user_id=0','date_from=invalid',
                  'date_from=2026-10-17&date_to=2026-10-16','action='+'x'*121):
        assert client.get('/admin/audit-log?'+query).status_code == 422
    response = client.get('/admin/audit-log?page_size=20&action=search&user_id=2&date_from=2026-10-16&date_to=2026-10-16')
    assert response.status_code == 200
    assert response.json()['total'] == 1
    assert set(response.json()['items'][0]) == {'id','created_at','user_id','username','action','document_id','document_title','result_count'}


def test_endpoint_never_uses_client_supplied_tenant(client):
    main.app.dependency_overrides[security.require_principal] = lambda: OTHER
    result = client.get('/admin/audit-log?tenant_id=7').json()
    assert result['total'] == 1
    assert result['items'][0]['username'] == 'outside'
