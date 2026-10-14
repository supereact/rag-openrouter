import pytest
from pydantic import ValidationError
from app.schemas import SearchRequest, IngestRequest


def test_search_has_sensible_limit():
    with pytest.raises(ValidationError):
        SearchRequest(question="VPN help", top_k=1000)


def test_ingest_requires_meaningful_text():
    with pytest.raises(ValidationError):
        IngestRequest(title="IT", text="too short")
