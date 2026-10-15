"""M9 local durable queue tests; do not touch the real database or model."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from app import ingestion_jobs as queue
from app.security import Principal

EDITOR = Principal(user_id=2, tenant_id=1, role='editor', username='editor')
READER = Principal(user_id=3, tenant_id=1, role='reader', username='reader')
OTHER = Principal(user_id=4, tenant_id=2, role='editor', username='outsider')
NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)


class FakeConn:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return self

    def fetchone(self):
        if callable(self.response):
            return self.response(self.calls[-1])
        return self.response

    def fetchall(self):
        return self.response or []


@contextmanager
def fake_connection(conn):
    yield conn


def test_name_normalization_and_unsupported_types():
    assert queue.safe_filename(r'docs\\internal\\guide.md') == 'guide.md'
    assert queue.safe_filename('../guide.pdf') == 'guide.pdf'
    with pytest.raises(ValueError):
        queue.safe_filename('../../secrets.exe')


def test_reader_rejected_without_writing(monkeypatch, tmp_path):
    monkeypatch.setattr(queue, 'SPOOL_DIR', tmp_path / 'spool')
    with pytest.raises(PermissionError):
        queue.queue_upload('hello.md', b'# Properly long example documentation', READER)
    assert not (tmp_path / 'spool').exists()


def test_queued_upload_scoped_to_authenticated_owner(monkeypatch, tmp_path):
    monkeypatch.setattr(queue, 'SPOOL_DIR', tmp_path / 'spool')
    connection = FakeConn(lambda call: (call[1][0], call[1][3], 'queued', NOW))
    monkeypatch.setattr(queue, 'db_connection', lambda: fake_connection(connection))
    data = b'Company policy: everyone must enable multi-factor authentication.'
    result = queue.queue_upload('folder/policy.md', data, EDITOR)
    job_uuid = UUID(result['id'])
    assert result['status'] == 'queued'
    assert result['filename'] == 'policy.md'
    assert queue.spool_path(job_uuid).read_bytes() == data
    sql, params = connection.calls[-1]
    assert 'tenant_id' in sql and 'user_id' in sql
    assert params[1:3] == (EDITOR.tenant_id, EDITOR.user_id)


def test_queue_failure_removes_staged_file(monkeypatch, tmp_path):
    monkeypatch.setattr(queue, 'SPOOL_DIR', tmp_path / 'spool')

    @contextmanager
    def fail_connection():
        raise RuntimeError('database down')
        yield

    monkeypatch.setattr(queue, 'db_connection', fail_connection)
    with pytest.raises(RuntimeError):
        queue.queue_upload('policy.md', b'Enough text for a policy document', EDITOR)
    assert list((tmp_path / 'spool').glob('*.upload')) == []


def test_job_listing_scope_in_sql(monkeypatch):
    conn = FakeConn([])
    monkeypatch.setattr(queue, 'db_connection', lambda: fake_connection(conn))
    assert queue.list_jobs(OTHER) == []
    query, parameters = conn.calls[0]
    assert 'tenant_id=%s AND user_id=%s' in query
    assert parameters[:2] == (2, 4)


def test_other_user_cannot_read_job_by_id(monkeypatch):
    conn = FakeConn(None)
    monkeypatch.setattr(queue, 'db_connection', lambda: fake_connection(conn))
    assert queue.get_job(OTHER, UUID('11111111-1111-4111-8111-111111111111')) is None
    assert conn.calls[0][1][1:] == (2, 4)


def test_worker_completes_job_and_deletes_staged_file(monkeypatch, tmp_path):
    from app import services
    monkeypatch.setattr(queue, 'SPOOL_DIR', tmp_path)
    job_id = UUID('11111111-1111-4111-8111-111111111111')
    queue.spool_path(job_id).write_bytes(b'Example paragraph that is long enough to be indexed.')
    monkeypatch.setattr(queue, 'claim_next_job', lambda: (job_id, 'test.md', EDITOR))
    captured = {}

    def ingest(title, text, principal):
        captured.update(title=title, text=text, principal=principal)
        return 54, 2, False

    monkeypatch.setattr(services, 'ingest_document', ingest)
    conn = FakeConn()
    monkeypatch.setattr(queue, 'db_connection', lambda: fake_connection(conn))
    assert queue.process_one_job()
    assert not queue.spool_path(job_id).exists()
    assert captured['principal'] == EDITOR
    assert captured['title'] == 'test.md'
    assert 'completed' in conn.calls[-1][0]
    assert conn.calls[-1][1][:3] == (54, 2, False)


def test_worker_marks_bad_file_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(queue, 'SPOOL_DIR', tmp_path)
    job_id = UUID('22222222-2222-4222-8222-222222222222')
    queue.spool_path(job_id).write_bytes(b'bad')
    monkeypatch.setattr(queue, 'claim_next_job', lambda: (job_id, 'test.md', EDITOR))
    conn = FakeConn()
    monkeypatch.setattr(queue, 'db_connection', lambda: fake_connection(conn))
    assert queue.process_one_job()
    assert 'failed' in conn.calls[-1][0]
    assert not queue.spool_path(job_id).exists()


def test_empty_queue(monkeypatch):
    monkeypatch.setattr(queue, 'claim_next_job', lambda: None)
    assert queue.process_one_job() is False


def test_pdf_worker_retains_original_for_authorized_viewing(monkeypatch, tmp_path):
    from app import services
    monkeypatch.setattr(queue, 'SPOOL_DIR', tmp_path)
    job_id = UUID('33333333-3333-4333-8333-333333333333')
    data = b'%PDF-1.4\nillustrative bytes for worker test'
    queue.spool_path(job_id).write_bytes(data)
    monkeypatch.setattr(queue, 'claim_next_job', lambda: (job_id, 'sample.pdf', EDITOR))
    monkeypatch.setattr(queue, 'extract_pdf_pages', lambda filename, pdf: [(1, 'enough text for this sample PDF')])
    monkeypatch.setattr(services, 'ingest_pdf_pages', lambda name, pages, principal: (42, 3, False))
    recorded = []
    monkeypatch.setattr(queue, 'store_pdf', lambda document_id, original: recorded.append((document_id, original)))
    connection = FakeConn()
    monkeypatch.setattr(queue, 'db_connection', lambda: fake_connection(connection))
    assert queue.process_one_job()
    assert recorded == [(42, data)]
    assert not queue.spool_path(job_id).exists()
    assert 'completed' in connection.calls[-1][0]
