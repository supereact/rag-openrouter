"""Non-destructive schema migration for tenant/user-owned conversation history."""
import psycopg
from app.db import _database_url


def migrate() -> None:
    with psycopg.connect(_database_url(), connect_timeout=5) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(78170923)')
        conn.execute('''CREATE TABLE IF NOT EXISTS conversations (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT NOT NULL REFERENCES tenants(id),
            user_id BIGINT NOT NULL REFERENCES app_users(id),
            title VARCHAR(120) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT conversations_title_nonempty CHECK (length(trim(title)) > 0)
        )''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_conversations_owner_recent
            ON conversations(tenant_id,user_id,updated_at DESC,id DESC)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS conversation_messages (
            id BIGSERIAL PRIMARY KEY,
            conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            sources JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT conversation_messages_question_nonempty CHECK (length(trim(question)) > 0)
        )''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_conversation_messages_recent
            ON conversation_messages(conversation_id,id DESC)''')
    print('Conversation migration complete; existing documents, users and keys preserved.')


if __name__ == '__main__':
    migrate()
