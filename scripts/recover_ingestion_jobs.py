"""Local operator utility for orphaned ingestion jobs.

Stop ALL ingestion workers before executing --confirm; never reclaim an active
worker. A transaction protects status changes, but cannot undo work already
performed by a process that you accidentally leave running.
"""
from __future__ import annotations

import argparse
from uuid import UUID

from app.db import db_connection
from app.ingestion_jobs import MAX_ATTEMPTS, spool_path


STALE_SQL = """SELECT id, attempt_count FROM ingestion_jobs
    WHERE status='processing'
      AND COALESCE(heartbeat_at, started_at) <
          now() - (%s * interval '1 minute')
    ORDER BY started_at, id"""


def classify_stale(job_id: UUID, attempts: int) -> str:
    """No access to file contents; only existence and safe location are checked."""
    path = spool_path(job_id)
    if path.is_symlink() or not path.is_file():
        return 'missing_input'
    if attempts >= MAX_ATTEMPTS:
        return 'exhausted'
    return 'requeue'


def recover_stale(older_than_minutes: int = 10, confirm: bool = False,
                  workers_stopped: bool = False) -> dict:
    if older_than_minutes < 5:
        raise ValueError('Require at least five minutes to classify stale jobs')
    if confirm and not workers_stopped:
        raise ValueError('Stop all workers and provide --workers-stopped')
    outcomes = {'requeue': 0, 'missing_input': 0, 'exhausted': 0}
    with db_connection() as conn:
        # With --confirm the locked rows cannot be claimed/changed concurrently
        # by another *recovery* command. Worker processes MUST be stopped.
        query = STALE_SQL + (' FOR UPDATE SKIP LOCKED' if confirm else '')
        rows = conn.execute(query, (older_than_minutes,)).fetchall()
        for job_id, attempts in rows:
            disposition = classify_stale(job_id, attempts)
            outcomes[disposition] += 1
            if not confirm:
                print(f'{job_id}: {disposition} (attempts={attempts}) [dry-run]')
                continue
            if disposition == 'requeue':
                conn.execute("""UPDATE ingestion_jobs
                    SET status='queued', started_at=NULL, finished_at=NULL,
                        heartbeat_at=NULL, available_at=now(),
                        error='Recovered by local operator; retry pending'
                    WHERE id=%s AND status='processing'""", (job_id,))
            else:
                conn.execute("""UPDATE ingestion_jobs
                    SET status='failed', finished_at=now(),
                        error=%s
                    WHERE id=%s AND status='processing'""", (
                        'Staged upload missing; cannot recover' if disposition == 'missing_input'
                        else 'Retry limit reached; staged file requires operator cleanup',
                        job_id,
                    ))
    return outcomes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--older-than-minutes', type=int, default=10)
    parser.add_argument('--confirm', action='store_true', help='Make changes; otherwise dry-run')
    parser.add_argument('--workers-stopped', action='store_true',
                        help='Explicit acknowledgement that all ingestion workers are stopped')
    args = parser.parse_args()
    try:
        stats = recover_stale(args.older_than_minutes, args.confirm, args.workers_stopped)
    except ValueError as exc:
        parser.error(str(exc))
    print('Stale jobs:', stats, '(applied)' if args.confirm else '(dry-run)')
    if not args.confirm:
        print('To recover: stop ALL ingestion workers, then rerun with --confirm --workers-stopped')


if __name__ == '__main__':
    main()
