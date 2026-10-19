"""Owner-only, tenant-scoped saved chat history.

Stored answer/source snapshots are sensitive. If any source document is no
longer readable, the saved answer and its excerpts are redacted on read.
All authorization is enforced in SQL; admins cannot browse others' chats.
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import HTTPException

from app.db import db_connection
from app.security import Principal
from app.services import ACCESS_SQL, access_args
from app.schemas import SearchHit
from app.conversation_context import (
    ConversationContext, ContextTurn, MAX_TURNS, MAX_QUESTION_CHARS, MAX_ANSWER_CHARS,
)

_CONTEXT_DOCUMENTS = '_context_document_ids'


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail='Conversation not found')


def _owned(conn, principal: Principal, conversation_id: int) -> tuple:
    row = conn.execute('''SELECT id,title,created_at,updated_at
        FROM conversations WHERE id=%s AND user_id=%s AND tenant_id=%s''',
        (conversation_id, principal.user_id, principal.tenant_id)).fetchone()
    if row is None:
        raise _not_found()
    return row


def _summary(row: tuple) -> dict:
    return dict(id=row[0], title=row[1], created_at=row[2], updated_at=row[3])


def list_conversations(principal: Principal) -> list[dict]:
    with db_connection() as conn:
        rows = conn.execute('''SELECT id,title,created_at,updated_at
            FROM conversations WHERE tenant_id=%s AND user_id=%s
            ORDER BY updated_at DESC,id DESC LIMIT 100''',
            (principal.tenant_id,principal.user_id)).fetchall()
    return [_summary(row) for row in rows]


def create_conversation(principal: Principal, title: str) -> dict:
    title = title.strip()
    if not 1 <= len(title) <= 120:
        raise ValueError('Title must contain 1–120 characters')
    with db_connection() as conn:
        row = conn.execute('''INSERT INTO conversations (tenant_id,user_id,title)
            VALUES (%s,%s,%s) RETURNING id,title,created_at,updated_at''',
            (principal.tenant_id,principal.user_id,title)).fetchone()
    return _summary(row)


def assert_owned(principal: Principal, conversation_id: int) -> None:
    with db_connection() as conn:
        _owned(conn,principal,conversation_id)


def rename_conversation(principal: Principal, conversation_id: int, title: str) -> dict:
    title = title.strip()
    if not 1 <= len(title) <= 120:
        raise ValueError('Title must contain 1–120 characters')
    with db_connection() as conn:
        result = conn.execute('''UPDATE conversations SET title=%s,updated_at=now()
          WHERE id=%s AND user_id=%s AND tenant_id=%s
          RETURNING id,title,created_at,updated_at''',
          (title,conversation_id,principal.user_id,principal.tenant_id)).fetchone()
        if result is None:
            raise _not_found()
    return _summary(result)


def delete_conversation(principal: Principal, conversation_id: int) -> None:
    with db_connection() as conn:
        row = conn.execute('''DELETE FROM conversations
            WHERE id=%s AND tenant_id=%s AND user_id=%s RETURNING id''',
            (conversation_id,principal.tenant_id,principal.user_id)).fetchone()
        if row is None:
            raise _not_found()


def append_exchange(principal: Principal, conversation_id: int, question: str,
                    answer: str, sources: list[SearchHit], *,
                    context_document_ids: set[int] | None = None) -> int:
    """Save one completed exchange atomically after /ask's budget settlement."""
    snapshots = [source.model_dump(mode='json') for source in sources]
    if snapshots and context_document_ids:
        # Internal JSON metadata keeps transitive context dependencies without
        # adding a table/column or exposing old excerpts as fresh citations.
        snapshots[0][_CONTEXT_DOCUMENTS] = sorted(context_document_ids)
    encoded = json.dumps(snapshots)
    with db_connection() as conn:
        # FOR UPDATE serializes concurrent writes on the same conversation.
        row = conn.execute('''SELECT id FROM conversations
            WHERE id=%s AND user_id=%s AND tenant_id=%s FOR UPDATE''',
            (conversation_id,principal.user_id,principal.tenant_id)).fetchone()
        if row is None:
            raise _not_found()
        msg_id = conn.execute('''INSERT INTO conversation_messages
            (conversation_id,question,answer,sources)
            VALUES (%s,%s,%s,%s::jsonb) RETURNING id''',
            (conversation_id,question,answer,encoded)).fetchone()[0]
        conn.execute('UPDATE conversations SET updated_at=now() WHERE id=%s', (conversation_id,))
    return int(msg_id)


