# Milestone 10.2: OpenRouter monthly budget guardrails

This is a **local development credit guardrail**, not a provider-enforced billing cap.
All amounts are OpenRouter provider-reported credits (not currency converted or a
claim about the user's complete OpenRouter account).

## Install

1. Back up PostgreSQL. Stop FastAPI during migration.
2. Apply the M10.2 Git patch after M10.1 usage ledger patch.
3. Run `python -m scripts.migrate_credit_budgets` (repeatable and additive).
4. Run `python -m pytest tests/test_credit_budgets.py tests/test_credit_budgets_api.py -v`.
5. Run `python -m pytest tests/ -q` and in `frontend/` run `npm test && npm run build`.
6. Restart FastAPI and React. In Admin Dashboard, open **Monthly credit budgets**.
7. Set tenant monthly credit limit, e.g. `1.0`, and per-request reservation, e.g. `0.01`.
8. Optionally set a smaller user limit, e.g. `0.1` for a test account.
9. Ask a question with that user, refresh dashboard, and check `spent`,
   `reserved`, and `remaining` credits. Set that user's limit to `0` and confirm
   that `/ask` returns HTTP 429 **without an LLM call**; `/search` still works.
10. Remove the test limit by leaving its field blank and saving.

## Scope and accounting

- Monthly window: 00:00 UTC on the first day of each calendar month onward.
- Budgets are scoped to authenticated tenant and user; admin routes are tenant-isolated.
- Reservations are acquired **before retrieval and OpenRouter generation** under a
  PostgreSQL per-tenant transaction advisory lock. All concurrent requests for the
  same tenant therefore see pending reservations before they can start generation.
- If retrieval fails before generation begins, the unused reservation is released.
- Completed OpenRouter requests with a reported cost atomically write the usage
  event and release the reservation. Requests with missing/unreported cost keep
  the reservation and appear as **unknown**. A database settlement error leaves
  the reservation held, not silently released.
- The default reservation is `0.01` credits; admins can change it. It protects
  concurrent requests, but **a single actual request can cost more than reserved**,
  pushing actual monthly spending over the limit. This is not a hard bill cap.
- If a provider request fails and no reliable cost arrives, the reservation
  remains held. Operator review against provider billing is required.
- Use OpenRouter key-level limits and a model output-token bound for additional
  control. Do **not** promise the application limit caps charges absolutely.
- Before a budget is configured, OpenRouter usage continues to be recorded using
  the legacy M10.1 ledger path, and no reservation is created.
- Direct OpenAI requests are unaffected by these OpenRouter-only budgets.
- Historical usage without provider costs is still excluded from spend totals,
  and cannot be reconstructed as zero-cost usage.

## Inspect uncertain reservations

Use your private PostgreSQL terminal (not React client). First check the audit
and billing records before any manual reconciliation.

```sql
SELECT id, tenant_id, user_id, status, reserved_credits, created_at
FROM credit_reservations
WHERE status IN ('reserved','unknown')
ORDER BY created_at DESC
LIMIT 30;
```

**Do not casually delete or release reservations.** An unknown provider charge
may be real; releasing its hold without reconciling your provider bill weakens
budget enforcement. Old reservations from a crashed worker should be reviewed
before a controlled reconciliation procedure. Reservations only count against
budgets in their creation month.

## Verification and rollback

Database migration is additive and does not modify existing RAG documents.
To disable enforcement while preserving history, use Admin Dashboard to clear
user and tenant monthly limits and unpause all policies. Do not drop budget
schema if usage may be in flight. Roll back the code using Git only after
checking pending reservations and ledger activity.

## Security notes

Credit limits are applied before the LLM is contacted, not through prompting.
Budget values never come from a normal user's request body. Admin endpoints
check role and tenant; updates take the same transaction lock as reservations.
Rate limits, distributed billing reconciliation, Stripe/payment integration,
user account billing, and provider-enforced quotas are outside this milestone.
