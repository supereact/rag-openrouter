# RAG evaluation — milestone 5

This evaluation is **read-only**: no schema changes, document updates, or reindexing.
Default mode calls your existing local embedding model and PostgreSQL retrieval,
**not** OpenRouter. `--answers` explicitly enables configured LLM calls (may cost money
and transmit retrieved text to that provider).

## Prepare

Keep the PostgreSQL container running; activate `.venv`; ensure `.env` points to
its database. For the included 8 cases, the four bundled demo TXT documents must
be indexed, plus the NIST file titled `incident-response.pdf`. If a file is not in
your database, the related cases count as misses. You can remove or edit cases
in `evaluation/questions.json` to match your actual corpus. Use short,
verbatim phrases in `evidence_contains` that occur within **one** chunk.

## Run from project root

```bash
python -m pytest tests/test_evaluation.py -v
python -m scripts.evaluate_rag --top-k 5 --output evaluation/results.json
# Optional: requires working OpenRouter/OpenAI key and incurs LLM costs
python -m scripts.evaluate_rag --top-k 5 --answers --output evaluation/answers.json
```

`--dataset path/to/custom.json` selects another labeled question set. `--top-k`
accepts 1–10 and should be held fixed for comparisons. The program prints a
per-case hit/rank and summary metrics; `--output` writes JSON on your Mac.
Never commit result files containing answers or company information.

## What the metrics actually mean

- **document_recall_at_k**: fraction of questions for which at least one of the
  top K chunks has the expected document title (one labeled relevant document
  per case). This is *not* general multi-document recall.
- **evidence_recall_at_k**: fraction with a top K chunk in the expected document
  containing the exact, case-insensitive `evidence_contains` text.
- **evidence_mrr_at_k**: mean of `1 / rank` of the first exact evidence hit;
  0 when absent.
- **retrieval_p50_ms / p95_ms**: observed per-query wall times for embedding +
  search, nearest-rank estimator; excludes any LLM answer generation. First
  model warm-up may inflate one measurement. Small datasets are not reliable
  latency benchmarks.
- **citation_reference_validity** (only `--answers`): average fraction of
  bracketed numeric citations such as `[2]` that point to returned source
  numbers. Uncited answers score 0. Does *not* judge whether claims are true.
- **cites_expected_evidence_rate** (`--answers`): fraction of answers citing a
  retrieved chunk whose text contains the gold snippet. This is a *proxy* for
  evidence usage, not automated semantic citation accuracy.
- **answer_term_coverage** (`--answers`): average fraction of listed strings
  found verbatim in answers. Lexical completeness proxy; not answer accuracy.

For true citation accuracy and answer correctness, manually review answers
against the cited PDF pages or add a separately validated judge later.

## Create a useful baseline

1. Save retrieval results with `--output evaluation/baseline.json`.
2. Note misses; check expected document titles, extraction and chunk boundaries.
3. When adding hybrid search or reranking, run the same dataset and same top K.
4. Compare results and manually inspect changes. Do not interpret similarity
   scores as probabilities.

Generated JSON reports (`evaluation/results.json`, `evaluation/answers.json`,
`evaluation/baseline.json`) should stay local. They may contain LLM answers.
