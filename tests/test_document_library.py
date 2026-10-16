"""Exercise library SQL against an ephemeral relational fixture, without PostgreSQL.

Only PostgreSQL placeholder/cast/ANY syntax is adapted; authorization, union,
filters, ordering, counts and pagination execute the production query unchanged.
"""
from contextlib import contextmanager
from unittest.mock import Mock
import sqlite3
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app import document_library as library, ingestion_jobs as jobs, main, security
from app.security import Principal

ADMIN = Principal(1, 7, 'admin', 'admin')
OWNER = Principal(2, 7, 'editor', 'owner')
READER = Principal(3, 7, 'reader', 'reader')
OTHER = Principal(9, 8, 'admin', 'outside')
JOB = UUID('00000000-0000-0000-0000-000000000001')


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:', check_same_thread=False)
        self.conn.create_function('strpos', 2, lambda text, part: text.find(part) + 1)
        self.calls = []
        self.conn.executescript('''
          CREATE TABLE documents(id INTEGER,tenant_id INTEGER,owner_user_id INTEGER,title TEXT,created_at TEXT);
          CREATE TABLE ingestion_jobs(id TEXT,tenant_id INTEGER,user_id INTEGER,filename TEXT,status TEXT,created_at TEXT,error TEXT);
          CREATE TABLE document_acl(document_id INTEGER,tenant_id INTEGER,user_id INTEGER);
          CREATE TABLE app_users(id INTEGER,tenant_id INTEGER,username TEXT);
        ''')
        self.conn.executemany('INSERT INTO documents VALUES(?,?,?,?,?)', [
            (11, 7, 2, 'Report.PDF', '2026-10-16T00:00:00Z'),
            (12, 7, 1, 'Private.md', '2026-10-16T00:00:00Z'),
            (99, 8, 9, 'Foreign.txt', '2026-10-17T00:00:00Z'),
        ])
        self.conn.executemany('INSERT INTO ingestion_jobs VALUES(?,?,?,?,?,?,?)', [
            (str(JOB), 7, 2, 'Pending.txt', 'failed', '2026-10-17T00:00:00Z', 'Synthetic failure'),
            ('own-reader', 7, 3, 'Own.txt', 'queued', '2026-10-15T00:00:00Z', None),
            ('processing', 7, 1, 'Import.md', 'processing', '2026-10-15T00:00:00Z', None),
            ('completed', 7, 2, 'Report.PDF', 'completed', '2026-10-18T00:00:00Z', None),
            ('deleted', 7, 2, 'Deleted.pdf', 'completed', '2026-10-18T00:00:00Z', None),
            ('outside', 8, 9, 'Foreign.txt', 'failed', '2026-10-19T00:00:00Z', None),
        ])
        self.conn.executemany('INSERT INTO app_users VALUES(?,?,?)', [(1, 7, 'admin'), (2, 7, 'owner'), (3, 7, 'reader'), (9, 8, 'outside')])
        self.conn.execute('INSERT INTO document_acl VALUES(11,7,3)')
        self.conn.commit()

    def execute(self, sql, args=()):
        self.calls.append((sql, args))
        if sql.startswith('SET TRANSACTION'):
            return None
        if 'ANY(%s)' in sql:
            tenant, ids = args
            sql = sql.replace('=ANY(%s)', ' IN (' + ','.join('?' for _ in ids) + ')')
            args = (tenant, *ids)
        sql = sql.replace('d.id::text', 'CAST(d.id AS TEXT)').replace('j.id::text', 'CAST(j.id AS TEXT)')
        sql = sql.replace('::text', '').replace('%s', '?').replace(' FOR UPDATE', '')
        return self.conn.execute(sql, tuple(str(arg) if isinstance(arg, UUID) else arg for arg in args))

    @contextmanager
    def connect(self):
        with self.conn:
            yield self


