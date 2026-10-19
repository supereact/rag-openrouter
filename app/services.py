"""Document ingestion, semantic search, and optional grounded answer generation."""
import hashlib
import os
from functools import lru_cache

from app.chunking import chunk_text
from app.db import db_connection
from app.security import Principal
from app.embeddings import embed_many
from app.chinese import contains_han, search_terms
from app.settings import RERANKER_MODEL
from app.model_loading import load_cached_model
from app.schemas import SearchHit
from app.llm import generate_grounded_answer
from app.retrieval import Candidate, reciprocal_rank_fusion, row_to_candidate, rerank_candidates


# Both SQL branches must use the SAME filter before rank fusion/reranking.
# Parameters are from a trusted, DB-resolved principal, never user input.
ACCESS_SQL = """d.tenant_id=%s AND (
    d.owner_user_id=%s OR %s='admin' OR EXISTS (
        SELECT 1 FROM document_acl a
        WHERE a.document_id=d.id AND a.tenant_id=d.tenant_id AND a.user_id=%s
    )
)"""


def access_args(principal: Principal) -> tuple:
    return (principal.tenant_id, principal.user_id, principal.role, principal.user_id)


def _ensure_can_write(principal: Principal) -> None:
    if not isinstance(principal, Principal) or principal.role not in ("admin", "editor"):
        raise PermissionError("Write permission required")


def _audit(conn, principal: Principal, action: str,
           document_id: int | None = None, result_count: int | None = None):
    # Avoid logging prompts, document contents, key material or personal data.
    conn.execute(
        """INSERT INTO audit_events(tenant_id,user_id,action,document_id,result_count)
           VALUES (%s,%s,%s,%s,%s)""",
        (principal.tenant_id, principal.user_id, action, document_id, result_count),
    )


def assert_document_writable(principal: Principal, document_id: int) -> None:
    _ensure_can_write(principal)
    with db_connection() as conn:
        row = conn.execute(
            """SELECT 1 FROM documents WHERE id=%s AND tenant_id=%s
               AND (owner_user_id=%s OR %s='admin')""",
            (document_id, principal.tenant_id, principal.user_id, principal.role),
        ).fetchone()
    if row is None:
        raise PermissionError("Document not found or not writable")


def visible_documents(principal: Principal) -> list[dict]:
    with db_connection() as conn:
        rows = conn.execute(
            f"""SELECT d.id, d.title, d.owner_user_id, d.created_at
                FROM documents d WHERE {ACCESS_SQL}
                ORDER BY d.id""", access_args(principal),
        ).fetchall()
    return [dict(id=r[0], title=r[1], owner_user_id=r[2], created_at=r[3]) for r in rows]


def share_document(principal: Principal, document_id: int, target_username: str):
    assert_document_writable(principal, document_id)
    with db_connection() as conn:
        target = conn.execute(
            """SELECT id FROM app_users WHERE tenant_id=%s AND username=%s""",
            (principal.tenant_id, target_username),
        ).fetchone()
        if not target:
            raise ValueError("Target user not found in your tenant")
        conn.execute(
            """INSERT INTO document_acl(document_id,tenant_id,user_id)
               VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""",
            (document_id, principal.tenant_id, target[0]),
        )
        _audit(conn, principal, "document.share", document_id)


def delete_document(principal: Principal, document_id: int) -> None:
    assert_document_writable(principal, document_id)
    with db_connection() as conn:
        deleted = conn.execute(
            """DELETE FROM documents WHERE id=%s AND tenant_id=%s
               AND (owner_user_id=%s OR %s='admin') RETURNING id""",
            (document_id, principal.tenant_id, principal.user_id, principal.role),
        ).fetchone()
        if not deleted:
            raise PermissionError("Document not found or not writable")
        _audit(conn, principal, "document.delete", document_id)


