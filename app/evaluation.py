"""Pure, dependency-free RAG evaluation metrics; does not call the database or LLM.

Gold labels are human-authored snippets and document titles. Exact text matching
is a reproducible retrieval proxy, not a semantic or faithfulness judgment.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from statistics import mean
from typing import Any

CITATIONS = re.compile(r"\[(\d+)\]")


def load_cases(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("Evaluation dataset must be a nonempty JSON array")
    cases: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for index, raw in enumerate(data, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Case {index} must be a JSON object")
        for key in ("id", "question", "expected_title", "evidence_contains"):
            if not isinstance(raw.get(key), str) or not raw[key].strip():
                raise ValueError(f"Case {index}: {key} must be a nonempty string")
        if raw["id"] in identifiers:
            raise ValueError(f"Duplicate evaluation id: {raw['id']}")
        identifiers.add(raw["id"])
        terms = raw.get("expected_answer_terms", [])
        if not isinstance(terms, list) or any(
            not isinstance(term, str) or not term.strip() for term in terms
        ):
            raise ValueError(f"Case {index}: expected_answer_terms must be strings")
        cases.append({**raw, "expected_answer_terms": terms})
    return cases


def _matches_title(hit: Any, case: dict[str, Any]) -> bool:
    return hit.title.strip().casefold() == case["expected_title"].strip().casefold()


def _matches_evidence(hit: Any, case: dict[str, Any]) -> bool:
    return _matches_title(hit, case) and (
        case["evidence_contains"].casefold() in hit.content.casefold()
    )


def evaluate_case(
    case: dict[str, Any], hits: list[Any], retrieval_seconds: float,
    answer: str | None = None, generation_seconds: float | None = None,
) -> dict[str, Any]:
    """Evaluate an ordered list of SearchHit-like objects against one gold case."""
    document_ranks = [i for i, hit in enumerate(hits, 1) if _matches_title(hit, case)]
    evidence_ranks = [i for i, hit in enumerate(hits, 1) if _matches_evidence(hit, case)]
    result: dict[str, Any] = {
        "id": case["id"],
        "document_hit": bool(document_ranks),
        "evidence_hit": bool(evidence_ranks),
        "evidence_reciprocal_rank": 1 / evidence_ranks[0] if evidence_ranks else 0.0,
        "first_evidence_rank": evidence_ranks[0] if evidence_ranks else None,
        "retrieval_ms": round(retrieval_seconds * 1000, 2),
        "retrieved_titles": list(dict.fromkeys(hit.title for hit in hits)),
    }
    if answer is not None:
        cited_numbers = {int(number) for number in CITATIONS.findall(answer)}
        hit_by_number = {hit.source_number: hit for hit in hits}
        valid = {number for number in cited_numbers if number in hit_by_number}
        evidence_citations = {
            number for number in valid if _matches_evidence(hit_by_number[number], case)
        }
        terms = case["expected_answer_terms"]
        matched_terms = [t for t in terms if t.casefold() in answer.casefold()]
        result.update({
            "answer": answer,
            "cited_source_numbers": sorted(cited_numbers),
            "citation_reference_validity": (
                len(valid) / len(cited_numbers) if cited_numbers else 0.0
            ),
            "cites_expected_evidence": bool(evidence_citations),
            "answer_term_coverage": len(matched_terms) / len(terms) if terms else None,
            "generation_ms": (
                round(generation_seconds * 1000, 2)
                if generation_seconds is not None else None
            ),
        })
    return result


def percentile(values: list[float], percent: int) -> float | None:
    """Nearest-rank percentile, useful for small, explicitly labeled samples."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil((percent / 100) * len(ordered)) - 1)
    return ordered[index]


def summarize(results: list[dict[str, Any]], answers_enabled: bool) -> dict[str, Any]:
    if not results:
        raise ValueError("Cannot summarize zero evaluation results")
    retrieval = [row["retrieval_ms"] for row in results]
    summary: dict[str, Any] = {
        "cases": len(results),
        "document_recall_at_k": mean(row["document_hit"] for row in results),
        "evidence_recall_at_k": mean(row["evidence_hit"] for row in results),
        "evidence_mrr_at_k": mean(row["evidence_reciprocal_rank"] for row in results),
        "retrieval_p50_ms": percentile(retrieval, 50),
        "retrieval_p95_ms": percentile(retrieval, 95),
    }
    if answers_enabled:
        term_scores = [row["answer_term_coverage"] for row in results
                       if row["answer_term_coverage"] is not None]
        durations = [row["generation_ms"] for row in results
                     if row["generation_ms"] is not None]
        summary.update({
            "citation_reference_validity": mean(
                row["citation_reference_validity"] for row in results
            ),
            "cites_expected_evidence_rate": mean(
                row["cites_expected_evidence"] for row in results
            ),
            "answer_term_coverage": mean(term_scores) if term_scores else None,
            "generation_p50_ms": percentile(durations, 50),
            "generation_p95_ms": percentile(durations, 95),
        })
    return summary
