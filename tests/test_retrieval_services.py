"""Service-level hybrid flow tests; mock all DB/ML operations."""
from contextlib import contextmanager

import pytest

pytest.importorskip("psycopg")
pytest.importorskip("pgvector")
pytest.importorskip("sentence_transformers")

from app import services
from app.security import Principal

PRINCIPAL = Principal(user_id=3, tenant_id=2, role="reader", username="test")


def rows():
    return {
        "vector": [
            (101, 11, "incident-response.pdf", 10, "Generic response overview", 7, .90),
            (102, 11, "incident-response.pdf", 11, "Exact incident phases", 8, .72),
        ],
        "keyword": [
            (102, 11, "incident-response.pdf", 11, "Exact incident phases", 8, .72),
        ],
    }


@contextmanager
def fake_connection(calls):
    class Connection:
        def execute(self, sql, params):
            calls.append((sql, params))
            value = rows()["keyword"] if "websearch_to_tsquery" in sql else rows()["vector"]

            class Cursor:
                def fetchall(self):
                    return value

            return Cursor()

    yield Connection()


def setup(monkeypatch):
    calls = []
    monkeypatch.setattr(services, "db_connection", lambda: fake_connection(calls))
    monkeypatch.setattr(services, "embed_many", lambda _texts: [[0.1, 0.2, 0.3]])
    monkeypatch.setattr(services, "_audit", lambda *args, **kwargs: None)
    return calls


def test_vector_mode_uses_only_vector_sql(monkeypatch):
    calls = setup(monkeypatch)
    hits = services.search_documents("Incident phases", 2, mode="vector", principal=PRINCIPAL)
    assert [h.chunk_index for h in hits] == [10, 11]
    assert [h.source_number for h in hits] == [1, 2]
    assert hits[1].page_number == 8
    assert len(calls) == 1
    assert "websearch_to_tsquery" not in calls[0][0]


def test_hybrid_sql_and_page_metadata(monkeypatch):
    calls = setup(monkeypatch)
    hits = services.search_documents("Incident phases", 2, mode="hybrid", principal=PRINCIPAL)
    assert [h.chunk_index for h in hits] == [11, 10]
    assert hits[0].page_number == 8
    assert hits[0].similarity == .72
    assert len(calls) == 2
    assert "websearch_to_tsquery" in calls[1][0]
    assert len(calls[1][1]) == 7
    assert calls[0][1][1:5] == (2, 3, "reader", 3)
    assert "d.tenant_id=%s" in calls[0][0]
    assert "d.tenant_id=%s" in calls[1][0]


def test_rerank_mode_calls_reranker_after_database(monkeypatch):
    calls = setup(monkeypatch)
    seen = []

    def fake_rerank(question, candidates):
        seen.append((question, len(candidates)))
        return list(reversed(candidates))

    monkeypatch.setattr(services, "_cross_encoder_rerank", fake_rerank)
    hits = services.search_documents("Incident phases", 2, mode="rerank", principal=PRINCIPAL)
    assert [h.chunk_index for h in hits] == [10, 11]
    assert seen == [("Incident phases", 2)]
    assert len(calls) == 2


def test_invalid_mode_does_not_embed_or_query(monkeypatch):
    calls = setup(monkeypatch)
    with pytest.raises(ValueError, match="Unknown retrieval mode"):
        services.search_documents("test", 3, mode="unknown", principal=PRINCIPAL)
    assert not calls
