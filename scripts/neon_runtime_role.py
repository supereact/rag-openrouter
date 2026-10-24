"""Provision a restricted runtime role on Neon; preview unless --apply is given.

Only updates DATABASE_URL in the explicit .env.neon file. Retains the owner's
DATABASE_URL_UNPOOLED for separate maintenance. Refuses to rotate an existing
role whose password is not already held by this file.
"""
import argparse
from pathlib import Path
import secrets
from urllib.parse import quote, urlsplit, urlunsplit

from dotenv import dotenv_values, set_key
import psycopg
from psycopg import sql

from scripts.run_neon import environment


def configure(path: Path, *, apply: bool = False) -> None:
    env = environment(path, direct=True)
    values = dotenv_values(path, interpolate=False)
    runtime = urlsplit(values['DATABASE_URL'])
    with psycopg.connect(env['DATABASE_URL'], connect_timeout=10) as conn:
        existing = conn.execute("SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname='rag_app'").fetchone()
        if existing:
            member = conn.execute("SELECT pg_has_role('rag_app','neon_superuser','MEMBER')").fetchone()
            if any(existing) or member[0]:
                raise RuntimeError('Existing runtime role is elevated; review it privately')
            if runtime.username != 'rag_app':
                raise RuntimeError('Runtime role already exists; provide its URL without rotating its password')
            print('PASS: restricted runtime role already configured; no credentials changed')
            return
        if not apply:
            print('Preview: create rag_app with DML/sequence privileges only; local .env is not used or changed')
            return
        password = secrets.token_urlsafe(36)
        conn.execute('CREATE ROLE rag_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS')
        conn.execute(sql.SQL('ALTER ROLE rag_app PASSWORD {}').format(sql.Literal(password)))
        dbname = conn.execute('SELECT current_database()').fetchone()[0]
        owner = conn.execute('SELECT current_user').fetchone()[0]
        conn.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO rag_app').format(sql.Identifier(dbname)))
        conn.execute('GRANT USAGE ON SCHEMA public TO rag_app')
        conn.execute('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO rag_app')
        conn.execute('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO rag_app')
        conn.execute(sql.SQL('ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO rag_app').format(sql.Identifier(owner)))
        conn.execute(sql.SQL('ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO rag_app').format(sql.Identifier(owner)))
    # Preserve Neon's exact pooled hostname and TLS parameters.
    host = runtime.hostname + (f':{runtime.port}' if runtime.port else '')
    url = urlunsplit((runtime.scheme, 'rag_app:' + quote(password, safe='') + '@' + host,
                      runtime.path, runtime.query, runtime.fragment))
    set_key(str(path), 'DATABASE_URL', url, quote_mode='always')
    path.chmod(0o600)
    print('PASS: restricted rag_app role created; only the selected Neon file was updated')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=Path('.env.neon'))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        configure(args.env_file, apply=args.apply)
        return 0
    except Exception as exc:
        print(f'FAIL: Neon runtime role setup ({type(exc).__name__}); no credential details displayed')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
