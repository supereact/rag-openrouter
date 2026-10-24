"""One schema entrypoint; previews by default and never runs on API startup.

Fresh DB: python -m scripts.setup_database --apply
Approved existing DB maintenance: add --upgrade after backup and stopping writers.
Each existing migration commits its own transaction; a failed run is resumable
by repeating the command after fixing the cause. No reset/seed is performed.
"""
import argparse
import importlib
from pathlib import Path

import psycopg

from app.db import _database_url, init_database

STEPS = (
    'init_db', 'migrate_security', 'migrate_accounts', 'migrate_ingestion_jobs',
    'migrate_usage_ledger', 'migrate_credit_budgets', 'migrate_starter_allowances',
    'migrate_credits', 'migrate_conversations', 'migrate_knowledge_bases',
    'migrate_answer_feedback', 'migrate_support',
)
SETUP_LOCK = 78171023


def apply_schema(*, upgrade: bool = False, fts_index: bool = False) -> None:
    # Keep a session-level lock across the migrations' separate transactions.
    # Closing this connection releases it, including on a failed migration.
    with psycopg.connect(_database_url(), autocommit=True, connect_timeout=5) as guard:
        acquired = guard.execute('SELECT pg_try_advisory_lock(%s)', (SETUP_LOCK,)).fetchone()
        if not acquired or not acquired[0]:
            raise RuntimeError('Another schema setup is already running.')
        existing = guard.execute("SELECT EXISTS(SELECT 1 FROM pg_tables WHERE schemaname='public')").fetchone()
        if existing[0] and not upgrade:
            raise RuntimeError('Database is not empty. Approved maintenance requires --upgrade after a backup.')
        for step in STEPS:
            print('Applying ' + step, flush=True)
            if step == 'init_db':
                init_database()
            else:
                importlib.import_module('scripts.' + step).migrate()
        if fts_index:
            sql = (Path(__file__).parent / 'sql/create_fts_index.sql').read_text()
            guard.execute(sql)
        print('Schema setup complete. Existing accounts and ledgers are not reset.')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Apply schema changes; otherwise print the plan only.')
    parser.add_argument('--upgrade', action='store_true', help='Acknowledge approved maintenance on a nonempty database.')
    parser.add_argument('--fts-index', action='store_true', help='Also create the existing optional keyword index.')
    args = parser.parse_args(argv)
    print('Schema plan: ' + ' -> '.join(STEPS))
    if args.fts_index:
        print('Optional: create keyword search index.')
    if not args.apply:
        print('Preview only. No database connection or changes performed.')
        return 0
    try:
        apply_schema(upgrade=args.upgrade, fts_index=args.fts_index)
    except Exception:
        # Driver errors may include connection secrets. Keep detailed inspection
        # private; prior migrations may already be committed, so do not reset DB.
        print('Schema setup stopped. Check connectivity, owner credentials, concurrent setup, and the --upgrade requirement privately. Earlier steps may have committed; fix and rerun without resetting data.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
