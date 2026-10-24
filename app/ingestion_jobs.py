"""Durable metadata for local background document ingestion.

Only job identifiers become spool filenames. Uploaded names are metadata, never
filesystem paths. The worker and API must share the same local spool directory.
"""
from __future__ import annotations

import logging
import os
import threading

import psycopg
from pathlib import Path
from uuid import UUID, uuid4

from app.db import db_connection
from app.file_ingestion import ALLOWED_EXTENSIONS, MAX_FILE_BYTES, extract_document, extract_pdf_pages
from app.security import Principal
from app.original_pdfs import store_pdf
from app import object_storage

logger = logging.getLogger('rag.ingestion')
MAX_ATTEMPTS = 3
HEARTBEAT_SECONDS = 15

SPOOL_DIR = Path(os.getenv(
    'RAG_INGEST_SPOOL',
    str(Path(__file__).resolve().parents[1] / '.ingestion_spool'),
))


def safe_filename(name: str) -> str:
    clean = Path(name.replace('\\', '/')).name
    if not clean or clean in ('.', '..') or Path(clean).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError('Only .txt, .md and .pdf files are supported')
    return clean


def spool_path(job_id: UUID) -> Path:
    """UUID, never user-controlled filename, determines the spool path."""
    return SPOOL_DIR / f'{job_id.hex}.upload'


def queue_upload(name: str, data: bytes, principal: Principal) -> dict:
    if principal.role not in ('admin', 'editor'):
        raise PermissionError('Write permission required')
    title = safe_filename(name)
    if not data:
        raise ValueError('The uploaded file is empty')
    if len(data) > MAX_FILE_BYTES:
        raise ValueError('File exceeds the upload size limit')
    job_id = uuid4()
    if object_storage.enabled():
        object_storage.put_upload(job_id, data)
        try:
            return _insert_job(job_id, title, principal)
        except BaseException:
            object_storage.remove_upload(job_id)
            raise
    SPOOL_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Only the current user should access unprocessed local documents.
    if SPOOL_DIR.is_symlink():
        raise RuntimeError('Spool directory must not be a symlink')
    path = spool_path(job_id)
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, 'wb') as fp:
            fp.write(data)
        return _insert_job(job_id, title, principal)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _insert_job(job_id: UUID, title: str, principal: Principal) -> dict:
    with db_connection() as conn:
        row = conn.execute('''INSERT INTO ingestion_jobs
            (id, tenant_id, user_id, filename, status)
            VALUES (%s, %s, %s, %s, 'queued')
            RETURNING id, filename, status, created_at''',
            (job_id, principal.tenant_id, principal.user_id, title)).fetchone()
    return dict(id=str(row[0]), filename=row[1], status=row[2], created_at=row[3])


def remove_staged(job_id: UUID) -> None:
    if object_storage.enabled():
        object_storage.remove_upload(job_id)
    else:
        spool_path(job_id).unlink(missing_ok=True)


def _job_dict(row) -> dict:
    return dict(
        id=str(row[0]), filename=row[1], status=row[2], document_id=row[3],
        chunk_count=row[4], already_exists=row[5], error=row[6],
        created_at=row[7], started_at=row[8], finished_at=row[9],
        attempt_count=row[10], heartbeat_at=row[11], next_attempt_at=row[12],
    )


_JOB_COLUMNS = '''id, filename, status, document_id, chunk_count,
                  already_exists, error, created_at, started_at, finished_at,
                  attempt_count, heartbeat_at, available_at'''


def list_jobs(principal: Principal, limit: int = 25) -> list[dict]:
    with db_connection() as conn:
        rows = conn.execute(
            f'''SELECT {_JOB_COLUMNS} FROM ingestion_jobs
                WHERE tenant_id=%s AND user_id=%s
                ORDER BY created_at DESC, id DESC LIMIT %s''',
            (principal.tenant_id, principal.user_id, limit),
        ).fetchall()
    return [_job_dict(row) for row in rows]


