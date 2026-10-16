"""Non-destructive schema migration for per-user OpenRouter usage accounting."""
import psycopg
from app.db import _database_url


def migrate() -> None:
    with psycopg.connect(_database_url(), connect_timeout=5) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(78170919)')
        conn.execute('''CREATE TABLE IF NOT EXISTS openrouter_usage_events (
            id UUID PRIMARY KEY,
            tenant_id BIGINT NOT NULL REFERENCES tenants(id),
            user_id BIGINT NOT NULL REFERENCES app_users(id),
            model TEXT NOT NULL,
            prompt_tokens BIGINT,
            completion_tokens BIGINT,
            cost_credits NUMERIC(24,12),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT usage_prompt_nonnegative CHECK (prompt_tokens IS NULL OR prompt_tokens >= 0),
            CONSTRAINT usage_output_nonnegative CHECK (completion_tokens IS NULL OR completion_tokens >= 0),
            CONSTRAINT usage_cost_nonnegative CHECK (cost_credits IS NULL OR cost_credits >= 0)
        )''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_openrouter_usage_tenant_time
                        ON openrouter_usage_events (tenant_id, created_at DESC)''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_openrouter_usage_tenant_user_time
                        ON openrouter_usage_events (tenant_id, user_id, created_at DESC)''')
    print('Usage ledger migration complete. No existing RAG data changed.')


if __name__ == '__main__':
    migrate()