def _authorized_document_ids(conn, principal: Principal, doc_ids: set[int],
                             knowledge_base_id: int | None = None) -> set[int]:
    if not doc_ids:
        return set()
    scope = (''' AND EXISTS (SELECT 1 FROM knowledge_base_documents kbd
        WHERE kbd.document_id=d.id AND kbd.tenant_id=d.tenant_id
          AND kbd.knowledge_base_id=%s)''') if knowledge_base_id is not None else ''
    args = (knowledge_base_id,) if knowledge_base_id is not None else ()
    rows = conn.execute(f'''SELECT d.id FROM documents d
        WHERE d.id = ANY(%s) AND {ACCESS_SQL}{scope}''',
        (list(doc_ids), *access_args(principal), *args)).fetchall()
    return {int(row[0]) for row in rows}


def _decode_sources(raw) -> tuple[list[dict], set[int], bool]:
    """Read legacy snapshots plus private context provenance; fail closed."""
    try:
        raw = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(raw, list):
            raise ValueError('Invalid source snapshots')
        sources, documents = [], set()
        for source in raw:
            if not isinstance(source, dict):
                raise ValueError('Invalid source snapshot')
            dependencies = source.get(_CONTEXT_DOCUMENTS, [])
            if not isinstance(dependencies, list):
                raise ValueError('Invalid context dependencies')
            for doc_id in [source.get('document_id'), *dependencies]:
                if type(doc_id) is not int or doc_id <= 0:
                    raise ValueError('Invalid document identity')
                documents.add(doc_id)
            sources.append({key: value for key, value in source.items() if key != _CONTEXT_DOCUMENTS})
        return sources, documents, True
    except (ValueError, TypeError, RecursionError):
        return [], set(), False


def load_context(principal: Principal, conversation_id: int,
                 knowledge_base_id: int | None = None) -> ConversationContext:
    """Read recent owner-only turns and recheck all source/dependency ACLs.

    A revoked or out-of-scope turn is a boundary: older context is also omitted
    so follow-ups cannot accidentally refer to an earlier, different topic.
    """
    with db_connection() as conn:
        _owned(conn, principal, conversation_id)
        rows = conn.execute('''SELECT question,answer,sources
            FROM conversation_messages WHERE conversation_id=%s
            ORDER BY id DESC LIMIT %s''', (conversation_id, MAX_TURNS)).fetchall()
        decoded = [(question, answer, *_decode_sources(sources))
                   for question, answer, sources in rows]
        documents = {doc for _, _, _, ids, _ in decoded for doc in ids}
        allowed = _authorized_document_ids(conn, principal, documents, knowledge_base_id)
    turns = []
    for question, answer, sources, ids, valid in decoded:
        if not valid or not sources or not ids <= allowed:
            break
        turns.append(ContextTurn(question[:MAX_QUESTION_CHARS], answer[:MAX_ANSWER_CHARS],
                                 frozenset(ids)))
    return ConversationContext(tuple(reversed(turns)))


def get_conversation(principal: Principal, conversation_id: int) -> dict:
    with db_connection() as conn:
        details = _owned(conn,principal,conversation_id)
        # Return most recent 100 exchanges, in chronological order.
        rows = conn.execute('''SELECT id,question,answer,sources,created_at
            FROM (SELECT id,question,answer,sources,created_at
                  FROM conversation_messages WHERE conversation_id=%s
                  ORDER BY id DESC LIMIT 100) latest ORDER BY id''',
            (conversation_id,)).fetchall()
        docs: set[int] = set()
        decoded = []
        for msg_id, question, answer, sources, created_at in rows:
            sources, dependencies, valid = _decode_sources(sources)
            docs.update(dependencies)
            decoded.append((msg_id,question,answer,sources,created_at,dependencies,valid))
        authorized = _authorized_document_ids(conn,principal,docs)
    messages = []
    for msg_id, question, answer, sources, created_at, dependencies, valid in decoded:
        revoked = not valid or not dependencies <= authorized
        messages.append(dict(
            id=msg_id,
            question=question,
            answer=('This saved answer is unavailable because access to a source document has changed.'
                    if revoked else answer),
            sources=[] if revoked else sources,
            redacted=revoked,
            created_at=created_at,
        ))
    return {**_summary(details), 'messages': messages}
