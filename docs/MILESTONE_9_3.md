# Milestone 9.3 — Background ingestion reliability and operational visibility

This patch **does not change existing documents, chunk vectors, permissions, stored
PDFs, OpenRouter settings, or frontend code**. It adds bounded retries for
transient ingestion failures, job heartbeats and a tenant-scoped admin status API.

## Apply safely

1. Back up PostgreSQL using `pg_dump` as before.
2. Stop FastAPI and **all** ingestion worker processes. Never run a migration
   or manual recovery against an actively processing job.
3. Apply the Git patch using `git apply --check ...` then `git apply ...`.
4. Run `python -m scripts.migrate_ingestion_jobs` to add **three columns** and
   an index. Existing job rows get `attempt_count=0` and `available_at=now()`.
5. Run `python -m pytest tests/test_worker_reliability.py -v`, followed by the
   full Python suite.
6. Restart FastAPI and the worker. No npm changes are needed.

## Operations

### Bounded automatic retries

New claims increment `attempt_count`. Temporary connection/time-out failures
are retried up to **3 total attempts**, after 15 and 30 seconds. During retry,
`status='queued'` and the private staged file is retained. Permanent validation
errors terminate as `failed` and remove the staged input. On success, the staged
file is removed as before. If the database is unreachable while the worker tries
to record a completion/failure, the staged file is retained; recover it manually
when the database comes back.

### Health API

`GET /ingestion-health` requires an **admin API key** and returns counts scoped
to that admin's tenant and the number of `processing` jobs with heartbeats older
than 10 minutes. It reveals no filenames, user identities or document contents.
It is not a live worker heartbeat when the queue is idle.

```bash
# Run with an API key stored in your shell, not embedded in the URL.
curl -H "Authorization: Bearer $RAG_ADMIN_API_KEY" http://127.0.0.1:8000/ingestion-health
```

### Recover an orphaned processing job after a worker crash

Never reclaim a still-running job. **Stop ALL workers first.** A requeued job
may cause repeated work if a previous process is still indexing. If you cannot
confirm workers are stopped, leave the job for manual investigation.

Dry-run (default; no database writes):

```bash
python -m scripts.recover_ingestion_jobs --older-than-minutes 10
```

After confirming all workers are stopped, apply the recovery:

```bash
python -m scripts.recover_ingestion_jobs --older-than-minutes 10 \
  --confirm --workers-stopped
```

Jobs with a present staged file and fewer than 3 attempts become queued.
Jobs with missing staged files or exhausted attempts become failed. For a
job stopped less than ten minutes ago, prefer waiting until it is stale instead
of lowering the threshold. Files for exhausted attempts are left for the
operator to review and securely remove from `.ingestion_spool/` when appropriate.

## Safety and limitations

- Uses a private local spool directory and PostgreSQL. No Redis, Celery or new
  Docker image is required.
- Long-running jobs send heartbeats every 15 seconds. A database outage may
  prevent a heartbeat. Heartbeat age alone does **not** prove the worker died.
- Failed input bytes are normally removed; manually recovered failures may
  leave private files and require cleanup. Monitor disk space and use a
  restricted file-system account.
- This is **not exactly-once processing**. Ingest services use deduplication
  for repeated document content, but a crash between committing a document and
  marking its job completed may still repeat some work on recovery.
- `--reload` restarts FastAPI, not the separate ingestion worker. Restart the
  worker after applying this patch.
- Do not publish localhost developer APIs without TLS, SSO, least-privilege
  database roles, and operational hardening.

## Rollback

Stop FastAPI/worker before reverting code. Reversing the patch will leave the
added columns in PostgreSQL (safe, additive). However, **do not roll back with
scheduled retries pending**, because the old worker ignores `available_at`.
Drain/review the queue first, then use `git apply -R` on the matching patch.
