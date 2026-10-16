"""Add password identities, invitations and revocable browser sessions.

Non-destructive: existing API keys/users/documents remain unchanged.
Run once after backing up ragdb, then use scripts.set_user_password to
associate an email/password with the existing admin account.
"""
import psycopg
from app.db import _database_url


def migrate() -> None:
    with psycopg.connect(_database_url(), connect_timeout=5) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(78170918)')
        conn.execute('ALTER TABLE app_users ADD COLUMN IF NOT EXISTS email TEXT')
        conn.execute('ALTER TABLE app_users ADD COLUMN IF NOT EXISTS password_hash TEXT')
        conn.execute('ALTER TABLE app_users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE')
        conn.execute('ALTER TABLE app_users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()')
        conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS app_users_email_unique
                        ON app_users (lower(email)) WHERE email IS NOT NULL''')
        conn.execute('''CREATE TABLE IF NOT EXISTS login_sessions (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_login_sessions_user ON login_sessions(user_id)')
        conn.execute('''CREATE TABLE IF NOT EXISTS signup_invitations (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT NOT NULL REFERENCES tenants(id),
            invited_by BIGINT NOT NULL REFERENCES app_users(id),
            email TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('reader','editor')),
            code_hash TEXT NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_signup_invites_tenant ON signup_invitations(tenant_id,created_at DESC)')
    print('Account migration completed. Existing API keys and documents preserved.')


if __name__ == '__main__':
    migrate()