def get_job(principal: Principal, job_id: UUID) -> dict | None:
    with db_connection() as conn:
        row = conn.execute(
            f'''SELECT {_JOB_COLUMNS} FROM ingestion_jobs
                WHERE id=%s AND tenant_id=%s AND user_id=%s''',
            (job_id, principal.tenant_id, principal.user_id),
        ).fetchone()
    return _job_dict(row) if row else None


def remove_failed_job(principal: Principal, job_id: UUID) -> None:
    if principal.role not in ('admin', 'editor'):
        raise PermissionError('Write permission required')
    with db_connection() as conn:
        row = conn.execute('''SELECT status FROM ingestion_jobs
            WHERE id=%s AND tenant_id=%s AND (user_id=%s OR %s='admin')
            FOR UPDATE''', (job_id, principal.tenant_id, principal.user_id,
                           principal.role)).fetchone()
        if row is None:
            raise PermissionError('Job not found')
        if row[0] != 'failed':
            raise ValueError('Only failed uploads can be removed')
        # Unlink first: a cleanup failure rolls back and retains the job record.
        # Workers may already have removed staged input after terminal failure.
        remove_staged(job_id)
        conn.execute('DELETE FROM ingestion_jobs WHERE id=%s', (job_id,))


def claim_next_job() -> tuple[UUID, str, Principal | None, int] | None:
    """Atomically claim a due job. Attempts are persisted before work starts."""
    with db_connection() as conn:
        row = conn.execute('''
            UPDATE ingestion_jobs AS j
               SET status='processing', started_at=now(), heartbeat_at=now(),
                   finished_at=NULL, error=NULL, attempt_count=j.attempt_count+1
             WHERE j.id = (
                 SELECT id FROM ingestion_jobs
                 WHERE status='queued' AND available_at <= now()
                   AND attempt_count < %s
                 ORDER BY created_at, id
                 FOR UPDATE SKIP LOCKED LIMIT 1
             )
            RETURNING j.id, j.filename, j.tenant_id, j.user_id, j.attempt_count
        ''', (MAX_ATTEMPTS,)).fetchone()
        if row is None:
            return None
        user = conn.execute(
            """SELECT role, username FROM app_users WHERE id=%s AND tenant_id=%s
               AND is_active AND role IN ('admin','editor')""",
            (row[3], row[2]),
        ).fetchone()
        # Return unauthorized claims for terminal finalization by the worker,
        # rather than rolling back the claim and repeatedly taking the same job.
        principal = (Principal(user_id=row[3], tenant_id=row[2],
                               role=user[0], username=user[1]) if user else None)
        return row[0], row[1], principal, int(row[4])


def _heartbeat(job_id: UUID, attempt: int, stop: threading.Event) -> None:
    """Update in-flight liveness without holding open an indexing transaction."""
    while not stop.wait(HEARTBEAT_SECONDS):
        try:
            with db_connection() as conn:
                result = conn.execute('''
                    UPDATE ingestion_jobs SET heartbeat_at=now()
                    WHERE id=%s AND status='processing' AND attempt_count=%s
                ''', (job_id, attempt))
                if getattr(result, 'rowcount', 1) == 0:
                    return
        except Exception:
            logger.warning('Could not update heartbeat for job %s', job_id)


def _is_transient(exc: Exception) -> bool:
    """Only retry conventional transient connection/time-out failures."""
    return isinstance(exc, (psycopg.OperationalError, ConnectionError, TimeoutError))


def retry_delay_seconds(attempt: int) -> int:
    return min(60, 15 * 2 ** max(attempt - 1, 0))


