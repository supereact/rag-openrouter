"""Worker authorization and terminal cleanup using only temporary uploads."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest

from app import ingestion_jobs as jobs, services

JOB = UUID('11111111-1111-4111-8111-111111111111')


class Connection:
    def __init__(self, owner, *, fail_finalization=False):
        self.owner = owner
        self.fail_finalization = fail_finalization
        self.calls = []
        self.rowcount = 1

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if self.fail_finalization and "status='failed'" in sql:
            raise RuntimeError('Synthetic finalization failure')
        return self

    def fetchone(self):
        sql, params = self.calls[-1]
        if 'RETURNING j.id' in sql:
            return JOB, 'policy.md', 7, 2, 1
        if 'SELECT role, username' in sql:
            # Model the authorization predicates, including deactivation and
            # tenant changes between upload and the worker claiming the job.
            assert params == (2, 7)
            assert 'AND is_active' in sql
            assert "role IN ('admin','editor')" in sql
            if self.owner and (self.owner['active'] and self.owner['tenant'] == 7
                               and self.owner['role'] in ('admin', 'editor')):
                return self.owner['role'], 'uploader'
        return None


@contextmanager
def connection(conn):
    yield conn


@pytest.mark.parametrize('role', ['admin', 'editor'])
def test_claim_uses_current_active_writer_identity(monkeypatch, role):
    conn = Connection({'active': True, 'tenant': 7, 'role': role})
    monkeypatch.setattr(jobs, 'db_connection', lambda: connection(conn))
    job_id, name, principal, attempt = jobs.claim_next_job()
    assert (job_id, name, attempt) == (JOB, 'policy.md', 1)
    assert (principal.user_id, principal.tenant_id, principal.role) == (2, 7, role)


@pytest.mark.parametrize('owner', [
    {'active': False, 'tenant': 7, 'role': 'editor'},
    {'active': True, 'tenant': 7, 'role': 'reader'},
    {'active': True, 'tenant': 8, 'role': 'editor'},
    None,
], ids=['deactivated', 'demoted', 'foreign-tenant', 'missing'])
def test_unauthorized_job_fails_before_reading_or_indexing(monkeypatch, tmp_path, owner):
    conn = Connection(owner)
    monkeypatch.setattr(jobs, 'db_connection', lambda: connection(conn))
    monkeypatch.setattr(jobs, 'SPOOL_DIR', tmp_path)
    staged = jobs.spool_path(JOB)
    staged.write_bytes(b'Synthetic upload that must not be read')
    read = Mock(side_effect=AssertionError('Unauthorized upload must not be read'))
    extract = Mock(side_effect=AssertionError('Extraction must not run'))
    ingest = Mock(side_effect=AssertionError('Indexing must not run'))
    monkeypatch.setattr(Path, 'open', read)
    monkeypatch.setattr(jobs, 'extract_document', extract)
    monkeypatch.setattr(jobs, 'extract_pdf_pages', extract)
    monkeypatch.setattr(services, 'ingest_document', ingest)
    monkeypatch.setattr(services, 'ingest_pdf_pages', ingest)
    assert jobs.process_one_job() is True
    read.assert_not_called()
    extract.assert_not_called()
    ingest.assert_not_called()
    assert not staged.exists()
    sql, params = conn.calls[-1]
    assert "status='failed'" in sql
    assert params == ('Upload owner is inactive or no longer permitted to ingest documents', JOB, 1)
    assert not any("available_at=now() +" in sql for sql, _ in conn.calls)


def test_authorization_finalization_failure_retains_staged_input(monkeypatch, tmp_path):
    conn = Connection({'active': False, 'tenant': 7, 'role': 'editor'}, fail_finalization=True)
    monkeypatch.setattr(jobs, 'db_connection', lambda: connection(conn))
    monkeypatch.setattr(jobs, 'SPOOL_DIR', tmp_path)
    staged = jobs.spool_path(JOB)
    staged.write_bytes(b'Synthetic staged upload')
    with pytest.raises(RuntimeError, match='Synthetic finalization failure'):
        jobs.process_one_job()
    assert staged.exists()
