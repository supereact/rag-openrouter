# Enterprise RAG Knowledge Assistant — Codex handoff

## Objective
Continue developing an enterprise-style, multi-tenant retrieval-augmented generation application without disrupting working features or user data.

## Existing stack (verify in repository)
- Python 3.12; FastAPI; PostgreSQL 17 + pgvector (often an existing Docker container).
- Sentence Transformers embedding model `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions).
- Hybrid PostgreSQL full-text + pgvector search, reciprocal rank fusion, and optional local cross-encoder reranking (`cross-encoder/ms-marco-MiniLM-L-6-v2`).
- OpenRouter API via OpenAI-compatible Python client; OpenAI provider may also be configurable.
- React, TypeScript, Vite, Tailwind; Markdown answers, clickable source citations, PDF viewer.

## Features built over prior milestones (implementation must be checked)
1. Text/Markdown/PDF ingestion, chunking, embeddings, semantic retrieval and grounded answers.
2. Page-aware PDF citations; original PDF private storage/authorized viewing.
3. Async ingestion with separate worker, job states, retries, heartbeats and recovery.
4. Authentication via API keys and invited email/password accounts, tenant/user roles, ACLs, admin dashboard and user management.
5. Persistent per-user OpenRouter usage ledger with costs when provider reports them; admin graphs/table; tenant and user monthly budgets with reservations and pause controls.
6. Saved user conversations with title/new chat/rename/delete and permission-aware history rendering.
7. Knowledge base collections and chat scope filtering, without bypassing document ACLs.
8. Answer thumbs-up/down feedback and admin quality analytics were the most recent milestone. A corrected M10.5A backend patch was provided because the original conflicted with knowledge-bases imports. **Confirm the backend patch, migration, and M10.5B frontend patch actually exist in the working tree before assuming this is complete.**
9. Observability for search and LLM latency, errors, token usage and provider-reported costs; tenant-scoped admin metrics.
10. Containerized deployment rehearsal (M9.5) was discussed but deferred; do not assume it was installed or used.

## Important recent lessons
- Earlier patches conflicted when generated from stale baselines; always diff against the ACTUAL local working tree, not an assumed older milestone.
- A large PDF extracted-text hard limit was removed; other limits (bytes/pages) must be inspected, not guessed.
- Original PDF not found can be due to missing stored bytes or permissions; use an authorized API and preserve source security.
- React tests previously needed explicit Testing Library cleanup and citation-rendering-aware assertions; favor observable behavior over exact text-node assumptions.
- UI layouts must handle long filenames and responsive widths.
- Python API and worker are separate; when backend code changes, restarting Uvicorn does not restart the ingestion worker.

## Pending work / ideas — user must prioritize
- Validate M10.5 feedback feature live, including migrations, frontend tests and tenant isolation.
- M10.6 account security: email verification, password reset, rate limits, MFA/SSO, session review/revocation.
- Improved document collection UX and admin/user dashboards.
- True multi-turn conversational context with authorized citation retrieval, secure history summarization.
- Better evaluation coverage for reranking/knowledge-base isolation, cost monitoring and deployment readiness.

## First Codex task
1. Inspect `git status`, project tree, `README.md`, `app/main.py`, authentication/security/retrieval/usage files, `frontend/src/App.tsx`, migrations and tests as needed.
2. Summarize which milestone features are actually present and which recent patches/migrations may still need applying. Do not assume this handoff is perfectly up to date.
3. Run available targeted tests and frontend build (if dependencies are installed). Report failures and probable causes.
4. Propose the safest NEXT small feature or bug fix; ask for confirmation before any data-altering or broad refactor.

## Operating and secret safety
Never print or commit `.env` contents, database backups, generated API keys, private PDFs, or credentials. Avoid `docker compose down -v`, deleting database volumes, and hardcoded test credentials in production code. Preserve data and user authorization constraints. Large changes need a concrete test plan, migration plan and rollback.
