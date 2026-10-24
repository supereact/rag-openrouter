"""Direct uploads are scoped, bounded, immutable after enqueue and retry-safe."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from unittest.mock import Mock
from uuid import UUID

from fastapi.testclient import TestClient
import pytest

from app import direct_uploads as direct, main, object_storage as storage, security
from app.schemas import DirectUploadRequest
from app.security import Principal

OWNER = Principal(2, 7, 'editor', 'writer')
OTHER_USER = Principal(3, 7, 'editor', 'other')
OTHER_TENANT = Principal(2, 8, 'editor', 'outsider')
READER = Principal(4, 7, 'reader', 'reader')
JOB = UUID('11111111-1111-4111-8111-111111111111')
NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)
DATA = b'%PDF-1.4\nSynthetic direct-upload fixture'


@pytest.fixture
def state(monkeypatch):
    monkeypatch.setattr(direct.settings, 'RAG_STORAGE_BACKEND', 's3')
    monkeypatch.setattr(direct.settings, 'RAG_UPLOAD_SIGNING_KEY', 'synthetic-signing-key-for-tests-only-123456')
    monkeypatch.setattr(direct.settings, 'DATABASE_URL', 'postgresql://synthetic@ep-test.neon.tech/test')
    monkeypatch.setenv('AWS_ENDPOINT_URL_S3', 'https://br-test.storage.neon.tech')
    monkeypatch.setattr(direct, 'uuid4', lambda: JOB)
    target = Mock(return_value={'url': 'https://br-test.storage.neon.tech/rag-uploads', 'fields': {'key': storage.incoming_key(JOB)}})
    monkeypatch.setattr(storage, 'call', target)
    read = Mock(return_value=DATA)
    put = Mock()
    remove = Mock()
    monkeypatch.setattr(storage, 'read_staged_object', read)
    monkeypatch.setattr(storage, 'put_upload', put)
    monkeypatch.setattr(storage, 'remove_incoming', remove)
    state = dict(existing=None, inserted=[], commit_error=False, target=target, read=read, put=put, remove=remove, sql=[])
    class Connection:
        def execute(self, sql, args=()):
            state['sql'].append((sql,args))
            row = None
            if sql.startswith('SELECT tenant_id'):
                row = state['existing']
            elif sql.startswith('INSERT'):
                state['inserted'].append(args)
                state['existing'] = (args[1],args[2],args[3],NOW)
                row = (NOW,)
            return Mock(fetchone=lambda: row)
    @contextmanager
    def connection():
        yield Connection()
        if state['commit_error']:
            raise RuntimeError('Uncertain database commit')
    monkeypatch.setattr(direct, 'db_connection', connection)
    state['body'] = DirectUploadRequest(filename='../policy.pdf', size=len(DATA), sha256=hashlib.sha256(DATA).hexdigest())
    state['ticket'] = direct.prepare(state['body'], OWNER)['ticket']
    return state


def test_prepare_limits_policy_to_one_incoming_key_and_exact_size(state):
    options = state['target'].call_args.kwargs
    assert options['Key'] == storage.incoming_key(JOB)
    assert ['content-length-range',len(DATA),len(DATA)] in options['Conditions']
    assert options['ExpiresIn'] == direct.TTL_SECONDS
    assert options['Fields']['Cache-Control'] == 'private, no-store'
    assert direct.settings.RAG_UPLOAD_SIGNING_KEY not in json.dumps(options)
    assert not state['sql'] and not state['put'].called


@pytest.mark.parametrize('principal', [OTHER_USER,OTHER_TENANT,READER])
def test_foreign_users_tenants_and_readers_cannot_finalize(state, principal):
    with pytest.raises(PermissionError):
        direct.complete(state['ticket'], principal)
    assert not state['sql'] and not state['read'].called


@pytest.mark.parametrize('ticket', ['bad', 'bad.signature', 'bad.signature.extra', '中文.signature'])
def test_tampered_tickets_fail_before_reading_storage_or_database(state, ticket):
    with pytest.raises(ValueError, match='invalid or expired'):
        direct.complete(ticket, OWNER)
    assert not state['read'].called and not state['sql']


def test_expiration_and_changed_cloud_scope_invalidate_authorization(state, monkeypatch):
    claims = direct.claims_for(state['ticket'], OWNER)
    with monkeypatch.context() as patch:
        patch.setattr(direct.time, 'time', lambda: claims['exp'])
        with pytest.raises(ValueError):
            direct.complete(state['ticket'], OWNER)
    monkeypatch.setenv('AWS_ENDPOINT_URL_S3', 'https://another-branch.storage.neon.tech')
    with pytest.raises(ValueError):
        direct.complete(state['ticket'], OWNER)
    assert not state['read'].called


@pytest.mark.parametrize('data', [b'bad', b'X' * len(DATA)])
def test_size_and_checksum_are_verified_before_job_creation(state, data):
    state['read'].return_value = data
    with pytest.raises(ValueError, match='size and checksum'):
        direct.complete(state['ticket'], OWNER)
    assert not state['inserted'] and not state['put'].called


def test_pdf_header_checked_before_queueing(state):
    data = b'This has a PDF filename but contains plain text.'
    body = DirectUploadRequest(filename='bad.pdf', size=len(data), sha256=hashlib.sha256(data).hexdigest())
    state['read'].return_value = data
    ticket = direct.prepare(body, OWNER)['ticket']
    with pytest.raises(ValueError, match='not a PDF'):
        direct.complete(ticket, OWNER)
    assert not state['put'].called


def test_missing_upload_can_be_retried_without_creating_a_job(state):
    state['read'].side_effect = FileNotFoundError()
    with pytest.raises(ValueError, match='not reached storage'):
        direct.complete(state['ticket'], OWNER)
    assert not state['inserted'] and not state['put'].called


def test_success_freezes_input_and_replay_does_not_overwrite_a_workers_file(state):
    first = direct.complete(state['ticket'], OWNER)
    state['read'].side_effect = AssertionError('Accepted input must never be reread from the browser key')
    second = direct.complete(state['ticket'], OWNER)
    assert first == second
    assert first['filename'] == 'policy.pdf'
    assert len(state['inserted']) == 1
    state['put'].assert_called_once_with(JOB, DATA)
    assert 'pg_advisory_xact_lock' in state['sql'][0][0]
    state['remove'].assert_called_with(JOB)


def test_uncertain_commit_keeps_frozen_input_and_retry_discovers_accepted_job(state):
    state['commit_error'] = True
    with pytest.raises(RuntimeError):
        direct.complete(state['ticket'], OWNER)
    state['remove'].assert_not_called()
    state['put'].assert_called_once()
    state['commit_error'] = False
    assert direct.complete(state['ticket'], OWNER)['id'] == str(JOB)
    assert len(state['inserted']) == 1 and state['put'].call_count == 1


def test_incoming_cleanup_outage_does_not_turn_a_committed_upload_into_failure(state):
    state['remove'].side_effect = storage.StorageUnavailable('safe')
    assert direct.complete(state['ticket'], OWNER)['status'] == 'queued'
    assert len(state['inserted']) == 1


def test_unknown_existing_job_is_not_exposed_or_overwritten(state):
    state['existing'] = (99,99,'private.pdf',NOW)
    with pytest.raises(PermissionError):
        direct.complete(state['ticket'], OWNER)
    state['read'].assert_not_called()
    state['put'].assert_not_called()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    main.app.dependency_overrides.clear()
    with TestClient(main.app) as client:
        yield client
    main.app.dependency_overrides.clear()


def test_routes_require_authentication_and_a_current_writer(client, state):
    body = state['body'].model_dump()
    assert client.post('/documents/uploads/prepare',json=body).status_code == 401
    assert client.post('/documents/uploads/complete',json={'ticket':state['ticket']}).status_code == 401
    main.app.dependency_overrides[security.require_principal] = lambda: READER
    assert client.post('/documents/uploads/prepare',json=body).status_code == 403
    main.app.dependency_overrides[security.require_principal] = lambda: OWNER
    assert client.post('/documents/uploads/complete',json={'ticket':state['ticket']}).status_code == 202


@pytest.mark.parametrize('change', [{'size':0},{'size':50*1024*1024+1},{'size':True},
    {'sha256':'invalid'},{'tenant_id':99}])
def test_invalid_metadata_cannot_issue_storage_capabilities(client, state, change):
    main.app.dependency_overrides[security.require_principal] = lambda: OWNER
    calls = state['target'].call_count
    assert client.post('/documents/uploads/prepare',json={**state['body'].model_dump(),**change}).status_code == 422
    assert state['target'].call_count == calls


def test_local_mode_or_missing_signing_key_fails_closed(client, state, monkeypatch):
    main.app.dependency_overrides[security.require_principal] = lambda: OWNER
    monkeypatch.setattr(direct.settings, 'RAG_UPLOAD_SIGNING_KEY', '')
    assert client.post('/documents/uploads/prepare',json=state['body'].model_dump()).status_code == 503
