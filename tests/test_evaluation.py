"""Offline evaluation tests: no network, model weights, Docker, or API keys needed."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.evaluation import evaluate_case, load_cases, percentile, summarize
from scripts.evaluate_rag import run_evaluation


CASE = {
    "id": "vpn",
    "question": "How to connect VPN?",
    "expected_title": "Vpn Support",
    "evidence_contains": "DNS resolution",
    "expected_answer_terms": ["DNS", "routes"],
}


def hit(number, title, text):
    return SimpleNamespace(source_number=number, title=title, content=text)


def test_retrieval_metrics_rank_two():
    rows = [hit(1, "Security Response", "Unrelated"),
            hit(2, "Vpn Support", "Check DNS resolution and routes")]
    result = evaluate_case(CASE, rows, 0.125)
    assert result["document_hit"] is True
    assert result["evidence_hit"] is True
    assert result["first_evidence_rank"] == 2
    assert result["evidence_reciprocal_rank"] == 0.5
    assert result["retrieval_ms"] == 125.0


def test_wrong_evidence_not_counted_as_hit():
    result = evaluate_case(CASE, [hit(1, "Vpn Support", "Check MFA")], 0.01)
    assert result["document_hit"] is True
    assert result["evidence_hit"] is False
    assert result["evidence_reciprocal_rank"] == 0


def test_citation_metrics_check_reference_and_gold_hit_not_semantics():
    rows = [hit(1, "Vpn Support", "DNS resolution and routes")]
    result = evaluate_case(CASE, rows, 0.01,
                           "Check DNS and routes [1]. Invalid [99].", 0.4)
    assert result["citation_reference_validity"] == 0.5
    assert result["cites_expected_evidence"] is True
    assert result["answer_term_coverage"] == 1


def test_uncited_answer_has_zero_reference_validity():
    result = evaluate_case(CASE, [], 0.02, "DNS routes")
    assert result["citation_reference_validity"] == 0
    assert result["cites_expected_evidence"] is False


def test_summary_and_percentiles():
    good = evaluate_case(CASE, [hit(1, "Vpn Support", "DNS resolution")], 0.1)
    bad = evaluate_case(CASE, [], 0.3)
    summary = summarize([good, bad], False)
    assert summary["document_recall_at_k"] == 0.5
    assert summary["evidence_recall_at_k"] == 0.5
    assert summary["evidence_mrr_at_k"] == 0.5
    assert summary["retrieval_p50_ms"] == 100
    assert summary["retrieval_p95_ms"] == 300
    assert percentile([], 95) is None


def test_runner_without_llm_calls():
    seen = []

    def fake_search(question, k):
        seen.append((question, k))
        return [hit(1, "Vpn Support", "DNS resolution and routes")]

    def forbidden_answer(*_):
        raise AssertionError("LLM should not be called")

    report = run_evaluation([CASE], 5, False, fake_search, forbidden_answer)
    assert report["summary"]["evidence_recall_at_k"] == 1
    assert seen == [(CASE["question"], 5)]


def test_runner_with_answer_uses_provided_function():
    report = run_evaluation(
        [CASE], 3, True,
        lambda *_: [hit(1, "Vpn Support", "DNS resolution and routes")],
        lambda *_: "Check DNS resolution and routes [1].",
    )
    assert report["summary"]["citation_reference_validity"] == 1
    assert report["summary"]["answer_term_coverage"] == 1


def test_load_cases_rejects_duplicates_and_empty_labels(tmp_path):
    path = tmp_path / "questions.json"
    path.write_text(json.dumps([CASE, CASE]))
    with pytest.raises(ValueError, match="Duplicate"):
        load_cases(path)
    path.write_text(json.dumps([{**CASE, "evidence_contains": ""}]))
    with pytest.raises(ValueError, match="evidence_contains"):
        load_cases(path)


def test_real_dataset_syntax_and_uniqueness():
    path = Path(__file__).resolve().parents[1] / "evaluation" / "questions.json"
    assert len(load_cases(path)) == 8
