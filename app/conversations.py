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
                    answer: str, sources: list[SearchHit]) -> int:
    """Save one completed exchange atomically after /ask's budget settlement."""
    encoded = json.dumps([source.model_dump(mode='json') for source in sources])
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


def _authorized_document_ids(conn, principal: Principal, doc_ids: set[int]) -> set[int]:
    if not doc_ids:
        return set()
    rows = conn.execute(f'''SELECT d.id FROM documents d
        WHERE d.id = ANY(%s) AND {ACCESS_SQL}''',
        (list(doc_ids), *access_args(principal))).fetchall()
    return {int(row[0]) for row in rows}


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
            if isinstance(sources, str):
                sources = json.loads(sources)
            if not isinstance(sources, list):
                sources = []
            docs.update(int(src['document_id']) for src in sources if isinstance(src,dict) and 'document_id' in src)
            decoded.append((msg_id,question,answer,sources,created_at))
        authorized = _authorized_document_ids(conn,principal,docs)
    messages = []
    for msg_id, question, answer, sources, created_at in decoded:
        revoked = any(int(src['document_id']) not in authorized for src in sources
                      if isinstance(src,dict) and 'document_id' in src)
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
