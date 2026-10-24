"""Schema runner orchestration only: all migration/DB operations are mocked."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from scripts import setup_database as setup


@pytest.fixture
def database(monkeypatch):
    state = dict(existing=False, locked=True, closed=False, steps=[], queries=[])
    class Connection:
        def execute(self, sql, args=()):
            state['queries'].append(sql)
            value = state['locked'] if 'pg_try_advisory_lock' in sql else state['existing']
            return SimpleNamespace(fetchone=lambda: (value,))
    @contextmanager
    def connect(*args, **kwargs):
        assert kwargs['autocommit'] is True
        try:
            yield Connection()
        finally:
            state['closed'] = True
    monkeypatch.setattr(setup.psycopg, 'connect', connect)
    monkeypatch.setattr(setup, '_database_url', lambda: 'synthetic-database')
    monkeypatch.setattr(setup, 'init_database', lambda: state['steps'].append('init_db'))
    monkeypatch.setattr(setup.importlib, 'import_module', lambda name:
        SimpleNamespace(migrate=lambda: state['steps'].append(name.removeprefix('scripts.'))))
    return state


def test_default_is_offline_preview(monkeypatch, capsys):
    monkeypatch.setattr(setup, '_database_url', lambda: pytest.fail('Preview must not read DB configuration'))
    monkeypatch.setattr(setup.psycopg, 'connect', lambda *args, **kwargs: pytest.fail('Preview must not connect'))
    assert setup.main([]) == 0
    assert 'Preview only' in capsys.readouterr().out


def test_fresh_schema_reuses_migrations_in_dependency_order(database):
    setup.apply_schema()
    assert tuple(database['steps']) == setup.STEPS
    assert database['closed']
    assert 'pg_try_advisory_lock' in database['queries'][0]
    assert setup.STEPS.index('migrate_security') < setup.STEPS.index('migrate_accounts')
    assert setup.STEPS.index('migrate_credit_budgets') < setup.STEPS.index('migrate_starter_allowances')
    assert setup.STEPS.index('migrate_conversations') < setup.STEPS.index('migrate_answer_feedback')


def test_nonempty_database_needs_explicit_upgrade_flag(database):
    database['existing'] = True
    with pytest.raises(RuntimeError, match='--upgrade'):
        setup.apply_schema()
    assert database['steps'] == [] and database['closed']
    setup.apply_schema(upgrade=True)
    assert tuple(database['steps']) == setup.STEPS


def test_concurrent_runner_refuses_to_apply(database):
    database['locked'] = False
    with pytest.raises(RuntimeError, match='already running'):
        setup.apply_schema(upgrade=True)
    assert database['steps'] == [] and database['closed']


def test_failure_stops_later_steps_and_closes_lock_connection(database, monkeypatch):
    def failed():
        raise RuntimeError('Synthetic secret connection parameters')
    monkeypatch.setattr(setup, 'init_database', failed)
    with pytest.raises(RuntimeError):
        setup.apply_schema()
    assert database['steps'] == [] and database['closed']


def test_cli_redacts_database_errors_and_supports_repeatable_upgrade(database, monkeypatch, capsys):
    database['existing'] = True
    assert setup.main(['--apply', '--upgrade']) == 0
    assert setup.main(['--apply', '--upgrade']) == 0
    assert tuple(database['steps']) == setup.STEPS * 2
    def failed(**kwargs):
        raise RuntimeError('synthetic-secret-database-password')
    monkeypatch.setattr(setup, 'apply_schema', failed)
    assert setup.main(['--apply']) == 1
    assert 'synthetic-secret' not in capsys.readouterr().out


def test_optional_keyword_index_is_explicit(database):
    setup.apply_schema(fts_index=True)
    assert 'CREATE INDEX IF NOT EXISTS idx_chunks_fts_en' in database['queries'][-1]
