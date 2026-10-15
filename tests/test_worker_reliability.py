"""No real database, uploaded content, or model required."""
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app import ingestion_jobs as jobs
from app.security import Principal
from scripts import migrate_ingestion_jobs as migration
from scripts import recover_ingestion_jobs as recover

NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)
ADMIN = Principal(user_id=1, tenant_id=7, role='admin', username='admin')
READER = Principal(user_id=2, tenant_id=7, role='reader', username='reader')
JOB = UUID('11111111-1111-4111-8111-111111111111')


class FakeConn:
    def __init__(self, results=()):
        self.calls = []
        self.results = list(results)
        self.rowcount = 1

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return self

    def fetchone(self):
        return self.results.pop(0) if self.results else None

    def fetchall(self):
        return self.results.pop(0) if self.results else []


@contextmanager
def connection(conn):
    yield conn


def test_migration_adds_retry_and_heartbeat_columns(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(migration, 'db_connection', lambda: connection(conn))
    migration.migrate()
    statement = '\n'.join(sql for sql, _ in conn.calls)
    assert 'ADD COLUMN IF NOT EXISTS attempt_count' in statement
    assert 'ADD COLUMN IF NOT EXISTS available_at' in statement
    assert 'ADD COLUMN IF NOT EXISTS heartbeat_at' in statement
    assert 'ingestion_jobs_due_idx' in statement
    assert 'DROP ' not in statement


def test_retry_delays_are_bounded():
    assert [jobs.retry_delay_seconds(n) for n in (1, 2, 3, 4)] == [15, 30, 60, 60]
    assert jobs._is_transient(TimeoutError())
    assert jobs._is_transient(ConnectionError())
    assert not jobs._is_transient(ValueError('bad pdf'))


def test_claim_requires_due_and_below_limit(monkeypatch):
    conn = FakeConn([(JOB, 'guide.md', 7, 1, 2), ('admin', 'admin')])
    monkeypatch.setattr(jobs, 'db_connection', lambda: connection(conn))
    claimed = jobs.claim_next_job()
    assert claimed == (JOB, 'guide.md', ADMIN, 2)
    statement, params = conn.calls[0]
    assert 'FOR UPDATE SKIP LOCKED' in statement
    assert 'available_at <= now()' in statement
    assert 'attempt_count < %s' in statement
    assert params == (jobs.MAX_ATTEMPTS,)


def test_health_rejects_readers_without_query(monkeypatch):
    monkeypatch.setattr(jobs, 'db_connection', lambda: pytest.fail('database should not be queried'))
    with pytest.raises(PermissionError):
        jobs.job_health(READER)


def test_health_is_tenant_scoped(monkeypatch):
    conn = FakeConn([[('queued', 2), ('completed', 7)], (1,)])
    monkeypatch.setattr(jobs, 'db_connection', lambda: connection(conn))
    result = jobs.job_health(ADMIN)
    assert result['counts']['queued'] == 2
    assert result['counts']['processing'] == 0
    assert result['stale_processing'] == 1
    assert len(conn.calls) == 2
    assert all(params[0] == ADMIN.tenant_id for _, params in conn.calls)


def test_transient_failure_schedules_retry_preserves_input(monkeypatch, tmp_path):
    from app import services
    monkeypatch.setattr(jobs, 'SPOOL_DIR', tmp_path)
    staged = jobs.spool_path(JOB)
    staged.write_bytes(b'Enough sample document text for a background ingestion test')
    monkeypatch.setattr(jobs, 'claim_next_job', lambda: (JOB, 'policy.md', ADMIN, 1))
    def broken(*args):
        raise TimeoutError('temporary dependency unavailable')
    monkeypatch.setattr(services, 'ingest_document', broken)
    conn = FakeConn()
    monkeypatch.setattr(jobs, 'db_connection', lambda: connection(conn))
    assert jobs.process_one_job() is True
    assert staged.exists()
    update, params = conn.calls[-1]
    assert "status='queued'" in update
    assert params == (15, JOB, 1)


def test_exhausted_transient_failure_is_terminal(monkeypatch, tmp_path):
    from app import services
    monkeypatch.setattr(jobs, 'SPOOL_DIR', tmp_path)
    staged = jobs.spool_path(JOB)
    staged.write_bytes(b'Enough sample document text for a background ingestion test')
    monkeypatch.setattr(jobs, 'claim_next_job', lambda: (JOB, 'policy.md', ADMIN, 3))
    def broken(*args):
        raise TimeoutError('temporary dependency unavailable')
    monkeypatch.setattr(services, 'ingest_document', broken)
    conn = FakeConn()
    monkeypatch.setattr(jobs, 'db_connection', lambda: connection(conn))
    assert jobs.process_one_job() is True
    assert not staged.exists()
    assert "status='failed'" in conn.calls[-1][0]


def test_recovery_dry_run_does_not_write(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, 'SPOOL_DIR', tmp_path)
    monkeypatch.setattr(recover, 'spool_path', jobs.spool_path)
    jobs.spool_path(JOB).write_bytes(b'private content')
    conn = FakeConn([[(JOB, 1)]])
    monkeypatch.setattr(recover, 'db_connection', lambda: connection(conn))
    assert recover.recover_stale(confirm=False)['requeue'] == 1
    assert len(conn.calls) == 1


def test_recovery_requires_workers_stopped(monkeypatch):
    with pytest.raises(ValueError, match='Stop all workers'):
        recover.recover_stale(confirm=True)
    with pytest.raises(ValueError, match='five minutes'):
        recover.recover_stale(older_than_minutes=1)


def test_confirmed_recovery_requeues_eligible_job(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, 'SPOOL_DIR', tmp_path)
    monkeypatch.setattr(recover, 'spool_path', jobs.spool_path)
    jobs.spool_path(JOB).write_bytes(b'private content')
    conn = FakeConn([[(JOB, 1)]])
    monkeypatch.setattr(recover, 'db_connection', lambda: connection(conn))
    stats = recover.recover_stale(confirm=True, workers_stopped=True)
    assert stats['requeue'] == 1
    assert "status='queued'" in conn.calls[1][0]


def test_confirmed_recovery_marks_missing_file_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, 'SPOOL_DIR', tmp_path)
    monkeypatch.setattr(recover, 'spool_path', jobs.spool_path)
    conn = FakeConn([[(JOB, 1)]])
    monkeypatch.setattr(recover, 'db_connection', lambda: connection(conn))
    stats = recover.recover_stale(confirm=True, workers_stopped=True)
    assert stats['missing_input'] == 1
    assert "status='failed'" in conn.calls[1][0]
