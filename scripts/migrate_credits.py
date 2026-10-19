"""Add isolated prepaid wallets and payments; does not fund or change existing accounts.

Run after migrate_accounts and migrate_credit_budgets during approved maintenance.
No automatic migration is performed by the API.
"""
import psycopg

from app.db import _database_url


def migrate() -> None:
    with psycopg.connect(_database_url(), connect_timeout=5) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(78171019)')
        conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS credit_reservations_owner_uq
            ON credit_reservations(id,tenant_id,user_id)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS credit_wallets (
            tenant_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('sandbox','live')),
            balance NUMERIC(24,12) NOT NULL DEFAULT 0,
            held NUMERIC(24,12) NOT NULL DEFAULT 0 CHECK (held>=0),
            PRIMARY KEY(tenant_id,user_id,mode),
            FOREIGN KEY(user_id,tenant_id) REFERENCES app_users(id,tenant_id)
        )''')
        # Negative balance is permitted only to record actual provider overage
        # or a refund of already-spent credit; it blocks further reservations.
        conn.execute('''CREATE TABLE IF NOT EXISTS credit_payment_orders (
            id UUID PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('sandbox','live')),
            request_key UUID NOT NULL,
            credits NUMERIC(24,12) NOT NULL CHECK (credits>0),
            service_fee NUMERIC(24,12) NOT NULL CHECK (service_fee>=0),
            total_usd NUMERIC(24,12) NOT NULL CHECK (total_usd=credits+service_fee),
            network TEXT NOT NULL CHECK (network IN ('usdttrc20','usdtbsc','usdterc20')),
            status TEXT NOT NULL DEFAULT 'creating' CHECK (status IN
              ('creating','waiting','confirming','confirmed','sending','partially_paid',
               'finished','failed','expired','refunded','review')),
            provider_payment_id TEXT,
            pay_address TEXT,
            pay_amount NUMERIC(36,18),
            expires_at TIMESTAMPTZ,
            credited_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(tenant_id,user_id,mode,request_key),
            UNIQUE(mode,provider_payment_id),
            UNIQUE(id,tenant_id,user_id,mode),
            UNIQUE(id,mode),
            FOREIGN KEY(user_id,tenant_id) REFERENCES app_users(id,tenant_id)
        )''')
        conn.execute('''CREATE INDEX IF NOT EXISTS credit_payment_orders_recent
            ON credit_payment_orders(tenant_id,user_id,mode,created_at DESC,id DESC)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS credit_wallet_holds (
            reservation_id UUID PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'live' CHECK (mode='live'),
            amount NUMERIC(24,12) NOT NULL CHECK (amount>0),
            active BOOLEAN NOT NULL DEFAULT TRUE,
            FOREIGN KEY(tenant_id,user_id,mode)
              REFERENCES credit_wallets(tenant_id,user_id,mode),
            FOREIGN KEY(reservation_id,tenant_id,user_id)
              REFERENCES credit_reservations(id,tenant_id,user_id)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS credit_wallet_ledger (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('sandbox','live')),
            kind TEXT NOT NULL CHECK (kind IN ('topup','usage','refund')),
            amount NUMERIC(24,12) NOT NULL,
            order_id UUID,
            reservation_id UUID UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(order_id,kind),
            FOREIGN KEY(tenant_id,user_id,mode)
              REFERENCES credit_wallets(tenant_id,user_id,mode),
            FOREIGN KEY(order_id,tenant_id,user_id,mode)
              REFERENCES credit_payment_orders(id,tenant_id,user_id,mode),
            FOREIGN KEY(reservation_id,tenant_id,user_id)
              REFERENCES credit_reservations(id,tenant_id,user_id),
            CHECK ((kind='usage' AND reservation_id IS NOT NULL AND order_id IS NULL AND amount<=0)
              OR (kind='topup' AND order_id IS NOT NULL AND reservation_id IS NULL AND amount>0)
              OR (kind='refund' AND order_id IS NOT NULL AND reservation_id IS NULL AND amount<0))
        )''')
        conn.execute('''CREATE INDEX IF NOT EXISTS credit_wallet_ledger_recent
            ON credit_wallet_ledger(tenant_id,user_id,mode,created_at DESC,id DESC)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS credit_payment_notifications (
            mode TEXT NOT NULL CHECK (mode IN ('sandbox','live')),
            payload_hash TEXT NOT NULL,
            order_id UUID NOT NULL,
            payment_status TEXT NOT NULL,
            processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY(mode,payload_hash),
            FOREIGN KEY(order_id,mode) REFERENCES credit_payment_orders(id,mode)
        )''')
    print('Credits migration complete; existing data preserved, no balances funded.')


if __name__ == '__main__':
    migrate()
