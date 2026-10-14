"""PostgreSQL setup and connection helper."""
from contextlib import contextmanager
from typing import Iterator

import psycopg
from pgvector.psycopg import register_vector

from app.settings import DATABASE_URL


def _database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL missing: copy .env.example to .env")
    return DATABASE_URL


@contextmanager
def db_connection() -> Iterator[psycopg.Connection]:
    with psycopg.connect(_database_url(), connect_timeout=5) as conn:
        register_vector(conn)
        yield conn


def init_database() -> None:
    # CREATE EXTENSION requires sufficient database privileges; the local
    # Docker superuser has these privileges.
    with psycopg.connect(_database_url(), connect_timeout=5) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id BIGSERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                content_hash TEXT NOT NULL UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id BIGSERIAL PRIMARY KEY,
                document_id BIGINT NOT NULL REFERENCES documents(id)
                    ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding VECTOR(384) NOT NULL,
                UNIQUE(document_id, chunk_index)
            )
        """)
        conn.execute("""
            ALTER TABLE chunks ADD COLUMN IF NOT EXISTS page_number INTEGER
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_document_id
            ON chunks (document_id)
        """)
    # For small data, exact vector search is sufficient. Add HNSW after
    # measuring search latency and recall on a representative dataset.
