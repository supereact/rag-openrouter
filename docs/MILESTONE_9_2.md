# Milestone 9.2 — Private PDF originals and citation page viewer

## Overview

The previous RAG milestones stored extracted PDF text and embeddings, **not the original PDF**. This milestone retains PDF bytes for uploads and reindexing, then serves them through an authenticated FastAPI endpoint. The React UI creates a temporary `blob:` URL, opening at the original physical PDF page. The API key is sent as a bearer header, never as a query string.

## Deploy locally

1. Back up the PostgreSQL DB, **and separately** arrange backups for `.original_pdfs/` once originals are retained. The file directory is not part of `pg_dump`.
2. Apply the Git patch; restart **both** FastAPI and the separate background ingestion worker; restart Vite after frontend changes.
3. No DB migration, dependency change, vector reindex, or new Docker image required.
4. Upload a **new** PDF through the Documents screen; wait for the background worker to complete.
5. Ask a question whose answer is in the PDF and click its `[n]` citation or the source's **Open original PDF** button. It should open at the cited physical page.
6. Try the same with a key that cannot access the PDF. The `GET /documents/{id}/original-pdf` endpoint should return **404** to the unauthorized user and **401** without a key.
7. Run `python -m pytest tests/test_original_pdfs.py tests/test_ingestion_jobs.py -v` and `cd frontend && npm test && npm run build`.

## Legacy PDFs

Documents uploaded before this patch do **not** have their original bytes stored. If you have the PDF file, choose **Replace PDF / reindex** from Documents using its existing owner/admin key. This preserves the document ID and stores original bytes. Otherwise, the viewer shows an `Original PDF unavailable` error. A database backup cannot reconstruct those files.

## Original-PDF filesystem

By default, files are at `.original_pdfs/{document_id}.pdf` (a private directory in the project root). Set `RAG_PDF_STORAGE_DIR` **identically for the API and worker** if you use a different path. Do not place originals in the Vite `public` folder or serve them with `StaticFiles`. Use a dedicated persistent private volume if deployed in containers. Protect, encrypt, and back up originals according to your organization's policies.

Note that PDF bytes and SQL rows are not one atomic transaction across disk and PostgreSQL; in a power loss/restart failure between indexing and file storage, a document may be searchable while its original is unavailable. Retrying a duplicate upload or reindexing it can repair that mismatch. Production deployments should add transactional outbox semantics, object storage, antivirus/scanning, quotas, key rotation, rate limiting, and access logs.

## Operational notes

- The PDF viewer is a browser-native PDF `<iframe>`. Page-fragment behavior can vary with browsers and installed PDF viewers.
- Document access uses the same tenant/owner/ACL SQL predicate as retrieval. Browsers never see the underlying private filesystem path or your API key in the viewer URL.
- The browser keeps PDF blob bytes in memory until the viewer closes. Closing it revokes the object URL.
- Existing synchronous upload/reindex endpoints also store PDF originals, but **background processing remains recommended** for large files.
