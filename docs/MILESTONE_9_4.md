# Milestone 9.4 — Local observability (no dependency or DB migration)

This change keeps the existing RAG retrieval, tenant access controls, and
OpenRouter/OpenAI responses untouched. It instruments only the secured
`/search` and `/ask` paths.

## What's measured

- Admin-only `GET /observability` returns this process's measurements for **the
  authenticated administrator's tenant only**.
- Separate phases for `/search` retrieval, `/ask` retrieval, and `/ask`
  generation. Counters include calls, errors, error rate, mean, P50, and P95.
- Last 256 latencies per tenant/phase drive percentiles; total call/error
  counts persist for the lifetime of this process.
- OpenRouter's **provider-reported cost in credits** and prompt/completion
  tokens are included when provided. OpenAI usage tokens are tracked without
  fabricating a price. `provider_cost_samples` and `usage_samples` distinguish
  "unreported" from a genuine zero-cost call. Values are **not billing records**.
- Each HTTP response gets a random `X-Request-ID`. Request logs include its
  ID, HTTP method, *route template*, status and duration. Never log raw URLs,
  authorization headers, questions, documents, or provider responses.

## Apply and test

```sh
cd ~/work/enterprise-rag-openrouter
git apply --check enterprise-rag-milestone-9-4-observability.patch
git apply enterprise-rag-milestone-9-4-observability.patch
source .venv/bin/activate
python -m pytest tests/test_observability.py -v
python -m pytest tests/ -q
```

Restart FastAPI (model preload still happens during startup):

```sh
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In the React UI sign in as your local admin and ask two questions. Then
inspect `GET /observability` in Swagger with that admin's Bearer key.
Alternatively, from your terminal (do not paste the key in shell history):

```sh
read -s 'RAG_KEY?Admin API key: '; echo
curl -s -H "Authorization: Bearer $RAG_KEY" http://127.0.0.1:8000/observability
unset RAG_KEY
```

`read -s` is for **zsh**. On other shells, use your shell's secure input method.
Readers and editors get 403; missing/invalid credentials get 401. Users from
other tenants cannot read these tenant-specific counters.

## Configuration

```ini
RAG_OBSERVABILITY_ENABLED=true
```

Setting it to `false` prevents new metrics; it does not erase counters already
held in memory. Restart the server to clear them.

## Limits / production checklist

This is deliberately a **local-development** monitor. It does not persist data;
`--reload` resets counters, and each Uvicorn worker maintains separate
counters. Do not run multiple workers and interpret this endpoint as a global
metric aggregator. Only the first 1,000 tenant IDs seen per process can be
tracked, limiting memory growth. Per-phase latency samples are capped at 256.

The basic `/health` checks database reachability. `/ingestion-health` continues
to provide persistent, tenant-scoped ingestion job status. Background worker
metrics are not aggregated into `/observability` because the worker runs in a
**different process**.

Before deploying, switch to OpenTelemetry/Prometheus or a central backend,
use per-tenant authorization on metrics access, configure log retention and
redaction, and apply TLS and least-privilege DB credentials. Measure provider
costs from authoritative usage/billing rather than estimating from input
character counts.
