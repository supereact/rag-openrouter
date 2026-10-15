"""HTTP contract and auth regression tests for the M9 ingestion queue."""
from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from app import main, security
from app.security import Principal

ADMIN = Principal(1, 1, 'admin', 'admin')
READER = Principal(2, 1, 'reader', 'reader')


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    main.app.dependency_overrides.clear()
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()


def test_requires_authentication(client):
    assert client.post('/documents/upload-async', files={'file': ('x.md', b'long text enough for testing')}).status_code == 401
    assert client.get('/ingestion-jobs').status_code == 401
    assert client.get('/ingestion-jobs/11111111-1111-4111-8111-111111111111').status_code == 401


def test_reader_cannot_queue_file(client):
    main.app.dependency_overrides[security.require_principal] = lambda: READER
    assert client.post('/documents/upload-async', files={'file': ('x.md', b'sample long text')}).status_code == 403


def test_editor_queues_with_authenticated_identity(monkeypatch, client):
    main.app.dependency_overrides[security.require_principal] = lambda: ADMIN
    seen = {}

    def fake_queue(name, data, principal):
        seen.update(name=name, data=data, principal=principal)
        return dict(id='11111111-1111-4111-8111-111111111111',
                    filename='policy.md', status='queued',
                    created_at=datetime.now(timezone.utc))

    monkeypatch.setattr(main, 'queue_upload', fake_queue)
    result = client.post('/documents/upload-async', files={'file': ('policy.md', b'valid contents for test')})
    assert result.status_code == 202
    assert result.json()['status'] == 'queued'
    assert seen['principal'] == ADMIN


def test_hidden_job_returns_404(monkeypatch, client):
    main.app.dependency_overrides[security.require_principal] = lambda: ADMIN
    monkeypatch.setattr(main, 'get_job', lambda principal, job_id: None)
    response = client.get('/ingestion-jobs/11111111-1111-4111-8111-111111111111')
    assert response.status_code == 404


def test_ingestion_health_requires_admin_and_is_tenant_scoped(monkeypatch, client):
    assert client.get('/ingestion-health').status_code == 401
    main.app.dependency_overrides[security.require_principal] = lambda: READER
    assert client.get('/ingestion-health').status_code == 403
    main.app.dependency_overrides[security.require_principal] = lambda: ADMIN
    observed = []

    def fake_health(principal):
        observed.append(principal)
        return {
            'counts': {'queued': 1, 'processing': 0, 'completed': 4, 'failed': 0},
            'stale_processing': 0, 'stale_threshold_minutes': 10,
        }

    monkeypatch.setattr(main, 'job_health', fake_health)
    response = client.get('/ingestion-health')
    assert response.status_code == 200
    assert response.json()['counts']['queued'] == 1
    assert observed == [ADMIN]
