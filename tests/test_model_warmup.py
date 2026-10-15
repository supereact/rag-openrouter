"""Startup warm-up tests without requiring model downloads or database access."""
import sys
from types import SimpleNamespace

import pytest

from app.model_warmup import warmup_local_models


@pytest.mark.parametrize("mode", ["vector", "hybrid", "rerank"])
def test_startup_warms_embedding_and_only_required_reranker(monkeypatch, mode):
    embedded = []
    predicted = []
    loaded_rerankers = []

    class FakeReranker:
        def predict(self, pairs, show_progress_bar):
            predicted.append((pairs, show_progress_bar))
            return [0.5]

    def fake_get_reranker():
        loaded_rerankers.append(True)
        return FakeReranker()

    monkeypatch.setenv("RAG_RETRIEVAL_MODE", mode)
    monkeypatch.setitem(sys.modules, "app.embeddings", SimpleNamespace(
        embed_many=lambda texts: embedded.append(texts),
    ))
    monkeypatch.setitem(sys.modules, "app.services", SimpleNamespace(
        _get_reranker=fake_get_reranker,
    ))

    warmup_local_models()

    assert len(embedded) == 1
    assert len(embedded[0]) == 1
    assert len(loaded_rerankers) == (1 if mode == "rerank" else 0)
    assert len(predicted) == (1 if mode == "rerank" else 0)
    if predicted:
        assert predicted[0][1] is False


def test_invalid_retrieval_mode_does_not_load_models(monkeypatch):
    embedded = []
    monkeypatch.setenv("RAG_RETRIEVAL_MODE", "invalid")
    monkeypatch.setitem(sys.modules, "app.embeddings", SimpleNamespace(
        embed_many=lambda texts: embedded.append(texts),
    ))

    with pytest.raises(ValueError, match="Invalid RAG_RETRIEVAL_MODE"):
        warmup_local_models()
    assert embedded == []
