"""M9.2 privacy and original-file lifecycle regression tests."""
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app import main, original_pdfs, security
from app.security import Principal

OWNER = Principal(1, 1, 'editor', 'owner')
OUTSIDER = Principal(7, 2, 'reader', 'outsider')


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    main.app.dependency_overrides.clear()
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


def test_private_atomic_pdf_storage(monkeypatch, tmp_path):
    root = tmp_path / 'private'
    monkeypatch.setattr(original_pdfs, 'PDF_DIR', root)
    original_pdfs.store_pdf(11, b'%PDF-1.7\noriginal')
    assert (root / '11.pdf').read_bytes() == b'%PDF-1.7\noriginal'
    original_pdfs.store_pdf(11, b'%PDF-1.7\nreplacement')
    assert (root / '11.pdf').read_bytes() == b'%PDF-1.7\nreplacement'
    assert list(root.glob('*.tmp')) == []
    original_pdfs.remove_pdf(11)
    assert not (root / '11.pdf').exists()


def test_storage_never_uses_filename_or_invalid_ids(monkeypatch, tmp_path):
    monkeypatch.setattr(original_pdfs, 'PDF_DIR', tmp_path)
    with pytest.raises(ValueError):
        original_pdfs.store_pdf(0, b'%PDF-1.7\n')
    with pytest.raises(ValueError):
        original_pdfs.store_pdf(1, b'not really a PDF')


def test_authorization_checked_before_file_lookup(monkeypatch):
    calls = []

    class FakeConnection:
        def execute(self, sql, args):
            calls.append((sql, args))
            return self

        def fetchone(self):
            return None

    @contextmanager
    def fake_db():
        yield FakeConnection()

    monkeypatch.setattr(original_pdfs, 'db_connection', fake_db)
    monkeypatch.setattr(original_pdfs, '_pdf_path', lambda _: pytest.fail('File probed before authorization'))
    assert original_pdfs.authorized_pdf(OUTSIDER, 11) is None
    assert 'document_acl' in calls[0][0]
    assert calls[0][1] == (11, 2, 7, 'reader', 7)


def test_unauthenticated_pdf_denied(client):
    assert client.get('/documents/11/original-pdf').status_code == 401


def test_inaccessible_pdf_returns_404(monkeypatch, client):
    main.app.dependency_overrides[security.require_principal] = lambda: OUTSIDER
    monkeypatch.setattr(main, 'authorized_pdf', lambda principal, doc_id: None)
    response = client.get('/documents/11/original-pdf')
    assert response.status_code == 404
    assert 'PDF unavailable' in response.text


def test_authorized_pdf_served_without_caching(monkeypatch, tmp_path, client):
    main.app.dependency_overrides[security.require_principal] = lambda: OWNER
    path = tmp_path / '11.pdf'
    path.write_bytes(b'%PDF-1.4\nmock PDF bytes')
    monkeypatch.setattr(main, 'authorized_pdf', lambda principal, doc_id: (path, 'guide.pdf'))
    response = client.get('/documents/11/original-pdf')
    assert response.status_code == 200
    assert response.content.startswith(b'%PDF-')
    assert response.headers['content-type'] == 'application/pdf'
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
