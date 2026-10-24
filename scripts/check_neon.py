"""Read-only Neon database and private-bucket readiness checks. No secrets logged."""
import argparse
import os
from pathlib import Path

import psycopg

from scripts.run_neon import environment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=Path('.env.neon'))
    parser.add_argument('--before-schema', action='store_true')
    args = parser.parse_args()
    try:
        os.environ.update(environment(args.env_file, direct=True))
        from app import object_storage
        from scripts.check_production import REQUIRED_TABLES
        with psycopg.connect(os.environ['DATABASE_URL'], connect_timeout=10) as conn:
            conn.execute('SET TRANSACTION READ ONLY')
            version = int(conn.execute('SHOW server_version_num').fetchone()[0]) // 10000
            tables = {row[0] for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()}
            if args.before_schema:
                if tables & REQUIRED_TABLES:
                    raise RuntimeError('Application schema already exists; do not treat this database as empty')
                print(f'PASS: Neon PostgreSQL {version}; no application tables present')
            else:
                missing = REQUIRED_TABLES - tables
                if missing:
                    raise RuntimeError('Required application schema is missing')
                vector = conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
                if not vector:
                    raise RuntimeError('pgvector is missing')
                print(f'PASS: Neon PostgreSQL {version}; application schema and pgvector present')
        if not args.before_schema:
            runtime = environment(args.env_file)
            with psycopg.connect(runtime['DATABASE_URL'], connect_timeout=10) as conn:
                role = conn.execute('''SELECT current_user,rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls,
                    pg_has_role(current_user,'neon_superuser','MEMBER') FROM pg_roles WHERE rolname=current_user''').fetchone()
                if not role or role[0] != 'rag_app' or role[1] or role[2]:
                    raise RuntimeError('Use the restricted runtime database role')
            print('PASS: application connection uses the restricted rag_app role')
        for kind in ('pdf', 'upload'):
            name = object_storage.bucket(kind)
            object_storage.call('head_bucket', Bucket=name)
            acl = object_storage.call('get_bucket_acl', Bucket=name)
            if any(grant.get('Grantee', {}).get('Type') == 'Group'
                   for grant in acl.get('Grants', [])):
                raise RuntimeError('A document bucket grants group/public access')
            print(f'PASS: private bucket {name} is accessible')
        return 0
    except Exception as exc:
        # Connection and SDK exceptions may include secrets; only safe type output.
        print(f'FAIL: Neon readiness check ({type(exc).__name__}); inspect configuration privately')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
