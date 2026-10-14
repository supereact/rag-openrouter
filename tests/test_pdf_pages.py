from io import BytesIO
from pypdf import PdfWriter
from app.schemas import SearchHit
from app.services import answer_question


def test_optional_page_number():
    hit = SearchHit(source_number=1, document_id=11, title='guide.pdf',
                    chunk_index=5, content='Example source text', similarity=.7,
                    page_number=3)
    assert hit.page_number == 3


def test_legacy_chunk_has_no_page():
    hit = SearchHit(source_number=1, document_id=11, title='guide.pdf',
                    chunk_index=5, content='Example source text', similarity=.7)
    assert hit.page_number is None
