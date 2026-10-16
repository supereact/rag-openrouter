# Milestone 10.4 — Knowledge Bases & Document Collections

## Design

This release adds **tenant-scoped collections** of existing indexed documents.
Collection membership is an organizational filter only: it never grants permission
and does not replace the existing `document_acl` check. Vector search, keyword
search, and reranking all receive already-authorized candidates.

## Install

1. Stop FastAPI and the ingestion worker. Make a PostgreSQL custom-format backup.
2. Apply the backend patch, then run `python -m scripts.migrate_knowledge_bases`.
3. Run `python -m pytest tests/test_knowledge_bases.py tests/test_knowledge_bases_api.py -v` and the whole backend suite.
4. Apply the frontend patch, then run `cd frontend && npm test && npm run build`.
5. Restart FastAPI and the frontend. Restart the worker if it was stopped.

The migration is additive; it never reindexes, moves, deletes, or changes access
to an existing document. It creates `knowledge_bases` and
`knowledge_base_documents` with composite foreign keys that prevent cross-tenant
memberships at the database layer.

## Working with collections

- Sign in as an **admin or editor** and open **Knowledge Bases**.
- Create a collection (for example, *Security Policies*).
- Choose a document you own (or any tenant document if admin) and add it.
- Open **Assistant**, select that knowledge base, and ask a question.
- Select **All accessible documents** to return to the previous behavior.
- Readers can select collections with at least one document they are allowed to
  read, but cannot create or edit collections.

The editor who created a collection and tenant admins may manage that
collection. Adding/removing a document requires ownership of that document
(or tenant-admin privileges). Document deletion cascades membership cleanup;
deleting a collection **does not delete the documents**.

The search scope is for **new questions**, including new questions in previously
saved conversations. Historic conversation answers and source citations stay as
saved snapshots and are still redacted if document permissions are later revoked.
Collection selection is not persisted as a preference across browser refreshes.

## API (authenticated bearer key required)

- `GET /knowledge-bases`
- `POST /knowledge-bases` with `{ "name": "Security Policies", "description": "..." }`
- `PATCH /knowledge-bases/{id}` to change name or description
- `DELETE /knowledge-bases/{id}` (membership only; documents remain)
- `GET /knowledge-bases/{id}/documents`
- `PUT /knowledge-bases/{id}/documents/{document_id}`
- `DELETE /knowledge-bases/{id}/documents/{document_id}`
- `POST /search`, `POST /ask`, and `POST /conversations/{id}/ask` accept optional
  `knowledge_base_id: number | null`. `null` means all authorized documents.

Cross-tenant collection IDs return HTTP 404 before embedding generation or
OpenRouter billing. In the SQL, `ACCESS_SQL` remains mandatory in both
retrieval branches. The API does not store collection IDs on existing chat
records or document records; it uses a separate membership table.

## Important verification scenarios

1. Admin creates a collection and adds a permitted PDF.
2. Reader without document access does not see or retrieve that PDF via the collection.
3. Grant explicit document access to reader; the PDF becomes searchable inside
   that collection.
4. Other-tenant users cannot read the collection or include its ID in `/ask`.
5. Editor cannot add a document owned by another editor without admin authority.
6. Switching back to 'All accessible documents' preserves the old behavior.
7. Delete the collection and confirm the underlying documents and embeddings
   still exist in PostgreSQL.

## Rollback

Switch the frontend to **All accessible documents** to bypass collection filtering.
The code patches may be reversed with `git apply -R` if no further edits conflict.
Do not drop the collection tables while the new API is running. The additive
migration is safe to retain even if the application is rolled back.
