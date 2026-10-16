# Add feedback records without modifying conversations or document permissions.
import psycopg
from app.db import _database_url


def migrate() -> None:
    with psycopg.connect(_database_url(),connect_timeout=5) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(78170925)')
        conn.execute('''CREATE TABLE IF NOT EXISTS answer_feedback (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT NOT NULL REFERENCES tenants(id),
            user_id BIGINT NOT NULL REFERENCES app_users(id),
            conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            message_id BIGINT NOT NULL UNIQUE REFERENCES conversation_messages(id) ON DELETE CASCADE,
            rating SMALLINT NOT NULL CHECK (rating IN (-1,1)),
            reason TEXT CHECK (reason IS NULL OR reason IN
              ('incorrect','incomplete','irrelevant','outdated','other')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT feedback_reason_only_downvote CHECK (reason IS NULL OR rating=-1)
        )''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_answer_feedback_tenant_time
            ON answer_feedback (tenant_id,updated_at DESC)''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_answer_feedback_user_conv
            ON answer_feedback (user_id,conversation_id)''')
    print('Answer feedback migration complete; existing chats and documents preserved.')


if __name__ == '__main__':
    migrate()
