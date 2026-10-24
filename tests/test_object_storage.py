"""Private object transport, worker recovery and authorization without live IO."""
from contextlib import contextmanager
from io import BytesIO
from unittest.mock import Mock
from uuid import UUID

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
import pytest

from app import ingestion_jobs as jobs, main, object_storage as storage, original_pdfs, security
from app.security import Principal
from scripts import recover_ingestion_jobs as recovery

JOB = UUID('11111111-1111-4111-8111-111111111111')
EDITOR = Principal(2, 7, 'editor', 'writer')


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setattr(storage.settings, 'RAG_STORAGE_BACKEND', 's3')
    monkeypatch.setattr(storage.settings, 'RAG_DOCUMENTS_BUCKET', 'rag-documents')
    monkeypatch.setattr(storage.settings, 'RAG_UPLOADS_BUCKET', 'rag-uploads')
    client = Mock()
    monkeypatch.setattr(storage, 'client', lambda: client)
    return client


def error(code):
    return ClientError({'Error': {'Code': code, 'Message': 'synthetic-private-driver-detail'}}, 'GetObject')


def test_client_requires_explicit_credentials_and_uses_sigv4_path_style(monkeypatch):
    import boto3
    storage.client.cache_clear()
    monkeypatch.setenv('AWS_ENDPOINT_URL_S3', 'https://br-test.storage.c-1.ap-southeast-1.aws.neon.tech')
    monkeypatch.setenv('AWS_REGION', 'ap-southeast-1')
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'synthetic-access')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'synthetic-secret')
    factory = Mock()
    monkeypatch.setattr(boto3, 'client', factory)
    try:
        storage.client()
        options = factory.call_args.kwargs
        assert options['config'].signature_version == 's3v4'
        assert options['config'].s3 == {'addressing_style': 'path'}
        assert options['aws_access_key_id'] == 'synthetic-access'
        storage.client.cache_clear()
        monkeypatch.setenv('AWS_ENDPOINT_URL_S3', 'http://untrusted.example')
        with pytest.raises(storage.StorageUnavailable):
            storage.client()
        assert factory.call_count == 1
    finally:
        storage.client.cache_clear()


@pytest.mark.parametrize('code', ['AccessDenied', 'SlowDown', 'NoSuchBucket'])
def test_sdk_errors_are_sanitized_and_retryable(s3, code):
    s3.get_object.side_effect = error(code)
    with pytest.raises(storage.StorageUnavailable) as caught:
        storage.read_upload(JOB)
    assert 'synthetic-private' not in str(caught.value)
    assert jobs._is_transient(caught.value)


def test_missing_objects_differ_from_storage_outages(s3):
    s3.head_object.side_effect = error('NoSuchKey')
    assert not storage.upload_exists(JOB)
    assert storage.find_pdf(17) is None
    s3.head_object.side_effect = error('AccessDenied')
    with pytest.raises(storage.StorageUnavailable):
        storage.upload_exists(JOB)


def test_read_is_bounded_and_closes_the_object(s3, monkeypatch):
    monkeypatch.setattr(storage, 'MAX_FILE_BYTES', 4)
    body = BytesIO(b'12345')
    s3.get_object.return_value = {'Body': body, 'ContentLength': 5}
    with pytest.raises(ValueError, match='size limit'):
        storage.read_upload(JOB)
    assert body.closed
    body = BytesIO(b'12345')
    s3.get_object.return_value = {'Body': body}  # Do not trust a missing length.
    with pytest.raises(ValueError, match='size limit'):
        storage.read_upload(JOB)
    assert body.closed


def test_private_original_keys_never_use_uploaded_filenames(s3):
    original_pdfs.store_pdf(17, b'%PDF-1.4\nsynthetic')
    call = s3.put_object.call_args.kwargs
    assert call['Key'] == 'originals/17.pdf'
    assert call['Bucket'] == 'rag-documents'
    assert call['CacheControl'] == 'private, no-store'
    assert 'ACL' not in call
    with pytest.raises(ValueError):
        original_pdfs.store_pdf(0, b'%PDF-1.4\nsynthetic')


def test_denied_document_never_probes_object_storage(s3, monkeypatch):
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = None
    @contextmanager
    def database():
        yield connection
    monkeypatch.setattr(original_pdfs, 'db_connection', database)
    assert original_pdfs.authorized_pdf(EDITOR, 17) is None
    s3.head_object.assert_not_called()
    assert 'document_acl' in connection.execute.call_args.args[0]


