"""Document ingestion, semantic search, and optional grounded answer generation."""
import hashlib

from app.chunking import chunk_text
from app.db import db_connection
from app.embeddings import embed_many
from app.schemas import SearchHit
from app.llm import generate_grounded_answer


def ingest_document(title: str, text: str) -> tuple[int, int, bool]:
    cleaned_title = title.strip()
    parts = chunk_text(text)
    if not parts:
        raise ValueError("Document must contain non-whitespace text")
    digest = hashlib.sha256((cleaned_title + "\n" + text).encode("utf-8")).hexdigest()

    with db_connection() as conn:
        found = conn.execute(
            "SELECT id FROM documents WHERE content_hash = %s", (digest,)
        ).fetchone()
        if found:
            return int(found[0]), 0, True

    # Embed outside transaction to avoid holding a DB transaction while
    # loading/inferencing the local model (which can be slow on first use).
    vectors = embed_many(parts)

    with db_connection() as conn:
        row = conn.execute(
            """INSERT INTO documents (title, content_hash)
               VALUES (%s, %s)
               ON CONFLICT (content_hash) DO NOTHING
               RETURNING id""",
            (cleaned_title, digest),
        ).fetchone()
        if row is None:
            found = conn.execute(
                "SELECT id FROM documents WHERE content_hash = %s", (digest,)
            ).fetchone()
            assert found is not None
            return int(found[0]), 0, True
        doc_id = int(row[0])
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO chunks (document_id, chunk_index, content, embedding)
                   VALUES (%s, %s, %s, %s)""",
                [(doc_id, i, part, vectors[i]) for i, part in enumerate(parts)],
            )
    return doc_id, len(parts), False


def search_documents(question: str, top_k: int = 3) -> list[SearchHit]:
    embedding = embed_many([question])[0]
    with db_connection() as conn:
        rows = conn.execute(
            """
            SELECT d.id, d.title, c.chunk_index, c.content,
                   1 - (c.embedding <=> %s) AS similarity
            FROM chunks AS c
            JOIN documents AS d ON d.id = c.document_id
            ORDER BY c.embedding <=> %s
            LIMIT %s
            """,
            (embedding, embedding, top_k),
        ).fetchall()
    return [
        SearchHit(
            source_number=i,
            document_id=int(row[0]),
            title=row[1],
            chunk_index=int(row[2]),
            content=row[3],
            similarity=float(row[4]),
        )
        for i, row in enumerate(rows, start=1)
    ]


def answer_question(question: str, sources: list[SearchHit]) -> str:
    if not sources:
        return "No indexed sources are available to answer that question."

    context = "\n\n".join(
        f"[{hit.source_number}] {hit.title} (document {hit.document_id}, "
        f"chunk {hit.chunk_index})\n{hit.content}"
        for hit in sources
    )
    return generate_grounded_answer(question, context)