@pytest.fixture
def db(monkeypatch, tmp_path):
    database = Database()
    monkeypatch.setattr(library, 'db_connection', database.connect)
    monkeypatch.setattr(jobs, 'db_connection', database.connect)
    monkeypatch.setattr(jobs, 'SPOOL_DIR', tmp_path)
    yield database
    database.conn.close()


def test_union_excludes_completed_jobs_and_batches_page_recipients(db):
    result = library.list_library(ADMIN)
    assert result['total'] == 5
    assert [row['title'] for row in result['items']] == ['Pending.txt', 'Private.md', 'Report.PDF', 'Import.md', 'Own.txt']
    by_title = {row['title']: row for row in result['items']}
    assert by_title['Report.PDF']['assigned_users'] == [{'id': 3, 'username': 'reader'}]
    assert by_title['Private.md']['assigned_users'] == []
    assert by_title['Pending.txt']['assigned_users'] is None
    assert sum('JOIN app_users' in sql for sql, _ in db.calls) == 1
    assert db.calls[0][0].endswith('REPEATABLE READ READ ONLY')


def test_reader_acl_visibility_and_recipient_privacy(db):
    result = library.list_library(READER)
    assert result['total'] == 2
    assert {row['title'] for row in result['items']} == {'Report.PDF', 'Own.txt'}
    assert all(row['assigned_users'] is None and not row['can_manage'] for row in result['items'])
    assert not any('JOIN app_users' in sql for sql, _ in db.calls)
    # Search/count must not reveal private or foreign metadata.
    for q in ('Private', 'Foreign'):
        assert library.list_library(READER, q=q)['total'] == 0


def test_editor_jobs_remain_owner_scoped_and_tenants_do_not_mix(db):
    assert {row['title'] for row in library.list_library(OWNER)['items']} == {'Report.PDF', 'Pending.txt'}
    assert {row['title'] for row in library.list_library(OTHER)['items']} == {'Foreign.txt'}
    assert library.list_library(ADMIN, q='Foreign')['total'] == 0


@pytest.mark.parametrize('options,expected', [
    ({'q': 'REPORT', 'file_type': 'pdf', 'status': 'indexed'}, ['Report.PDF']),
    ({'status': 'failed'}, ['Pending.txt']),
    ({'status': 'processing', 'file_type': 'md'}, ['Import.md']),
    ({'q': '%'}, []), ({'q': '_'}, []), ({'file_type': 'txt'}, ['Pending.txt', 'Own.txt']),
])
def test_filters_combine_and_search_is_literal(db, options, expected):
    result = library.list_library(ADMIN, **options)
    assert [row['title'] for row in result['items']] == expected
    assert result['total'] == len(expected)


def test_pagination_stable_ties_counts_and_page_clamping(db):
    db.conn.executemany('INSERT INTO documents VALUES(?,?,?,?,?)', [(i, 7, 2, f'Doc{i}.txt', '2026-10-16T00:00:00Z') for i in range(100, 141)])
    one = library.list_library(ADMIN)
    two = library.list_library(ADMIN, page=2)
    assert one['total'] == two['total'] == 46
    assert one['pages'] == 3
    keys = lambda result: [(r['kind'], r['id']) for r in result['items']]
    assert len(one['items']) == len(two['items']) == 20
    assert not set(keys(one)) & set(keys(two))
    assert keys(one) == keys(library.list_library(ADMIN))
    assert library.list_library(ADMIN, page=99)['page'] == 3
    assert library.list_library(ADMIN, page=99, q='missing')['page'] == 1
    assert len(library.list_library(ADMIN, page_size=50)['items']) == 46


@pytest.mark.parametrize('principal', [OWNER, ADMIN])
def test_failed_upload_removal_cleans_only_job_and_staged_input(db, principal):
    path = jobs.spool_path(JOB)
    path.write_bytes(b'synthetic upload')
    jobs.remove_failed_job(principal, JOB)
    assert not path.exists()
    assert db.conn.execute('SELECT count(*) FROM ingestion_jobs WHERE id=?', (str(JOB),)).fetchone()[0] == 0
    assert db.conn.execute('SELECT count(*) FROM documents').fetchone()[0] == 3
    assert any('FOR UPDATE' in sql for sql, _ in db.calls)


