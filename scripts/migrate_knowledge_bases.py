"""Additive knowledge-base migration; does not move or delete documents."""
import psycopg
from app.db import _database_url


def migrate():
    with psycopg.connect(_database_url(), connect_timeout=5) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(78170926)')
        conn.execute('''CREATE TABLE IF NOT EXISTS knowledge_bases (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT NOT NULL REFERENCES tenants(id),
            created_by BIGINT NOT NULL REFERENCES app_users(id),
            name VARCHAR(120) NOT NULL,
            description VARCHAR(500) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT knowledge_bases_name_not_blank CHECK (length(trim(name)) > 0)
        )''')
        conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_tenant_casefold_name
            ON knowledge_bases(tenant_id,lower(name))''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_kb_tenant ON knowledge_bases(tenant_id,id)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS knowledge_base_documents (
            knowledge_base_id BIGINT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
            document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            tenant_id BIGINT NOT NULL REFERENCES tenants(id),
            PRIMARY KEY(knowledge_base_id,document_id)
        )''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_kb_docs_tenant
            ON knowledge_base_documents(tenant_id,knowledge_base_id,document_id)''')
        # Tighten data integrity: reject cross-tenant membership even for direct SQL.
        conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_tenant_id
            ON knowledge_bases(id,tenant_id)''')
        conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS uq_docs_tenant_id
            ON documents(id,tenant_id)''')
        conn.execute('''DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='kb_member_kb_tenant_fk') THEN
            ALTER TABLE knowledge_base_documents ADD CONSTRAINT kb_member_kb_tenant_fk
              FOREIGN KEY (knowledge_base_id, tenant_id)
              REFERENCES knowledge_bases(id, tenant_id) ON DELETE CASCADE;
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='kb_member_doc_tenant_fk') THEN
            ALTER TABLE knowledge_base_documents ADD CONSTRAINT kb_member_doc_tenant_fk
              FOREIGN KEY (document_id, tenant_id)
              REFERENCES documents(id, tenant_id) ON DELETE CASCADE;
          END IF;
        END $$''')
    print('Knowledge base migration complete: existing documents preserved.')


if __name__ == '__main__':
    migrate()
