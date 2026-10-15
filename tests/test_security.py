"""Milestone 7: security fail-closed, tenant filtering, API permissions."""
from contextlib import contextmanager
import pytest
from fastapi.testclient import TestClient

from app import main, security, services
from app.security import Principal

ADMIN = Principal(user_id=1, tenant_id=1, role="admin", username="admin")
EDITOR = Principal(user_id=2, tenant_id=1, role="editor", username="editor")
READER = Principal(user_id=3, tenant_id=1, role="reader", username="reader")
OTHER_TENANT = Principal(user_id=4, tenant_id=2, role="editor", username="outsider")


@pytest.fixture
def client():
    main.app.dependency_overrides.clear()
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


def authorize(principal):
    # Override only the DB lookup in this test; actual permission dependencies run.
    main.app.dependency_overrides[security.require_principal] = lambda: principal


def test_authentication_required(client):
    assert client.post("/search", json={"question": "vpn issue?"}).status_code == 401
    assert client.post("/ask", json={"question": "vpn issue?"}).status_code == 401
    assert client.post("/documents", json={"title": "Test", "text": "A valid test document string."}).status_code == 401
    assert client.get("/documents").status_code == 401
    assert client.post("/documents/upload", files={"file": ("x.md", b"some valid text for testing")}).status_code == 401
    assert client.delete("/documents/11").status_code == 401
    assert client.post("/documents/11/reindex-pdf", files={"file": ("x.pdf", b"x")}).status_code == 401


def test_reader_cannot_modify_documents(client):
    authorize(READER)
    assert client.post("/documents", json={"title": "Test", "text": "Long enough example to pass validation."}).status_code == 403
    assert client.post("/documents/upload", files={"file": ("file.md", b"some valid file text here")}).status_code == 403
    assert client.delete("/documents/11").status_code == 403
    assert client.post("/documents/11/share", json={"username": "admin"}).status_code == 403
    assert client.post("/documents/11/reindex-pdf", files={"file": ("file.pdf", b"x")}).status_code == 403


def test_reader_can_search_but_tenant_bound(monkeypatch, client):
    authorize(READER)
    seen = {}
    def fake_search(question, top_k, *, principal, mode=None):
        seen["principal"] = principal
        return []
    monkeypatch.setattr(main, "search_documents", fake_search)
    result = client.post("/search", json={"question": "help with VPN", "top_k": 5})
    assert result.status_code == 200
    assert seen["principal"] == READER


def test_cross_tenant_delete_denied(monkeypatch, client):
    authorize(OTHER_TENANT)
    # Simulate an existing doc in tenant 1 and a user in tenant 2.
    def denied(principal, document_id):
        assert principal.tenant_id == 2
        raise PermissionError("Document not found or not writable")
    monkeypatch.setattr(main, "delete_document", denied)
    assert client.delete("/documents/11").status_code == 404


def test_access_sql_used_in_both_queries():
    assert "d.tenant_id=%s" in services.ACCESS_SQL
    assert "d.owner_user_id=%s" in services.ACCESS_SQL
    assert "document_acl" in services.ACCESS_SQL
    assert services.access_args(READER) == (1, 3, "reader", 3)
    assert services.access_args(OTHER_TENANT) == (2, 4, "editor", 4)


def test_nonwriter_ingestion_fails_before_embedding(monkeypatch):
    monkeypatch.setattr(services, "embed_many", lambda *_: (_ for _ in ()).throw(AssertionError("inference must not run")))
    with pytest.raises(PermissionError):
        services.ingest_document("Test", "This is a sufficiently long text passage.", READER)


def test_missing_principal_fails_before_embedding(monkeypatch):
    monkeypatch.setattr(services, "embed_many", lambda *_: (_ for _ in ()).throw(AssertionError("no embed")))
    with pytest.raises(PermissionError):
        services.search_documents("help", 3, principal=None)


def test_key_format_is_high_entropy_and_digest_not_equal_raw():
    key1, key2 = security.generate_api_key(), security.generate_api_key()
    assert key1.startswith("rag_") and len(key1) >= 40
    assert key1 != key2
    assert security.key_digest(key1) != key1
    assert security.key_digest(key1) != security.key_digest(key2)


def test_invalid_key_rejected_without_database(monkeypatch):
    monkeypatch.setattr(security, "db_connection", lambda: (_ for _ in ()).throw(AssertionError("invalid keys must short-circuit")))
    assert security.principal_from_api_key("not-a-valid-key") is None
