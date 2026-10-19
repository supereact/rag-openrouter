"""Add private support chats/messages after accounts migration; no live activation."""
import psycopg

from app.db import _database_url


def migrate():
    with psycopg.connect(_database_url(), connect_timeout=5) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(78171020)')
        conn.execute('''CREATE TABLE IF NOT EXISTS support_chats (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            subject VARCHAR(120) NOT NULL CHECK (length(trim(subject))>0),
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
            request_key UUID NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(id,tenant_id,user_id),
            UNIQUE(tenant_id,user_id,request_key),
            FOREIGN KEY(user_id,tenant_id) REFERENCES app_users(id,tenant_id)
        )''')
        conn.execute('''CREATE INDEX IF NOT EXISTS support_chats_owner_recent
            ON support_chats(tenant_id,user_id,updated_at DESC,id DESC)''')
        conn.execute('''CREATE INDEX IF NOT EXISTS support_chats_inbox
            ON support_chats(status,updated_at DESC,id DESC)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS support_messages (
            id BIGSERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            tenant_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            sender_user_id BIGINT NOT NULL REFERENCES app_users(id),
            author_kind TEXT NOT NULL CHECK (author_kind IN ('user','staff')),
            body TEXT NOT NULL CHECK (length(trim(body)) BETWEEN 1 AND 4000),
            request_key UUID NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(chat_id,request_key),
            CHECK (author_kind='staff' OR sender_user_id=user_id),
            FOREIGN KEY(chat_id,tenant_id,user_id) REFERENCES support_chats(id,tenant_id,user_id)
        )''')
        conn.execute('''CREATE INDEX IF NOT EXISTS support_messages_chat_order
            ON support_messages(chat_id,id)''')
    print('Support migration complete; existing application data preserved.')


if __name__ == '__main__':
    migrate()