@pytest.mark.parametrize('principal', [READER, OTHER, Principal(4, 7, 'editor', 'unrelated')])
def test_failed_removal_authorization(db, principal):
    with pytest.raises(PermissionError):
        jobs.remove_failed_job(principal, JOB)
    assert db.conn.execute('SELECT count(*) FROM ingestion_jobs WHERE id=?', (str(JOB),)).fetchone()[0] == 1


@pytest.mark.parametrize('status', ['queued', 'processing', 'completed'])
def test_status_is_rechecked_under_lock_before_cleanup(db, monkeypatch, status):
    db.conn.execute('UPDATE ingestion_jobs SET status=? WHERE id=?', (status, str(JOB)))
    cleanup = Mock()
    monkeypatch.setattr(jobs, 'spool_path', cleanup)
    with pytest.raises(ValueError, match='Only failed'):
        jobs.remove_failed_job(OWNER, JOB)
    cleanup.assert_not_called()


def test_cleanup_failure_preserves_record_and_staged_file(db, monkeypatch):
    path = jobs.spool_path(JOB)
    path.write_bytes(b'synthetic')
    broken = Mock()
    broken.unlink.side_effect = OSError('Synthetic permission failure')
    monkeypatch.setattr(jobs, 'spool_path', lambda _: broken)
    with pytest.raises(OSError):
        jobs.remove_failed_job(ADMIN, JOB)
    assert path.exists()
    assert db.conn.execute('SELECT status FROM ingestion_jobs WHERE id=?', (str(JOB),)).fetchone() == ('failed',)


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    monkeypatch.setattr(main.app, 'dependency_overrides', {})
    with TestClient(main.app) as client:
        yield client


def test_routes_authentication_and_typed_query_validation(client):
    assert client.get('/documents/library').status_code == 401
    assert client.delete(f'/ingestion-jobs/{JOB}').status_code == 401
    main.app.dependency_overrides[security.require_principal] = lambda: READER
    assert client.delete(f'/ingestion-jobs/{JOB}').status_code == 403
    assert client.get('/documents/library?page_size=20').json()['total'] == 2
    for query in ('page=0', 'page_size=21', 'page_size=500', 'status=completed', 'file_type=exe', 'q=' + 'x' * 201):
        assert client.get('/documents/library?' + query).status_code == 422


def test_removal_routes_not_found_conflict_and_success(client, db):
    main.app.dependency_overrides[security.require_principal] = lambda: OTHER
    assert client.delete(f'/ingestion-jobs/{JOB}').status_code == 404
    main.app.dependency_overrides[security.require_principal] = lambda: ADMIN
    db.conn.execute("UPDATE ingestion_jobs SET status='processing' WHERE id=?", (str(JOB),))
    db.conn.commit()
    assert client.delete(f'/ingestion-jobs/{JOB}').status_code == 409
    db.conn.execute("UPDATE ingestion_jobs SET status='failed' WHERE id=?", (str(JOB),))
    db.conn.commit()
    assert client.delete(f'/ingestion-jobs/{JOB}').status_code == 204
    assert client.delete(f'/ingestion-jobs/{JOB}').status_code == 404


def test_cleanup_route_is_retryable_and_preserves_record(client, monkeypatch):
    main.app.dependency_overrides[security.require_principal] = lambda: ADMIN
    broken = Mock()
    broken.unlink.side_effect = OSError('Synthetic cleanup failure')
    monkeypatch.setattr(jobs, 'spool_path', lambda _: broken)
    assert client.delete(f'/ingestion-jobs/{JOB}').status_code == 503
    assert client.get('/documents/library?status=failed').json()['total'] == 1
