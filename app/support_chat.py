"""Private support chats; only explicitly designated central staff cross tenants."""
from uuid import UUID

from fastapi import HTTPException

from app import settings
from app.db import db_connection
from app.security import Principal

CHAT_FIELDS = ('id', 'subject', 'tenant_id', 'user_id', 'username', 'status', 'created_at', 'updated_at')
CHAT_SELECT = 'c.id,c.subject,c.tenant_id,c.user_id,u.username,c.status,c.created_at,c.updated_at'
CHAT_FROM = 'FROM support_chats c JOIN app_users u ON u.id=c.user_id AND u.tenant_id=c.tenant_id'
MESSAGE_FIELDS = ('id', 'sender_user_id', 'username', 'author_kind', 'body', 'created_at')


def staff_ids() -> set[int]:
    raw = settings.RAG_SUPPORT_STAFF_USER_IDS.strip()
    if not raw:
        return set()
    try:
        parts = [part.strip() for part in raw.split(',')]
        if any(not part.isascii() or not part.isdecimal() or int(part) <= 0 for part in parts):
            raise ValueError()
        return {int(part) for part in parts}
    except ValueError as exc:
        raise HTTPException(503, 'Invalid support staff configuration') from exc


def is_staff(principal: Principal) -> bool:
    # An ordinary tenant admin never becomes global support staff automatically.
    return principal.role == 'admin' and principal.user_id in staff_ids()


def _scope(principal: Principal) -> tuple[str, tuple]:
    if is_staff(principal):
        return 'TRUE', ()
    return '(c.tenant_id=%s AND c.user_id=%s)', (principal.tenant_id, principal.user_id)


def _chat(conn, principal: Principal, chat_id: int, *, lock=False) -> dict:
    scope, args = _scope(principal)
    row = conn.execute(f'''SELECT {CHAT_SELECT} {CHAT_FROM}
        WHERE c.id=%s AND {scope}{' FOR UPDATE OF c' if lock else ''}''',
        (chat_id, *args)).fetchone()
    if row is None:
        raise HTTPException(404, 'Support chat not found')
    return dict(zip(CHAT_FIELDS, row))


def list_chats(principal: Principal, page=1, page_size=20, status='all') -> dict:
    scope, args = _scope(principal)
    if status != 'all':
        scope += ' AND c.status=%s'
        args += (status,)
    with db_connection() as conn:
        total = conn.execute(f'SELECT COUNT(*) {CHAT_FROM} WHERE {scope}', args).fetchone()[0]
        page = min(page, max(1, (total + page_size - 1) // page_size))
        rows = conn.execute(f'''SELECT {CHAT_SELECT} {CHAT_FROM} WHERE {scope}
            ORDER BY c.updated_at DESC,c.id DESC LIMIT %s OFFSET %s''',
            (*args, page_size, (page - 1) * page_size)).fetchall()
    return {'items': [dict(zip(CHAT_FIELDS, row)) for row in rows], 'total': total,
            'page': page, 'page_size': page_size, 'is_staff': is_staff(principal),
            'enabled': bool(staff_ids())}


def _message_by_key(conn, chat_id: int, request_key: UUID):
    row = conn.execute('''SELECT m.id,m.sender_user_id,u.username,m.author_kind,m.body,m.created_at
        FROM support_messages m JOIN app_users u ON u.id=m.sender_user_id
        WHERE m.chat_id=%s AND m.request_key=%s''', (chat_id, request_key)).fetchone()
    return dict(zip(MESSAGE_FIELDS, row)) if row else None


def _insert_message(conn, principal: Principal, chat: dict, body: str, request_key: UUID) -> dict:
    conn.execute('''INSERT INTO support_messages
        (chat_id,tenant_id,user_id,sender_user_id,author_kind,body,request_key)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
        (chat['id'], chat['tenant_id'], chat['user_id'], principal.user_id,
         'staff' if is_staff(principal) else 'user', body, request_key)).fetchone()
    conn.execute('UPDATE support_chats SET updated_at=now() WHERE id=%s', (chat['id'],))
    return _message_by_key(conn, chat['id'], request_key)


def create_chat(principal: Principal, subject: str, body: str, request_key: UUID) -> dict:
    if not staff_ids():
        raise HTTPException(503, 'Support is not configured yet')
    with db_connection() as conn:
        # Serialize creation/idempotency and the open-chat cap for this owner.
        owner = conn.execute('''SELECT id FROM app_users
            WHERE id=%s AND tenant_id=%s AND is_active FOR UPDATE''',
            (principal.user_id, principal.tenant_id)).fetchone()
        if owner is None:
            raise HTTPException(401, 'Account unavailable')
        previous = conn.execute('''SELECT id FROM support_chats
            WHERE tenant_id=%s AND user_id=%s AND request_key=%s''',
            (principal.tenant_id, principal.user_id, request_key)).fetchone()
        if previous:
            chat = _chat(conn, principal, previous[0])
            first = _message_by_key(conn, chat['id'], request_key)
            if chat['subject'] != subject or first is None or first['body'] != body:
                raise HTTPException(409, 'This request key was already used for another chat')
            return chat
        count = conn.execute('''SELECT COUNT(*) FROM support_chats
            WHERE tenant_id=%s AND user_id=%s AND status='open' ''',
            (principal.tenant_id, principal.user_id)).fetchone()[0]
        if count >= 5:
            raise HTTPException(429, 'You already have five open support chats. Use an existing chat.')
        chat_id = conn.execute('''INSERT INTO support_chats(tenant_id,user_id,subject,request_key)
            VALUES (%s,%s,%s,%s) RETURNING id''',
            (principal.tenant_id, principal.user_id, subject, request_key)).fetchone()[0]
        chat = _chat(conn, principal, chat_id)
        _insert_message(conn, principal, chat, body, request_key)
        return _chat(conn, principal, chat_id)


def read_messages(principal: Principal, chat_id: int, after_id=0) -> dict:
    with db_connection() as conn:
        chat = _chat(conn, principal, chat_id)
        rows = conn.execute('''SELECT m.id,m.sender_user_id,u.username,m.author_kind,m.body,m.created_at
            FROM support_messages m JOIN app_users u ON u.id=m.sender_user_id
            WHERE m.chat_id=%s AND m.id>%s ORDER BY m.id LIMIT 101''', (chat_id, after_id)).fetchall()
    return {'chat': chat, 'messages': [dict(zip(MESSAGE_FIELDS, row)) for row in rows[:100]],
            'has_more': len(rows) > 100}


def send_message(principal: Principal, chat_id: int, body: str, request_key: UUID) -> dict:
    with db_connection() as conn:
        # Lock and recheck status before inserting; closing cannot race a reply.
        chat = _chat(conn, principal, chat_id, lock=True)
        previous = _message_by_key(conn, chat_id, request_key)
        if previous:
            if previous['sender_user_id'] != principal.user_id or previous['body'] != body:
                raise HTTPException(409, 'This request key was already used for another message')
            return previous
        if chat['status'] != 'open':
            raise HTTPException(409, 'This support chat is closed')
        if not staff_ids():
            raise HTTPException(503, 'Support is not configured yet')
        return _insert_message(conn, principal, chat, body, request_key)


def set_status(principal: Principal, chat_id: int, status: str) -> dict:
    if not is_staff(principal):
        raise HTTPException(403, 'Central support staff access required')
    with db_connection() as conn:
        _chat(conn, principal, chat_id, lock=True)
        conn.execute('UPDATE support_chats SET status=%s,updated_at=now() WHERE id=%s', (status, chat_id))
        return _chat(conn, principal, chat_id)
