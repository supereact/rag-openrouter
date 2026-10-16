"""Non-destructive PostgreSQL migration for monthly budget policies and holds."""
import psycopg
from app.db import _database_url


def migrate() -> None:
    with psycopg.connect(_database_url(), connect_timeout=5) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(78171002)')
        # Requires scripts.migrate_usage_ledger and scripts.migrate_security.
        conn.execute('''CREATE TABLE IF NOT EXISTS tenant_credit_budgets (
            tenant_id BIGINT PRIMARY KEY REFERENCES tenants(id),
            monthly_limit_credits NUMERIC(24,12),
            paused BOOLEAN NOT NULL DEFAULT FALSE,
            reservation_credits NUMERIC(24,12) NOT NULL DEFAULT 0.01,
            CHECK (monthly_limit_credits IS NULL OR
                (monthly_limit_credits>=0 AND monthly_limit_credits<=1000000)),
            CHECK (reservation_credits>0 AND reservation_credits<=1000000)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS user_credit_budgets (
            tenant_id BIGINT NOT NULL REFERENCES tenants(id),
            user_id BIGINT NOT NULL REFERENCES app_users(id),
            monthly_limit_credits NUMERIC(24,12),
            paused BOOLEAN NOT NULL DEFAULT FALSE,
            PRIMARY KEY (tenant_id,user_id),
            CHECK (monthly_limit_credits IS NULL OR
                (monthly_limit_credits>=0 AND monthly_limit_credits<=1000000))
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS credit_reservations (
            id UUID PRIMARY KEY,
            tenant_id BIGINT NOT NULL REFERENCES tenants(id),
            user_id BIGINT NOT NULL REFERENCES app_users(id),
            reserved_credits NUMERIC(24,12) NOT NULL CHECK (reserved_credits>0),
            actual_cost_credits NUMERIC(24,12),
            status TEXT NOT NULL DEFAULT 'reserved'
                CHECK (status IN ('reserved','settled','unknown','released')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finalized_at TIMESTAMPTZ,
            CHECK (actual_cost_credits IS NULL OR actual_cost_credits>=0)
        )''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_credit_reservations_tenant_month
            ON credit_reservations (tenant_id,created_at DESC)
            WHERE status IN ('reserved','unknown')''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_credit_reservations_user_month
            ON credit_reservations (tenant_id,user_id,created_at DESC)
            WHERE status IN ('reserved','unknown')''')
    print('Credit budget migration complete; limits default to unlimited.')


if __name__ == '__main__':
    migrate()