def test_queue_persists_remote_input_before_scoped_metadata_and_cleans_up_failure(s3, monkeypatch):
    monkeypatch.setattr(jobs, 'uuid4', lambda: JOB)
    monkeypatch.setattr(jobs, 'spool_path', lambda _: pytest.fail('Remote mode must not touch local files'))
    seen = []
    def insert(job_id, title, principal):
        assert s3.put_object.called
        seen.append((job_id, title, principal))
        return {'id': str(job_id), 'status': 'queued'}
    monkeypatch.setattr(jobs, '_insert_job', insert)
    assert jobs.queue_upload('../guide.md', b'Synthetic document content', EDITOR)['status'] == 'queued'
    assert seen == [(JOB, 'guide.md', EDITOR)]
    assert s3.put_object.call_args.kwargs['Key'] == f'staged/{JOB.hex}.upload'
    monkeypatch.setattr(jobs, '_insert_job', Mock(side_effect=RuntimeError('DB unavailable')))
    with pytest.raises(RuntimeError):
        jobs.queue_upload('guide.md', b'Synthetic document content', EDITOR)
    assert s3.delete_object.call_args.kwargs['Key'] == f'staged/{JOB.hex}.upload'


def test_worker_reads_remote_input_and_retains_it_when_finalization_fails(s3, monkeypatch):
    from app import services
    monkeypatch.setattr(jobs, 'claim_next_job', lambda: (JOB, 'guide.md', EDITOR, 1))
    s3.get_object.return_value = {'Body': BytesIO(b'Synthetic policy text for indexing.'), 'ContentLength': 34}
    monkeypatch.setattr(services, 'ingest_document', lambda *args: (17, 1, False))
    @contextmanager
    def unavailable():
        raise RuntimeError('DB unavailable')
        yield
    monkeypatch.setattr(jobs, 'db_connection', unavailable)
    with pytest.raises(RuntimeError):
        jobs.process_one_job()
    s3.delete_object.assert_not_called()


def test_recovery_checks_remote_input(s3, monkeypatch):
    monkeypatch.setattr(recovery, 'spool_path', lambda _: pytest.fail('Local spool must not be probed'))
    assert recovery.classify_stale(JOB, 1) == 'requeue'
    assert recovery.classify_stale(JOB, jobs.MAX_ATTEMPTS) == 'exhausted'
    s3.head_object.side_effect = error('NoSuchKey')
    assert recovery.classify_stale(JOB, 1) == 'missing_input'


def test_private_pdf_stream_and_range_keep_authorization_and_close_body(s3, monkeypatch):
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    monkeypatch.setattr(main, 'authorized_pdf', lambda *args: (storage.RemotePDF('originals/17.pdf', 20), '中文.pdf'))
    main.app.dependency_overrides[security.require_principal] = lambda: EDITOR
    body = Mock()
    body.iter_chunks.return_value = iter([b'%PDF'])
    s3.get_object.return_value = {'Body': body, 'ContentLength': 4, 'ContentRange': 'bytes 0-3/20'}
    try:
        with TestClient(main.app) as client:
            response = client.get('/documents/17/original-pdf', headers={'Range': 'bytes=0-3'})
            assert response.status_code == 206 and response.content == b'%PDF'
            assert response.headers['content-range'] == 'bytes 0-3/20'
            assert response.headers['cache-control'] == 'private, no-store'
            assert 'filename*=utf-8' in response.headers['content-disposition']
            body.close.assert_called_once()
            calls = s3.get_object.call_count
            response = client.get('/documents/17/original-pdf', headers={'Range': 'bytes=0-1,3-4'})
            assert response.status_code == 416
            assert response.headers['content-range'] == 'bytes */20'
            assert s3.get_object.call_count == calls
    finally:
        main.app.dependency_overrides.clear()


def test_storage_outage_returns_generic_503(s3, monkeypatch):
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    monkeypatch.setattr(main, 'authorized_pdf', Mock(side_effect=storage.StorageUnavailable('safe')))
    main.app.dependency_overrides[security.require_principal] = lambda: EDITOR
    try:
        with TestClient(main.app) as client:
            response = client.get('/documents/17/original-pdf')
            assert response.status_code == 503
            assert response.json() == {'detail': 'Private document storage is temporarily unavailable'}
    finally:
        main.app.dependency_overrides.clear()
