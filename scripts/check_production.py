"""Read-only release preflight. Never prints connection strings or credentials."""
import os
from pathlib import Path
import sys

from app import settings
from app.db import db_connection

REQUIRED_TABLES = {
    'tenants', 'app_users', 'api_keys', 'documents', 'chunks', 'document_acl',
    'audit_events', 'login_sessions', 'signup_invitations', 'ingestion_jobs',
    'openrouter_usage_events', 'credit_reservations', 'tenant_credit_budgets',
    'user_credit_budgets', 'user_starter_allowances', 'conversations',
    'conversation_messages', 'knowledge_bases', 'knowledge_base_documents',
    'answer_feedback', 'support_chats', 'support_messages',
}


def check() -> list[str]:
    problems = []
    if settings.LLM_PROVIDER != 'openrouter' or not settings.OPENROUTER_API_KEY:
        problems.append('Configure OpenRouter and a nonempty production provider key.')
    if settings.RAG_PAYMENTS_MODE != 'disabled' or settings.RAG_WALLET_ENFORCEMENT != 'false':
        problems.append('This release requires payments disabled and prepaid enforcement off.')
    if settings.RAG_PUBLIC_REGISTRATION_ENABLED != 'true':
        problems.append('This release requires public registration enabled.')
    for name in ('RAG_INGEST_SPOOL', 'RAG_PDF_STORAGE_DIR', 'HF_HOME'):
        value = os.getenv(name, '')
        path = Path(value)
        if (not value or not path.is_dir() or path.is_symlink()
                or not os.access(path, os.R_OK | os.W_OK | os.X_OK)):
            problems.append(f'{name} must be an accessible persistent directory.')
        elif path.stat().st_mode & 0o077:
            problems.append(f'{name} must not grant group or other access (use mode 0700).')
    try:
        with db_connection() as conn:
            conn.execute('SET TRANSACTION READ ONLY')
            tables = {row[0] for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()}
            if missing := REQUIRED_TABLES - tables:
                problems.append('Missing required tables: ' + ', '.join(sorted(missing)))
            elevated = conn.execute('''SELECT rolsuper OR rolcreatedb OR rolcreaterole
                FROM pg_roles WHERE rolname=current_user''').fetchone()
            if not elevated or elevated[0]:
                problems.append('Use the restricted runtime role, not the database owner/superuser.')
            owner = conn.execute('''SELECT EXISTS(SELECT 1 FROM pg_tables
                WHERE schemaname='public' AND tableowner=current_user)''').fetchone()
            if owner and owner[0]:
                problems.append('The runtime role must not own application tables.')
            dimension = conn.execute('''SELECT format_type(atttypid,atttypmod)
                FROM pg_attribute WHERE attrelid=to_regclass('public.chunks')
                    AND attname='embedding' AND NOT attisdropped''').fetchone()
            if not dimension or dimension[0] != 'vector(384)':
                problems.append('The existing application requires vector(384); verify model compatibility.')
            if not missing:
                allowed = conn.execute('''SELECT has_table_privilege(current_user,
                    'public.user_starter_allowances','SELECT') AND has_table_privilege(
                    current_user,'public.user_starter_allowances','INSERT')''').fetchone()
                if not allowed or not allowed[0]:
                    problems.append('The runtime role needs starter-allowance read/write grants.')
    except Exception:
        # Driver exceptions can contain connection parameters. Keep them private.
        problems.append('Database preflight failed. Check connectivity, migrations and role grants privately.')
    return problems


def main() -> int:
    problems = check()
    for problem in problems:
        print('FAIL: ' + problem)
    if not problems:
        print('PASS: read-only production preflight. Live smoke/restore tests are still required.')
    return int(bool(problems))


if __name__ == '__main__':
    sys.exit(main())
