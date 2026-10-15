"""Run retrieval evaluation; optionally generate answers through OpenRouter/OpenAI.

Usage:
    python -m scripts.evaluate_rag
    python -m scripts.evaluate_rag --top-k 5 --output evaluation/results.json
    python -m scripts.evaluate_rag --answers --output evaluation/answers.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from app.evaluation import evaluate_case, load_cases, summarize

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "evaluation" / "questions.json"


def run_evaluation(
    cases: list[dict], top_k: int, answers: bool,
    search_fn, answer_fn=None,
) -> dict:
    """Dependency-injected runner: easy to test without DB, model, or network."""
    results = []
    for i, case in enumerate(cases, start=1):
        start = perf_counter()
        hits = search_fn(case["question"], top_k)
        retrieval_seconds = perf_counter() - start
        answer = None
        generation_seconds = None
        if answers:
            if answer_fn is None:
                raise ValueError("Answer generation function is required with --answers")
            start = perf_counter()
            answer = answer_fn(case["question"], hits)
            generation_seconds = perf_counter() - start
        outcome = evaluate_case(
            case, hits, retrieval_seconds, answer, generation_seconds
        )
        results.append(outcome)
        print(
            f"[{i}/{len(cases)}] {case['id']}: "
            f"doc={'YES' if outcome['document_hit'] else 'NO'} "
            f"evidence={'YES' if outcome['evidence_hit'] else 'NO'} "
            f"rank={outcome['first_evidence_rank'] or '-'}"
        )
    return {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "top_k": top_k,
        "answer_generation_enabled": answers,
        "summary": summarize(results, answers_enabled=answers),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the existing RAG retriever")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--retriever", choices=("vector", "hybrid", "rerank"), default="vector",
        help="Choose retrieval strategy; defaults to the original vector-only baseline",
    )
    parser.add_argument(
        "--warmup", action="store_true",
        help="Run one untimed retrieval first (recommended for steady-state timing)",
    )
    parser.add_argument("--answers", action="store_true",
                        help="Call configured LLM API; may incur costs")
    parser.add_argument("--output", type=Path,
                        help="Write JSON report; may include generated answers")
    args = parser.parse_args()
    if not 1 <= args.top_k <= 10:
        parser.error("--top-k must be between 1 and 10")

    try:
        cases = load_cases(args.dataset)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(f"Invalid evaluation dataset: {exc}")

    # Imports are deliberately lazy: importing metrics never loads PyTorch.
    from app.services import answer_question, search_documents

    # The CLI overrides the API's RAG_RETRIEVAL_MODE only for this process.
    def selected_search(question: str, top_k: int):
        return search_documents(question, top_k, mode=args.retriever)

    try:
        if args.warmup:
            # Model load / network download occurs before measured retrievals.
            selected_search(cases[0]["question"], args.top_k)
        report = run_evaluation(
            cases, args.top_k, args.answers,
            search_fn=selected_search, answer_fn=answer_question,
        )
        report["retriever"] = args.retriever
        report["warmup_enabled"] = args.warmup
    except Exception as exc:
        print(f"Evaluation aborted: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print("\n=== Evaluation summary ===")
    print(json.dumps(report["summary"], indent=2))
    print("Reminder: lexical evidence/answer matching is a proxy, not factual verification.")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Saved report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
