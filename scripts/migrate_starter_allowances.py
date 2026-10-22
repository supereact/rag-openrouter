"""Add one-time signup allowances; leaves every existing account unchanged.

Run after migrate_accounts, migrate_usage_ledger and migrate_credit_budgets,
in approved maintenance. API startup never runs this migration automatically.
"""
import psycopg

from app.db import _database_url


def migrate() -> None:
    with psycopg.connect(_database_url(), connect_timeout=5) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(78171022)')
        conn.execute('''CREATE TABLE IF NOT EXISTS user_starter_allowances (
            tenant_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            limit_credits NUMERIC(24,12) NOT NULL CHECK (limit_credits>=0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY(tenant_id,user_id),
            FOREIGN KEY(user_id,tenant_id) REFERENCES app_users(id,tenant_id)
        )''')
    print('Starter allowance table ready. Existing accounts have not been changed.')


if __name__ == '__main__':
    migrate()
