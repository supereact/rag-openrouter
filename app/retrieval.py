"""Pure ranking helpers for hybrid RAG retrieval.

No DB or model imports: ranking is deterministic and simple to unit-test.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    chunk_id: int
    document_id: int
    title: str
    chunk_index: int
    content: str
    page_number: int | None
    similarity: float  # Always cosine similarity, including FTS candidates.


def row_to_candidate(row: tuple) -> Candidate:
    """Map the shared SELECT column order from both SQL retrieval queries."""
    return Candidate(
        chunk_id=int(row[0]),
        document_id=int(row[1]),
        title=row[2],
        chunk_index=int(row[3]),
        content=row[4],
        page_number=row[5],
        similarity=float(row[6]),
    )


def reciprocal_rank_fusion(
    vector_hits: list[Candidate],
    keyword_hits: list[Candidate],
    rrf_k: int = 60,
) -> list[Candidate]:
    """Fuse independent rank lists by stable chunk ID (not by document ID).

    score(chunk) = sum(1 / (rrf_k + rank)) over lists containing that chunk.
    """
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    candidates: dict[int, Candidate] = {}
    scores: dict[int, float] = {}
    for ranking in (vector_hits, keyword_hits):
        seen: set[int] = set()
        for rank, hit in enumerate(ranking, start=1):
            if hit.chunk_id in seen:
                continue
            seen.add(hit.chunk_id)
            candidates.setdefault(hit.chunk_id, hit)
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (rrf_k + rank)
    return sorted(
        candidates.values(),
        key=lambda hit: (-scores[hit.chunk_id], hit.chunk_id),
    )


def rerank_candidates(
    question: str, candidates: list[Candidate], scores: list[float]
) -> list[Candidate]:
    """Order candidates by cross-encoder relevance scores, highest first."""
    if len(candidates) != len(scores):
        raise ValueError("Reranker must produce one score per candidate")
    return [
        candidate for _, candidate in sorted(
            zip(scores, candidates),
            key=lambda item: (-float(item[0]), item[1].chunk_id),
        )
    ]
