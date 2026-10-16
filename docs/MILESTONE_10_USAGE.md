# Milestone 10.1 — OpenRouter usage by user

This is an additive change on top of the **Milestone 10 account/admin dashboard** implementation. It does not require the optional Docker deployment and does not change documents, embeddings, API keys, session permissions, PDFs, or existing RAG responses.

## Before applying

1. Stop Uvicorn while migrating. Keep PostgreSQL running.
2. Back up `ragdb` with `pg_dump`.
3. Apply the Git patch with `git apply --check` and then `git apply`.

## Schema migration

```bash
source .venv/bin/activate
python -m scripts.migrate_usage_ledger
```

This creates `openrouter_usage_events` with indexes on `(tenant_id, created_at)` and `(tenant_id, user_id, created_at)`. It is rerunnable (`CREATE TABLE/INDEX IF NOT EXISTS`). Every event stores a tenant ID, user ID, model identifier, provider-reported prompt/output tokens and **nullable** provider-reported cost, plus a UTC timestamp. No prompts, answers, API keys, retrieved passages or raw provider responses are persisted. There is no historical backfill.

## Start and test

```bash
python -m pytest tests/test_usage_ledger.py tests/test_usage_api.py -v
python -m pytest tests/ -q
python -m uvicorn app.main:app --reload
```

In another terminal:

```bash
cd frontend
npm test
npm run build
npm run dev
```

Sign in as an admin at `http://127.0.0.1:5173`, open **Dashboard**, and send a few `/ask` requests with different user accounts. Click **Refresh usage**. The dashboard shows:

- Overall app-observed OpenRouter credit charges since the migration.
- Credits for the current UTC calendar week (starts Monday 00:00 UTC).
- A UTC daily graph with selectable last 7/30 days.
- Usage by user (including API-key-only users), this week and overall.
- Cost coverage: requests with provider-reported cost vs total recorded usage-bearing OpenRouter responses.

You can verify the HTTP endpoint in Swagger (`GET /admin/usage?days=30`). It is admin-only and filters every database read by the authenticated tenant. Normal reader/editor users get HTTP 403.

To confirm the stored records without logging raw content:

```sql
SELECT user_id, model, prompt_tokens, completion_tokens, cost_credits, created_at
FROM openrouter_usage_events
ORDER BY created_at DESC LIMIT 10;
```

This query is for trusted local administrators with database access; users should access the API rather than the database directly.

## Accounting limitations

- **Not OpenRouter's entire account balance.** Only `/ask` calls through this application are tracked, beginning after applying the migration and restarting the API. Historical per-user charges cannot be reconstructed from prior per-process counters.
- The recorded cost is the **provider-reported** OpenRouter `usage.cost` when available. If it is absent, the cost remains NULL and the dashboard displays incomplete coverage. Do not interpret missing cost as free usage.
- OpenAI-direct usage is intentionally excluded from the OpenRouter ledger.
- One database insert is attempted for each usage-bearing OpenRouter response. The request remains usable if that insert fails; the backend emits a generic warning. This is not an audited billing system and may miss events during outages/process crashes.
- The weekly interval uses **UTC Monday through the present**, and the 7/30-day graph is rolling calendar days (including the current partial day), also in UTC.
- Numeric values are sent to the frontend as decimal strings to avoid precision loss during serialization. The graph renders approximate numeric magnitudes for visualization.
- Disable access to the admin routes from untrusted networks; the milestone retains the same local security limitations discussed in the previous guides.

## Rollback

Revert the Git patch and restart the API/frontend if needed. The new `openrouter_usage_events` table is additive and can remain in the database harmlessly. **Do not drop the table unless you explicitly want to delete the recorded usage history.**
