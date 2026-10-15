"""Extracted text is not capped at 200,000 characters (upload size still is)."""
from app import file_ingestion


def test_large_utf8_text_below_upload_byte_limit():
    data = b"A" * 200_001
    name, text = file_ingestion.extract_document("long.txt", data)
    assert name == "long.txt"
    assert len(text) == 200_001


def test_pdf_extractors_accept_over_200k_characters(monkeypatch):
    class FakePage:
        def extract_text(self):
            return "Technical documentation. " * 10_000

    class FakeReader:
        is_encrypted = False

        def __init__(self, stream, strict=False):
            self.pages = [FakePage(), FakePage()]

    monkeypatch.setattr(file_ingestion, "PdfReader", FakeReader)
    data = b"%PDF-test"
    filename, text = file_ingestion.extract_document("large.pdf", data)
    assert filename == "large.pdf"
    assert len(text) > 200_000
    pages = file_ingestion.extract_pdf_pages("large.pdf", data)
    assert [page for page, _ in pages] == [1, 2]
    assert sum(len(part) for _, part in pages) > 200_000


def test_upload_byte_limit_still_applies():
    oversized = b"x" * (file_ingestion.MAX_FILE_BYTES + 1)
    try:
        file_ingestion.extract_document("oversized.txt", oversized)
    except ValueError as exc:
        assert "upload limit" in str(exc)
    else:
        raise AssertionError("Oversized upload was not rejected")
