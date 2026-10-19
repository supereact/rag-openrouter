"""Large-PDF regressions using synthetic PDFs and mocked database/model writes."""
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app import file_ingestion, ingestion_jobs, main, security, services
from app.security import Principal

EDITOR = Principal(2, 1, 'editor', 'synthetic-editor')
JOB = UUID('11111111-1111-4111-8111-111111111111')


@pytest.fixture(scope='module')
def large_pdf():
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'),
    }))
    for number in range(1, 351):
        page = writer.add_blank_page(width=300, height=300)
        if number == 151:
            continue  # Blank physical pages must not shift later citations.
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): font}),
        })
        content = DecodedStreamObject()
        content.set_data(f'BT /F1 12 Tf 10 280 Td (Synthetic policy page {number}.) Tj ET'.encode())
        page[NameObject('/Contents')] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def assert_physical_pages(pages):
    assert len(pages) == 350
    assert pages[150] == (151, '')
    assert pages[300][0] == 301
    assert 'Synthetic policy page 301.' in pages[300][1]
    assert pages[-1][0] == 350
    assert 'Synthetic policy page 350.' in pages[-1][1]


def test_real_350_page_pdf_extracts_without_truncation(large_pdf):
    name, text = file_ingestion.extract_document('folder/large.pdf', large_pdf)
    assert name == 'large.pdf'
    assert 'Synthetic policy page 350.' in text
    assert_physical_pages(file_ingestion.extract_pdf_pages('large.pdf', large_pdf))


@pytest.mark.parametrize('extract', [file_ingestion.extract_document, file_ingestion.extract_pdf_pages])
@pytest.mark.parametrize('count', [1000, 1001])
def test_page_limit_boundary_before_text_extraction(monkeypatch, extract, count):
    def text():
        assert count == 1000, 'Over-limit PDFs must be rejected before extracting text'
        return 'Synthetic text for a boundary test.'
    page = SimpleNamespace(extract_text=text)
    monkeypatch.setattr(file_ingestion, 'PdfReader',
                        lambda *_a, **_kw: SimpleNamespace(is_encrypted=False, pages=[page] * count))
    if count == 1001:
        with pytest.raises(ValueError, match='PDF exceeds the 1000-page limit'):
            extract('boundary.pdf', b'%PDF-synthetic')
    else:
        result = extract('boundary.pdf', b'%PDF-synthetic')
        if extract is file_ingestion.extract_pdf_pages:
            assert len(result) == 1000
            assert result[-1][0] == 1000
        else:
            assert result[1].count('Synthetic text') == 1000


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    main.app.dependency_overrides[security.require_principal] = lambda: EDITOR
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()


@pytest.mark.parametrize('route,replacing', [('/documents/upload', False), ('/documents/42/reindex-pdf', True)])
def test_upload_and_reindex_accept_large_pdf(monkeypatch, client, large_pdf, route, replacing):
    seen = []
    writable = []
    originals = []
    def ingest(title, pages, principal, **kwargs):
        assert title == 'large.pdf'
        assert principal == EDITOR
        assert_physical_pages(pages)
        seen.append(kwargs)
        return 42, 349, False
    monkeypatch.setattr(main, 'ingest_pdf_pages', ingest)
    monkeypatch.setattr(main, 'assert_document_writable', lambda principal, doc: writable.append((principal, doc)))
    monkeypatch.setattr(main, 'store_pdf', lambda doc, data: originals.append((doc, data)))
    result = client.post(route, files={'file': ('large.pdf', large_pdf, 'application/pdf')})
    assert result.status_code == 200
    assert result.json() == dict(document_id=42, chunk_count=349, already_exists=False)
    assert seen == [{'replace_document_id': 42} if replacing else {}]
    assert originals == [(42, large_pdf)]
    assert writable == ([(EDITOR, 42)] if replacing else [])


def test_queued_large_pdf_is_processed_with_physical_pages(monkeypatch, client, large_pdf, tmp_path):
    calls = []
    @contextmanager
    def database():
        class Connection:
            def execute(self, sql, params=()):
                calls.append((sql, params))
                return self
            def fetchone(self):
                params = calls[-1][1]
                return params[0], params[3], 'queued', datetime.now(timezone.utc)
        yield Connection()
    monkeypatch.setattr(ingestion_jobs, 'SPOOL_DIR', tmp_path)
    monkeypatch.setattr(ingestion_jobs, 'db_connection', database)
    monkeypatch.setattr(ingestion_jobs, 'uuid4', lambda: JOB)
    result = client.post('/documents/upload-async', files={'file': ('large.pdf', large_pdf, 'application/pdf')})
    assert result.status_code == 202
    assert ingestion_jobs.spool_path(JOB).read_bytes() == large_pdf
    def ingest(title, pages, principal):
        assert title == 'large.pdf'
        assert principal == EDITOR
        assert_physical_pages(pages)
        return 42, 349, False
    monkeypatch.setattr(ingestion_jobs, 'claim_next_job', lambda: (JOB, 'large.pdf', EDITOR, 1))
    monkeypatch.setattr(services, 'ingest_pdf_pages', ingest)
    originals = []
    monkeypatch.setattr(ingestion_jobs, 'store_pdf', lambda doc, data: originals.append((doc, data)))
    assert ingestion_jobs.process_one_job()
    assert not ingestion_jobs.spool_path(JOB).exists()
    assert originals == [(42, large_pdf)]
    sql, params = calls[-1]
    assert "status='completed'" in sql
    assert params == (42, 349, False, JOB, 1)
