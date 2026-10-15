"""Ranking and hybrid retrieval tests, no live DB or model download required."""
from unittest.mock import MagicMock

import pytest

from app.retrieval import (
    Candidate, reciprocal_rank_fusion, rerank_candidates, row_to_candidate,
)


def candidate(idx: int, similarity: float = 0.5) -> Candidate:
    return Candidate(
        chunk_id=idx, document_id=11, title="incident-response.pdf",
        chunk_index=idx, content=f"Document chunk {idx}",
        page_number=idx + 1, similarity=similarity,
    )


def test_rrf_fuses_by_chunk_id_not_document_id():
    ranked = reciprocal_rank_fusion(
        [candidate(1), candidate(2)],
        [candidate(3), candidate(2)],
    )
    assert [hit.chunk_id for hit in ranked] == [2, 1, 3]
    assert len(ranked) == 3


def test_rrf_rescues_candidate_outside_vector_top_k():
    vectors = [candidate(i) for i in range(1, 11)]
    keywords = [candidate(7), candidate(2), candidate(10)]
    fused = reciprocal_rank_fusion(vectors, keywords)
    assert fused.index(next(hit for hit in fused if hit.chunk_id == 7)) < 6


def test_rrf_handles_empty_lexical_results():
    vectors = [candidate(1), candidate(2)]
    assert reciprocal_rank_fusion(vectors, []) == vectors


def test_rrf_no_duplicate_scores_from_repeated_id_within_one_list():
    result = reciprocal_rank_fusion([candidate(1), candidate(1)], [candidate(2)])
    assert [hit.chunk_id for hit in result] == [1, 2]


def test_rrf_rejects_invalid_k():
    with pytest.raises(ValueError, match="positive"):
        reciprocal_rank_fusion([candidate(1)], [], rrf_k=0)


def test_rerank_overrides_fused_order_without_changing_similarity():
    first, second = candidate(1, .92), candidate(2, .60)
    result = rerank_candidates("explain policy", [first, second], [-3, 5])
    assert [hit.chunk_id for hit in result] == [2, 1]
    assert result[0].similarity == .60


def test_rerank_ties_deterministically():
    result = rerank_candidates("test", [candidate(5), candidate(3)], [1, 1])
    assert [hit.chunk_id for hit in result] == [3, 5]


def test_rerank_requires_matching_score_count():
    with pytest.raises(ValueError, match="one score"):
        rerank_candidates("test", [candidate(1)], [])


def test_row_mapping_preserves_page_and_cosine_score():
    hit = row_to_candidate((17, 11, "guide.pdf", 6, "text", 42, .81))
    assert (hit.chunk_id, hit.document_id, hit.page_number, hit.similarity) == (17, 11, 42, .81)