def ingest_document(title: str, text: str, principal: Principal) -> tuple[int, int, bool]:
    _ensure_can_write(principal)
    cleaned_title = title.strip()
    parts = chunk_text(text)
    if not parts:
        raise ValueError("Document must contain non-whitespace text")
    digest = hashlib.sha256((cleaned_title + "\n" + text).encode("utf-8")).hexdigest()

    with db_connection() as conn:
        found = conn.execute(
            "SELECT id FROM documents WHERE tenant_id=%s AND owner_user_id=%s AND content_hash=%s",
            (principal.tenant_id, principal.user_id, digest)
        ).fetchone()
        if found:
            return int(found[0]), 0, True

    # Embed outside transaction to avoid holding a DB transaction while
    # loading/inferencing the local model (which can be slow on first use).
    vectors = embed_many(parts)

    with db_connection() as conn:
        row = conn.execute(
            """INSERT INTO documents (title, content_hash, tenant_id, owner_user_id)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (tenant_id, owner_user_id, content_hash) DO NOTHING
               RETURNING id""",
            (cleaned_title, digest, principal.tenant_id, principal.user_id),
        ).fetchone()
        if row is None:
            found = conn.execute(
                "SELECT id FROM documents WHERE tenant_id=%s AND owner_user_id=%s AND content_hash=%s",
            (principal.tenant_id, principal.user_id, digest)
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
        _audit(conn, principal, "document.create", doc_id)
    return doc_id, len(parts), False



def ingest_pdf_pages(
    title: str, pages: list[tuple[int, str]], principal: Principal,
    replace_document_id: int | None = None,
) -> tuple[int, int, bool]:
    """Index PDF pages; reindex is owner/admin-only and preserves document ID."""
    _ensure_can_write(principal)
    cleaned_title = title.strip()
    full_text = "\n\n".join(text for _, text in pages)
    digest = hashlib.sha256((cleaned_title + "\n" + full_text).encode("utf-8")).hexdigest()
    numbered_parts = [(page, part) for page, text in pages for part in chunk_text(text)]
    if not numbered_parts:
        raise ValueError("No indexable PDF text")

    if replace_document_id is not None:
        assert_document_writable(principal, replace_document_id)
    else:
        with db_connection() as conn:
            existing = conn.execute(
                """SELECT id FROM documents
                   WHERE tenant_id=%s AND owner_user_id=%s AND content_hash=%s""",
                (principal.tenant_id, principal.user_id, digest),
            ).fetchone()
            if existing:
                return int(existing[0]), 0, True

    vectors = embed_many([part for _, part in numbered_parts])
    with db_connection() as conn:
        if replace_document_id is None:
            row = conn.execute(
                """INSERT INTO documents (title, content_hash, tenant_id, owner_user_id)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (tenant_id, owner_user_id, content_hash)
                   DO NOTHING RETURNING id""",
                (cleaned_title, digest, principal.tenant_id, principal.user_id),
            ).fetchone()
            if row is None:
                existing = conn.execute(
                    """SELECT id FROM documents
                       WHERE tenant_id=%s AND owner_user_id=%s AND content_hash=%s""",
                    (principal.tenant_id, principal.user_id, digest),
                ).fetchone()
                return int(existing[0]), 0, True
            doc_id = int(row[0])
        else:
            doc_id = replace_document_id
            row = conn.execute(
                """SELECT title FROM documents WHERE id=%s AND tenant_id=%s
                   AND (owner_user_id=%s OR %s='admin') FOR UPDATE""",
                (doc_id, principal.tenant_id, principal.user_id, principal.role),
            ).fetchone()
            if not row:
                raise PermissionError("Document not found or not writable")
            if row[0] != cleaned_title:
                raise ValueError("Existing PDF filename must match the document title")
            # Do not create two documents with the same owner + content hash.
            collision = conn.execute(
                """SELECT 1 FROM documents WHERE tenant_id=%s
                   AND owner_user_id=(SELECT owner_user_id FROM documents WHERE id=%s)
                   AND content_hash=%s AND id<>%s""",
                (principal.tenant_id, doc_id, digest, doc_id),
            ).fetchone()
            if collision:
                raise ValueError("Identical document already exists for the owner")
            conn.execute("UPDATE documents SET content_hash=%s WHERE id=%s", (digest, doc_id))
            conn.execute("DELETE FROM chunks WHERE document_id=%s", (doc_id,))
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO chunks
                   (document_id, chunk_index, content, embedding, page_number)
                   VALUES (%s, %s, %s, %s, %s)""",
                [(doc_id, i, part, vectors[i], page)
                 for i, (page, part) in enumerate(numbered_parts)],
            )
        _audit(conn, principal, "document.reindex" if replace_document_id else "document.create", doc_id)
    return doc_id, len(numbered_parts), False


# English retains the existing vector default; Han queries add literal matches.
# Set RAG_RETRIEVAL_MODE=hybrid or =rerank to opt in for other queries.
RETRIEVAL_MODES = {"vector", "hybrid", "rerank"}


@lru_cache(maxsize=1)
def _get_reranker():
    # Import and download weights only when reranking is explicitly requested.
    from sentence_transformers import CrossEncoder
    return load_cached_model(CrossEncoder, RERANKER_MODEL)


def _cross_encoder_rerank(question: str, candidates: list[Candidate]) -> list[Candidate]:
    if not candidates:
        return []
    model = _get_reranker()
    pairs = [(question, hit.content) for hit in candidates]
    scores = model.predict(pairs, show_progress_bar=False)
    return rerank_candidates(question, candidates, [float(score) for score in scores])


def search_documents(
    question: str, top_k: int = 3, mode: str | None = None,
    *, principal: Principal, knowledge_base_id: int | None = None,
) -> list[SearchHit]:
    """Retrieve chunks using vector, hybrid (RRF), or hybrid + reranking.

    All returned `similarity` values remain cosine similarity; rank fusion and
    cross-encoder scores are only used for ORDERING, never mislabeled as cosine.
    """
    selected_mode = (mode or os.getenv("RAG_RETRIEVAL_MODE", "vector")).strip().lower()
    if selected_mode not in RETRIEVAL_MODES:
        raise ValueError(f"Unknown retrieval mode: {selected_mode}")
    if not 1 <= top_k <= 10:
        raise ValueError("top_k must be between 1 and 10")
    han_query = contains_han(question)
    # Preserve explicit vector-only evaluation; normal Chinese requests also
    # retrieve lexical candidates instead of relying on the English baseline.
    if mode is None and selected_mode == 'vector' and han_query:
        selected_mode = 'hybrid'

    # Candidate pool is deliberately larger than the final top_k so that
    # lexical search can rescue vectors ranked outside top 5.
    pool_size = max(40, top_k * 5) if selected_mode != "vector" else top_k
    if not isinstance(principal, Principal):
        raise PermissionError("Authenticated principal required")
    if knowledge_base_id is not None:
        # Check tenant ownership before expensive embedding or reranking work.
        from app.knowledge_bases import assert_tenant_collection
        assert_tenant_collection(principal, knowledge_base_id)
    # The collection filter is applied to BOTH ranking branches, and the
    # original document ACL is always enforced. Never filter after reranking.
    kb_where = (" AND EXISTS (SELECT 1 FROM knowledge_base_documents kbd "
                "WHERE kbd.knowledge_base_id=%s AND kbd.document_id=d.id "
                "AND kbd.tenant_id=d.tenant_id)") if knowledge_base_id is not None else ""
    kb_args = (knowledge_base_id,) if knowledge_base_id is not None else ()
    embedding = embed_many([question], query=True)[0]
    select_columns = """c.id, d.id, d.title, c.chunk_index, c.content,
                        c.page_number, 1 - (c.embedding <=> %s) AS similarity"""

    with db_connection() as conn:
        vector_rows = conn.execute(
            f"""SELECT {select_columns}
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE {ACCESS_SQL}{kb_where}
                ORDER BY c.embedding <=> %s
                LIMIT %s""",
            (embedding, *access_args(principal), *kb_args, embedding, pool_size),
        ).fetchall()

        vector_candidates = [row_to_candidate(row) for row in vector_rows]
        if selected_mode == "vector":
            ordered = vector_candidates
        elif han_query:
            keyword_rows = conn.execute(
                f'''SELECT {select_columns}
                    FROM chunks c JOIN documents d ON d.id=c.document_id
                    CROSS JOIN LATERAL (
                        SELECT count(*) AS matches FROM unnest(%s::text[]) AS terms(term)
                        WHERE strpos(lower(c.content), terms.term) > 0
                    ) lexical
                    WHERE {ACCESS_SQL}{kb_where} AND lexical.matches > 0
                    ORDER BY lexical.matches DESC,c.id LIMIT %s''',
                (embedding, search_terms(question), *access_args(principal), *kb_args, pool_size),
            ).fetchall()
            ordered = reciprocal_rank_fusion(vector_candidates, [row_to_candidate(row) for row in keyword_rows])
        else:
            # websearch_to_tsquery handles ordinary phrases and punctuation
            # without requiring the caller to write tsquery syntax.
            keyword_rows = conn.execute(
                f"""WITH q AS (
                        SELECT websearch_to_tsquery('english', %s) AS tsq
                    )
                    SELECT {select_columns}
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    CROSS JOIN q
                    WHERE {ACCESS_SQL}{kb_where}
                      AND to_tsvector('english', c.content) @@ q.tsq
                    ORDER BY ts_rank_cd(to_tsvector('english', c.content), q.tsq)
                             DESC, c.id
                    LIMIT %s""",
                (question, embedding, *access_args(principal), *kb_args, pool_size),
            ).fetchall()
            keyword_candidates = [row_to_candidate(row) for row in keyword_rows]
            ordered = reciprocal_rank_fusion(vector_candidates, keyword_candidates)
        _audit(conn, principal, "search", result_count=min(top_k, len(ordered)))

    # IMPORTANT: inference runs after leaving the DB transaction/connection.
    if selected_mode == "rerank":
        ordered = _cross_encoder_rerank(question, ordered[:pool_size])

    return [
        SearchHit(
            source_number=i,
            document_id=hit.document_id,
            title=hit.title,
            chunk_index=hit.chunk_index,
            content=hit.content,
            similarity=hit.similarity,
            page_number=hit.page_number,
        )
        for i, hit in enumerate(ordered[:top_k], start=1)
    ]


def answer_question(question: str, sources: list[SearchHit], *, conversation_context: str = '') -> str:
    if not sources:
        if contains_han(question):
            # These characters are shared by Simplified and Traditional Chinese.
            return '未找到可引用的已索引文本。'
        return "No indexed sources are available to answer that question."

    context = "\n\n".join(
        f"[{hit.source_number}] {hit.title} (document {hit.document_id}, "
        f"chunk {hit.chunk_index}"
        f"{f', PDF page {hit.page_number}' if hit.page_number is not None else ''})\n{hit.content}"
        for hit in sources
    )
    args = {'conversation_context': conversation_context} if conversation_context else {}
    return generate_grounded_answer(question, context, **args)
