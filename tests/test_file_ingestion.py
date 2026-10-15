"""File ingestion validation and HTTP endpoint tests."""
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app import main
from app.security import Principal, require_editor


@pytest.fixture
def authenticated_editor():
    main.app.dependency_overrides[require_editor] = lambda: Principal(3, 1, "editor", "editor")
    yield
    main.app.dependency_overrides.clear()
from app.file_ingestion import MAX_FILE_BYTES, extract_document


def test_markdown_extraction():
    name, text = extract_document(
        "folders/policy.md", b"# Security policy\nEmployees must use MFA to sign in."
    )
    assert name == "policy.md"
    assert "Employees must use MFA" in text


def test_windows_filename_is_sanitized():
    name, _ = extract_document(
        r"C:\temp\policy.txt", b"Passwords must never be copied to public chats."
    )
    assert name == "policy.txt"


def test_pdf_extraction_no_text_rejected():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    stream = BytesIO()
    writer.write(stream)
    with pytest.raises(ValueError, match="No readable text"):
        extract_document("empty.pdf", stream.getvalue())


@pytest.mark.parametrize("filename, data", [
    ("malware.exe", b"This is some nonempty binary content."),
    ("empty.md", b""),
    ("short.txt", b"short"),
    ("bad.txt", b"\xff" * 40),
    ("invalid.pdf", b"not a valid PDF file at all"),
    ("huge.txt", b"x" * (MAX_FILE_BYTES + 1)),
])
def test_invalid_uploads(filename, data):
    with pytest.raises(ValueError):
        extract_document(filename, data)


def test_upload_calls_existing_ingestion(monkeypatch, authenticated_editor):
    seen = {}

    def fake_ingest(title, text, principal):
        seen["title"] = title
        seen["text"] = text
        return 42, 2, False

    monkeypatch.setattr(main, "ingest_document", fake_ingest)
    client = TestClient(main.app)
    response = client.post(
        "/documents/upload",
        files={"file": ("support.md", b"# Support\nAlways verify your VPN connection first.", "text/markdown")},
    )
    assert response.status_code == 200
    assert response.json() == {
        "document_id": 42,
        "chunk_count": 2,
        "already_exists": False,
    }
    assert seen["title"] == "support.md"


def test_upload_rejects_bad_extension(authenticated_editor):
    client = TestClient(main.app)
    response = client.post(
        "/documents/upload",
        files={"file": ("script.exe", b"Do not run this program at all.")},
    )
    assert response.status_code == 400


def test_upload_limit_is_50_mb():
    assert MAX_FILE_BYTES == 50 * 1024 * 1024


def test_empty_pdf_has_specific_error():
    from app.file_ingestion import extract_pdf_pages
    with pytest.raises(ValueError, match="uploaded PDF is empty"):
        extract_pdf_pages("test.pdf", b"")
