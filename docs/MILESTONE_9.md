# Milestone 9.1 — Background document ingestion (local MVP)

This patch is additive. Existing synchronous `/documents/upload` and
`/documents/{id}/reindex-pdf` routes remain in place. The React upload UI now
uses `POST /documents/upload-async`; a separate worker indexes the queued file.

## Before applying

Back up `ragdb` with pg_dump and commit your working M8 code. Keep `.env`,
`backups/`, `.ingestion_spool/`, and credentials out of Git.

## Run once (after applying)

```bash
source .venv/bin/activate
python -m scripts.migrate_ingestion_jobs
python -m pytest tests/test_ingestion_jobs.py tests/test_ingestion_api.py -v
```

No existing documents, chunks or embeddings are altered by the migration.

## Start three processes

Terminal 1 — existing PostgreSQL: `docker start enterprise-rag-postgres`

Terminal 2 — HTTP API:

```bash
python -m uvicorn app.main:app --reload --host 127.0.0.1
```

Terminal 3 — ingestion worker (same project and Python environment):

```bash
source .venv/bin/activate
python -m scripts.ingestion_worker
```

Terminal 4 — frontend:

```bash
cd frontend
npm test
npm run build
npm run dev
```

Open http://127.0.0.1:5173, sign in as admin/editor, and upload a **new** PDF
or Markdown file. Check the Recent uploads panel: queued → processing →
completed, then the document appears in the library. For a deterministic
single-job test, run `python -m scripts.ingestion_worker --once` instead of
starting the continuous worker.

## API checks

Pass the existing authorized API key as a Bearer header; do not paste it into
terminal history on shared computers.

- `POST /documents/upload-async` (multipart file): 202 with job ID
- `GET /ingestion-jobs`: current user's newest 25 jobs
- `GET /ingestion-jobs/{uuid}`: status/detail, 404 for another user's job

`reader` receives 403 when uploading. Credentials are never copied into job
records. The worker resolves identity and role from PostgreSQL.

## Limits and recovery

- Files limited to existing 10 MB and parser's page/character limits. A queued
  PDF can fail during extraction: the job will show `failed` and the message.
- Local spool lives in `.ingestion_spool/` (permissions 0700 for new dir,
  0600 for new files). Change `RAG_INGEST_SPOOL` only if **both API and worker**
  share the same trusted local path.
- On normal completion or a handled failure, staged bytes are deleted. They
  are not permanent PDF storage, so page-clickable original PDF viewing remains
  a separate milestone.
- If the worker crashes while a job is `processing`, that job remains in this
  state. **Stop all workers** before manually requeueing:

  ```sql
  UPDATE ingestion_jobs SET status='queued', started_at=NULL, error=NULL
  WHERE id='YOUR_JOB_UUID' AND status='processing';
  ```

  Only requeue if `.ingestion_spool/<32-hex-uuid>.upload` still exists; if the
  file is gone, mark the job failed instead. Never requeue a still-running job.
- This is a local developer implementation, not a hosted production queue.
  Production should use managed private object storage, a durable task system,
  safe retry/lease semantics, virus scanning, size controls at the reverse
  proxy, TLS, SSO and least-privileged database access.
- The current HTTP API still preloads the embedding and reranking models for
  search. The worker separately loads the embedding model once at startup.

## Rollback

To return the frontend to M8, reverse the patch after stopping the worker:

```bash
git apply -R enterprise-rag-milestone-9-background-ingestion.patch
```

The migration table and any queued jobs remain unless explicitly removed.
Reverse the patch **only after the queue is drained or the job files are
handled**, or those jobs will be left unprocessed. Existing indexed documents
are unaffected.
