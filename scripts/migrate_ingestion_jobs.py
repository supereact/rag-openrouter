"""Additive migration for local asynchronous document ingestion."""
from app.db import db_connection


def migrate() -> None:
    with db_connection() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS ingestion_jobs (
            id UUID PRIMARY KEY,
            tenant_id BIGINT NOT NULL REFERENCES tenants(id),
            user_id BIGINT NOT NULL,
            filename TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued' CHECK (
                status IN ('queued', 'processing', 'completed', 'failed')
            ),
            document_id BIGINT REFERENCES documents(id) ON DELETE SET NULL,
            chunk_count INTEGER,
            already_exists BOOLEAN,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            FOREIGN KEY(user_id, tenant_id) REFERENCES app_users(id, tenant_id)
        )''')
        # Additive, safe for databases that already contain jobs.
        conn.execute("""ALTER TABLE ingestion_jobs
                        ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0""")
        conn.execute("""ALTER TABLE ingestion_jobs
                        ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ NOT NULL DEFAULT now()""")
        conn.execute("""ALTER TABLE ingestion_jobs
                        ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ""")
        conn.execute('''CREATE INDEX IF NOT EXISTS ingestion_jobs_owner_created_idx
                        ON ingestion_jobs(tenant_id, user_id, created_at DESC)''')
        conn.execute("""CREATE INDEX IF NOT EXISTS ingestion_jobs_due_idx
                        ON ingestion_jobs(available_at, created_at, id)
                        WHERE status='queued'""")
        conn.execute('''CREATE INDEX IF NOT EXISTS ingestion_jobs_queue_idx
                        ON ingestion_jobs(created_at, id)
                        WHERE status='queued' ''')
    print('Ingestion job reliability columns ready; existing documents unchanged.')


if __name__ == '__main__':
    migrate()