def process_one_job() -> bool:
    """Process one job; retain staged bytes for bounded transient retries."""
    claimed = claim_next_job()
    if claimed is None:
        return False
    # Support previous 3-element tuple in older local mocks.
    job_id, title, principal = claimed[:3]
    attempt = int(claimed[3]) if len(claimed) > 3 else 1
    path = spool_path(job_id)
    finalized = False
    stop = threading.Event()
    heart = threading.Thread(target=_heartbeat, args=(job_id, attempt, stop), daemon=True)
    heart.start()
    try:
        if principal is None or principal.role not in ('admin', 'editor'):
            raise PermissionError('Upload owner is inactive or no longer permitted to ingest documents')
        if object_storage.enabled():
            data = object_storage.read_upload(job_id)
        else:
            with path.open('rb') as stream:
                data = stream.read(MAX_FILE_BYTES + 1)
        if title.lower().endswith('.pdf'):
            from app.services import ingest_pdf_pages
            pages = extract_pdf_pages(title, data)
            doc_id, chunks, exists = ingest_pdf_pages(title, pages, principal)
            store_pdf(doc_id, data)
        else:
            from app.services import ingest_document
            clean_title, content = extract_document(title, data)
            doc_id, chunks, exists = ingest_document(clean_title, content, principal)
        with db_connection() as conn:
            result = conn.execute('''UPDATE ingestion_jobs SET
                status='completed', document_id=%s, chunk_count=%s,
                already_exists=%s, finished_at=now(), heartbeat_at=now()
                WHERE id=%s AND status='processing' AND attempt_count=%s''',
                (doc_id, chunks, exists, job_id, attempt))
            if getattr(result, 'rowcount', 1) == 0:
                raise RuntimeError('Job claim was changed while processing')
        finalized = True
        logger.info('Completed job %s on attempt %s', job_id, attempt)
    except Exception as exc:
        transient = _is_transient(exc) and attempt < MAX_ATTEMPTS
        # We intentionally do not expose uploaded text or provider error details.
        message = (str(exc)[:240] if isinstance(exc, (ValueError, PermissionError, FileNotFoundError))
                   else 'Processing failed; see worker logs')
        try:
            with db_connection() as conn:
                if transient:
                    delay = retry_delay_seconds(attempt)
                    result = conn.execute('''UPDATE ingestion_jobs SET
                        status='queued', error='Temporary processing failure; retry scheduled',
                        available_at=now() + (%s * interval '1 second'),
                        started_at=NULL, heartbeat_at=NULL
                        WHERE id=%s AND status='processing' AND attempt_count=%s''',
                        (delay, job_id, attempt))
                else:
                    result = conn.execute('''UPDATE ingestion_jobs SET
                        status='failed', error=%s, finished_at=now(), heartbeat_at=now()
                        WHERE id=%s AND status='processing' AND attempt_count=%s''',
                        (message, job_id, attempt))
                if getattr(result, 'rowcount', 1) == 0:
                    raise RuntimeError('Job claim changed; cannot finalize')
            finalized = not transient
        except Exception:
            # Critical: if DB finalization fails, keep staged bytes for operator recovery.
            logger.exception('Could not finalize job %s; staged input retained', job_id)
            raise
        logger.warning('Job %s %s after attempt %s', job_id,
                       'scheduled for retry' if transient else 'failed', attempt)
    finally:
        stop.set()
        heart.join(timeout=1)
        if finalized:
            # Success or terminal failure: remove staged document contents.
            remove_staged(job_id)
    return True


def job_health(principal: Principal, stale_minutes: int = 10) -> dict:
    """Tenant-scoped counts; no job contents or cross-tenant metadata."""
    if principal.role != 'admin':
        raise PermissionError('Admin access required')
    with db_connection() as conn:
        rows = conn.execute('''SELECT status, COUNT(*)
            FROM ingestion_jobs WHERE tenant_id=%s GROUP BY status''',
            (principal.tenant_id,)).fetchall()
        stale = conn.execute('''SELECT COUNT(*) FROM ingestion_jobs
            WHERE tenant_id=%s AND status='processing'
              AND COALESCE(heartbeat_at, started_at) <
                  now() - (%s * interval '1 minute')''',
            (principal.tenant_id, stale_minutes)).fetchone()
    counts = {state: 0 for state in ('queued', 'processing', 'completed', 'failed')}
    for state, value in rows:
        counts[state] = int(value)
    return {'counts': counts, 'stale_processing': int(stale[0]),
            'stale_threshold_minutes': stale_minutes}
