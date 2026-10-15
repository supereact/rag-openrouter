"""Idempotent, non-destructive security migration for existing ragdb.

Run after a pg_dump backup and before restarting FastAPI with M7 code.
Assigns ALL legacy documents to tenant 'local' / user 'admin'.
"""
import psycopg
from app.db import _database_url


def migrate() -> None:
    with psycopg.connect(_database_url(), connect_timeout=5) as conn:
        # Transaction covers the migration, and advisory lock prevents two
        # migrations from racing. Do not run alongside ingestion traffic.
        conn.execute("SELECT pg_advisory_xact_lock(78170911)")
        conn.execute("""CREATE TABLE IF NOT EXISTS tenants (
            id BIGSERIAL PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS app_users (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT NOT NULL REFERENCES tenants(id),
            username TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('admin','editor','reader')),
            UNIQUE (tenant_id, username),
            UNIQUE (id, tenant_id)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS api_keys (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
            key_hash TEXT NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            revoked_at TIMESTAMPTZ
        )""")
        conn.execute("INSERT INTO tenants(slug) VALUES ('local') ON CONFLICT DO NOTHING")
        tenant_id = conn.execute("SELECT id FROM tenants WHERE slug='local'").fetchone()[0]
        conn.execute("""INSERT INTO app_users(tenant_id, username, role)
            VALUES (%s, 'admin', 'admin') ON CONFLICT (tenant_id, username) DO NOTHING""",
            (tenant_id,),
        )
        admin_id = conn.execute("""SELECT id FROM app_users
            WHERE tenant_id=%s AND username='admin' AND role='admin'""",
            (tenant_id,),
        ).fetchone()
        if admin_id is None:
            raise RuntimeError("The local/admin user exists but isn't an admin")
        admin_id = admin_id[0]
        conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS tenant_id BIGINT REFERENCES tenants(id)")
        conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS owner_user_id BIGINT")
        conn.execute("UPDATE documents SET tenant_id=%s WHERE tenant_id IS NULL", (tenant_id,))
        conn.execute("UPDATE documents SET owner_user_id=%s WHERE owner_user_id IS NULL", (admin_id,))
        conn.execute("ALTER TABLE documents ALTER COLUMN tenant_id SET NOT NULL")
        conn.execute("ALTER TABLE documents ALTER COLUMN owner_user_id SET NOT NULL")
        conn.execute("""DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='documents_owner_tenant_fk') THEN
            ALTER TABLE documents ADD CONSTRAINT documents_owner_tenant_fk
            FOREIGN KEY (owner_user_id, tenant_id) REFERENCES app_users(id,tenant_id);
          END IF;
        END $$""")
        # Previous schema had UNIQUE(content_hash) globally. Replace with
        # owner-scoped deduplication so tenants/users cannot learn each
        # other's document IDs through same-hash uploads.
        conn.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_content_hash_key")
        conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS documents_owner_hash_uq
            ON documents(tenant_id, owner_user_id, content_hash)""")
        conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS documents_id_tenant_uq
            ON documents(id, tenant_id)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS document_acl (
            document_id BIGINT NOT NULL,
            tenant_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            PRIMARY KEY(document_id, user_id),
            FOREIGN KEY(document_id, tenant_id) REFERENCES documents(id,tenant_id) ON DELETE CASCADE,
            FOREIGN KEY(user_id, tenant_id) REFERENCES app_users(id,tenant_id) ON DELETE CASCADE
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS audit_events (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT NOT NULL REFERENCES tenants(id),
            user_id BIGINT NOT NULL REFERENCES app_users(id),
            action TEXT NOT NULL,
            document_id BIGINT,
            result_count INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_tenant ON documents(tenant_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_tenant_time ON audit_events(tenant_id, created_at DESC)")
        total = conn.execute("SELECT count(*) FROM documents WHERE tenant_id=%s", (tenant_id,)).fetchone()[0]
    print(f"Migration complete. Existing local-tenant documents: {total}. No document rows deleted.")


if __name__ == "__main__":
    migrate()
