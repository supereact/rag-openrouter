"""Read-only production checks using synthetic configuration/storage only."""
from contextlib import contextmanager

import pytest

from scripts import check_production as preflight, migrate_starter_allowances as migration
from scripts import production_entrypoint as entrypoint


class Cursor:
    def __init__(self, value):
        self.value = value
    def fetchall(self):
        return self.value
    def fetchone(self):
        return self.value


class Database:
    def __init__(self):
        self.tables = preflight.REQUIRED_TABLES.copy()
        self.elevated, self.owner = False, False
        self.dimension, self.allowed = 'vector(384)', True
        self.calls = []
    def execute(self, sql):
        self.calls.append(sql)
        if 'SELECT tablename' in sql:
            return Cursor([(table,) for table in self.tables])
        if 'FROM pg_roles' in sql: return Cursor((self.elevated,))
        if 'tableowner=current_user' in sql: return Cursor((self.owner,))
        if 'format_type' in sql: return Cursor((self.dimension,))
        if 'has_table_privilege' in sql: return Cursor((self.allowed,))
        assert sql == 'SET TRANSACTION READ ONLY'
        return Cursor(None)
    @contextmanager
    def connect(self):
        yield self


@pytest.fixture
def configured(monkeypatch, tmp_path):
    for name, value in dict(LLM_PROVIDER='openrouter', OPENROUTER_API_KEY='synthetic-test-key',
            RAG_PAYMENTS_MODE='disabled', RAG_WALLET_ENFORCEMENT='false',
            RAG_PUBLIC_REGISTRATION_ENABLED='true').items():
        monkeypatch.setattr(preflight.settings, name, value)
    for name in ('RAG_INGEST_SPOOL', 'RAG_PDF_STORAGE_DIR', 'HF_HOME'):
        path = tmp_path / name
        path.mkdir(mode=0o700)
        monkeypatch.setenv(name, str(path))
    db = Database()
    monkeypatch.setattr(preflight, 'db_connection', db.connect)
    return db


def test_preflight_is_read_only_and_accepts_restricted_migrated_setup(configured):
    assert preflight.check() == []
    assert configured.calls[0] == 'SET TRANSACTION READ ONLY'
    assert all(sql.startswith(('SET TRANSACTION READ ONLY', 'SELECT')) for sql in configured.calls)


@pytest.mark.parametrize('field,value,expected', [
    ('tables', preflight.REQUIRED_TABLES - {'user_starter_allowances'}, 'Missing required tables'),
    ('elevated', True, 'restricted runtime role'),
    ('owner', True, 'must not own'),
    ('dimension', 'vector(768)', 'vector(384)'),
    ('allowed', False, 'read/write grants'),
])
def test_preflight_rejects_missing_migration_and_unsafe_runtime_roles(configured, field, value, expected):
    setattr(configured, field, value)
    assert any(expected in problem for problem in preflight.check())


def test_preflight_rejects_live_payments_and_inaccessible_storage(configured, monkeypatch):
    monkeypatch.setattr(preflight.settings, 'RAG_PAYMENTS_MODE', 'live')
    monkeypatch.setenv('RAG_INGEST_SPOOL', '')
    problems = preflight.check()
    assert any('payments disabled' in problem for problem in problems)
    assert any('RAG_INGEST_SPOOL' in problem for problem in problems)


def test_preflight_redacts_driver_connection_errors(configured, monkeypatch, capsys):
    @contextmanager
    def broken():
        raise RuntimeError('synthetic-secret-connection-string')
        yield
    monkeypatch.setattr(preflight, 'db_connection', broken)
    assert preflight.main() == 1
    output = capsys.readouterr().out
    assert 'Database preflight failed' in output
    assert 'synthetic-secret' not in output


def test_starter_migration_is_repeatable_ddl_without_account_backfill(monkeypatch):
    calls = []
    class Connection:
        def execute(self, sql):
            calls.append(sql)
    @contextmanager
    def connect(*args, **kwargs):
        yield Connection()
    monkeypatch.setattr(migration.psycopg, 'connect', connect)
    monkeypatch.setattr(migration, '_database_url', lambda: 'synthetic-db')
    migration.migrate()
    migration.migrate()
    assert sum('CREATE TABLE IF NOT EXISTS user_starter_allowances' in sql for sql in calls) == 2
    assert not any(sql.lstrip().startswith(('INSERT', 'UPDATE', 'DELETE', 'DROP')) for sql in calls)


@pytest.mark.parametrize('preflight_status', [0, 1])
def test_production_processes_only_start_after_preflight(monkeypatch, preflight_status):
    executed = []
    monkeypatch.setattr(entrypoint.sys, 'argv', ['entrypoint', 'python', '-m', 'scripts.ingestion_worker'])
    monkeypatch.setattr(entrypoint, 'preflight', lambda: preflight_status)
    monkeypatch.setattr(entrypoint.os, 'execvp', lambda *args: executed.append(args))
    assert entrypoint.main() == preflight_status
    assert bool(executed) is (preflight_status == 0)
