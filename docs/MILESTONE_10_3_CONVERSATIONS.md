# Milestone 10.3 — Private Conversation History

## Scope
- Conversations persist in PostgreSQL per authenticated user and tenant.
- Frontend supports new chat, reopen, rename, and delete.
- Each `/conversations/{id}/ask` request executes the **existing** `/ask` budget, retrieval, monitoring, and usage-accounting path before recording the completed exchange.
- The original `/ask` endpoint remains available and does not save history.
- Historical chat messages are **display history**, not multi-turn LLM memory. Subsequent questions still use only the current question and retrieved sources.
- A saved answer is **redacted on read** if its referenced documents are no longer accessible to the current user. Page citations from the original answer are preserved as snapshots when access remains authorized.

## Install
1. Back up PostgreSQL, and commit currently working code.
2. From project root: `git apply --check enterprise-rag-m10-3-conversation-history.patch`, then `git apply ...`.
3. Run `python -m scripts.migrate_conversations` once after enabling your `.venv`.
4. Run `python -m pytest tests/test_conversations.py tests/test_conversations_api.py -v` then the full Python suite.
5. Run `cd frontend && npm test && npm run build`.
6. Restart Uvicorn and the React dev server; the worker doesn't need restart.

## Manual checks
- Reader signs in, asks a question, signs out, signs in, and reopens the saved chat with correct citation anchors.
- Reader B **within the same tenant** receives 404 for Reader A's conversation ID, even if B is admin.
- User in another tenant receives 404 and cannot submit a question to A's conversation; no provider call or budget reservation should occur.
- Rename a conversation, then delete it; confirm it disappears upon reload.
- Remove a document permission for a source, then reopen a conversation that cited it. Saved answer/source excerpts should be hidden.
- Existing `/ask` calls still succeed without creating a conversation.
- Existing user budgets still reject paid requests as before.

## Security and limitations
- Chat content and source snapshots are sensitive and stored **unencrypted** in PostgreSQL; protect backups and DB access accordingly. Backup before deploying migrations.
- Saved answers are redacted if any source document is revoked, but the user's original question is retained. The server does not delete old answers on permission changes.
- Max 100 conversations listed and last 100 turns loaded per conversation, no pagination in this initial version.
- If paid generation succeeds but database persistence fails, the user may see an error despite being charged. Do **not** blindly retry; check ledger and logs.
- Sessions remain memory-only in the browser; conversations can be reopened after signing in again.
- For deployment: add retention policies, page-based pagination, encryption/key management, and idempotent generation requests.

## Rollback
- Revert Git patch with `git apply -R enterprise-rag-m10-3-conversation-history.patch` after stopping API and frontend. Existing PostgreSQL tables remain unless deliberately dropped later. Do not remove tables without first exporting conversation data.
