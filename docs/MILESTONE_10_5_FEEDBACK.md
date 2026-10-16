# Milestone 10.5: Feedback and Quality Analytics

## Apply and migrate

1. Stop the API and back up PostgreSQL (`pg_dump -Fc`).
2. Apply backend patch, run `python -m scripts.migrate_answer_feedback`.
3. Run `python -m pytest tests/test_answer_feedback.py tests/test_answer_feedback_api.py -v` and full suite.
4. Apply frontend patch, run `cd frontend && npm test && npm run build`.
5. Restart FastAPI, then Vite. No embedding reindexing or worker restart required.

## New endpoints

- `GET /conversations/{id}/feedback`: ratings for the current user's chat, excludes revoked-source messages.
- `PUT /conversations/{id}/messages/{message_id}/feedback`: `{"rating":"up"}` or `{"rating":"down","reason":"incorrect"}`.
- `DELETE /conversations/{id}/messages/{message_id}/feedback`: clear one's own rating.
- `GET /admin/feedback?days=7|30`: tenant-only aggregate votes, daily totals and reason categories.

No raw prompts, answers, API tokens, PDF excerpts or chat text are copied into the ledger or admin reports.
An answer can be rated only by its conversation owner while underlying sources remain readable.
Feedback is one current rating per message, not a historical event stream; changing a vote
updates `updated_at`. Deleted chats cascade-delete their feedback.

## Security and operational checks

- Reader cannot query admin quality endpoint (403).
- User A cannot rate/list messages owned by User B or another tenant (404).
- Revoking a source document prevents rating or retrieving a stale rating via API.
- Changing to a different rating updates rather than duplicates the record.
- Removing a rating deletes the record.
- Dashboard counts represent user sentiment **not** verified correctness or an LLM evaluation.
- Dates are based on UTC, 7/30 rolling *calendar* days; all-time counts start at migration.

This is a local development feature. Public deployment still requires rate limiting,
SSO/MFA, auditing and least-privileged DB access.
