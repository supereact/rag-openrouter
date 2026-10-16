# Repository instructions for Codex

## Project
Enterprise RAG Knowledge Assistant: Python/FastAPI backend, PostgreSQL 17 + pgvector, local Sentence Transformers embeddings, hybrid retrieval and cross-encoder reranking, OpenRouter-generated answers, React/TypeScript/Tailwind frontend.

## Ground truth
The checked-out repository and its tests are the source of truth. Read the relevant files before changing anything; do not assume historical milestone notes precisely match current code. Consult `CODEX_HANDOFF.md` for historical context, then verify its claims.

## Scope and working style
- Prefer small, focused changes and Git-compatible diffs. Preserve existing functionality and API contracts unless explicitly asked to change them.
- Before edits, inspect `git status`, relevant files, existing tests, and routes/schema affected by the task. Do not overwrite uncommitted work.
- State a brief plan for a multi-file task, implement it, run targeted tests, and report test/build results and limitations.
- Keep frontend and backend types/contracts consistent. Add regression tests for bug fixes.
- Before running destructive commands, dropping/changing tables, deleting documents, overwriting data, or resetting Docker volumes, ask for approval. Use additive, repeatable DB migrations whenever possible.
- Do not modify `.env` or print credentials, API keys, tokens, database passwords, or private document text in logs. Never commit secrets, `node_modules`, runtime caches, uploaded PDFs, staged files, or DB backups.
- Do not assume a Docker image/network/container name without checking. Preserve the existing PostgreSQL volume and data; no unrequested database recreation.

## Security invariants
- Enforce tenant isolation, document ownership, and ACLs in database retrieval for vector AND keyword searches, before reranking or OpenRouter calls. Knowledge-base membership never grants document access.
- Preserve authentication/authorization on upload, list, source PDF download, reindex, share, delete, saved conversations, feedback, metrics, usage, budgets, and admin endpoints.
- A user must not see another user's private conversations or saved excerpts after document access is revoked.
- Existing API-key auth and password/session auth should keep working unless explicitly directed otherwise.
- Keep provider costs as unreported if absent; never silently treat missing costs as zero. Preserve atomic credit reservations and settlement for concurrent requests.

## Architecture notes
- API and ingestion worker are separate processes. Model loading may be cached and warmed during FastAPI startup; worker has its own process lifecycle.
- PostgreSQL stores documents, chunks, users, jobs, usage, budgets, conversations, collections, and feedback. Original PDFs live in a private local directory and require an authorized API to access.
- Retrieval modes: `vector`, `hybrid`, `rerank`. Keep PDF physical page metadata and citation authorization intact.
- OpenRouter is configured through the OpenAI-compatible SDK; local embeddings do not require paid embedding calls.
- Docker Compose deployment rehearsal is optional and may NOT have been deployed; avoid changing the user's existing PostgreSQL setup.

## Useful checks (adapt to actual repo)
- Backend: `source .venv/bin/activate && python -m pytest tests/ -q`
- Frontend: `cd frontend && npm test && npm run build`
- Patch: `git diff --check` and review `git diff`.
- Confirm database and worker integration separately; mocked/offline tests are not proof of live PostgreSQL/OpenRouter behavior.

## Output after each change
Summarize modified files, rationale, security implications, migrations/configuration needed, tests run with outcomes, unverified items, and rollback guidance when appropriate. Prefer a reviewable diff over a full-project rewrite.
