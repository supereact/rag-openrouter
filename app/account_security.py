"""Owner-only password/session controls using the existing account schema."""
from app import account_auth
from app.db import db_connection
from app.security import Principal, key_digest
from fastapi import HTTPException

password_throttle = account_auth.LoginThrottle()


def _lock_account(conn, principal: Principal, token: str):
    # Match admin updates' tenant -> account lock order. The later audit insert
    # references the tenant, so taking this key-share lock first avoids a cycle.
    conn.execute('SELECT id FROM tenants WHERE id=%s FOR KEY SHARE', (principal.tenant_id,))
    # Login takes this same lock before checking a password/issuing a session.
    # An old-password login cannot issue a new session after password revocation.
    row = conn.execute('''SELECT password_hash FROM app_users
        WHERE id=%s AND tenant_id=%s AND is_active FOR UPDATE''',
        (principal.user_id, principal.tenant_id)).fetchone()
    if row is None:
        raise HTTPException(401, 'Account unavailable. Please sign in again.')
    if token.startswith('rags_'):
        valid = conn.execute('''SELECT id FROM login_sessions WHERE token_hash=%s
            AND user_id=%s AND revoked_at IS NULL AND expires_at>now()''',
            (key_digest(token), principal.user_id)).fetchone()
    elif token.startswith('rag_'):
        valid = conn.execute('''SELECT id FROM api_keys WHERE key_hash=%s
            AND user_id=%s AND revoked_at IS NULL''',
            (key_digest(token), principal.user_id)).fetchone()
    else:
        valid = None
    if valid is None:
        raise HTTPException(401, 'Your session or API key is no longer active.')
    return row[0]


def _audit(conn, principal: Principal, action: str):
    conn.execute('''INSERT INTO audit_events(tenant_id,user_id,action)
        VALUES (%s,%s,%s)''', (principal.tenant_id, principal.user_id, action))


def list_sessions(principal: Principal, token: str, page=1, page_size=20) -> dict:
    with db_connection() as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        account = conn.execute('''SELECT password_hash IS NOT NULL AND password_hash<>''
            FROM app_users WHERE id=%s AND tenant_id=%s AND is_active''',
            (principal.user_id, principal.tenant_id)).fetchone()
        if account is None:
            raise HTTPException(401, 'Account unavailable. Please sign in again.')
        scope = '''FROM login_sessions s JOIN app_users u ON u.id=s.user_id
            WHERE u.id=%s AND u.tenant_id=%s AND u.is_active
              AND s.revoked_at IS NULL AND s.expires_at>now()'''
        args = (principal.user_id, principal.tenant_id)
        total = conn.execute(f'SELECT COUNT(*) {scope}', args).fetchone()[0]
        page = min(page, max(1, (total + page_size - 1) // page_size))
        rows = conn.execute(f'''SELECT s.id,s.created_at,s.expires_at,s.token_hash=%s
            {scope} ORDER BY s.created_at DESC,s.id DESC LIMIT %s OFFSET %s''',
            (key_digest(token), *args, page_size, (page - 1) * page_size)).fetchall()
    return {'password_enabled': bool(account[0]), 'password_session': token.startswith('rags_'),
            'sessions': [dict(zip(('id', 'created_at', 'expires_at', 'current'), row)) for row in rows],
            'total': total, 'page': page, 'page_size': page_size}


def change_password(principal: Principal, token: str, current_password: str, new_password: str) -> dict:
    try:
        account_auth.validate_password(new_password)
    except UnicodeError as exc:
        raise HTTPException(422, 'Password contains unsupported characters.') from exc
    except ValueError as exc:
        raise HTTPException(422, 'Password must contain 12–128 characters (512 UTF-8 bytes maximum).') from exc
    throttle_key = f'password-change:{principal.tenant_id}:{principal.user_id}'
    if not password_throttle.allowed(throttle_key):
        raise HTTPException(429, 'Too many password attempts. Try again later.')
    with db_connection() as conn:
        stored = _lock_account(conn, principal, token)
        if not stored:
            raise HTTPException(409, 'Password sign-in is not configured. Ask your administrator to set an initial password.')
        if not account_auth.verify_password(current_password, stored):
            password_throttle.failure(throttle_key)
            # A wrong current password is not an expired authentication session.
            raise HTTPException(400, 'Current password is incorrect.')
        if current_password == new_password:
            raise HTTPException(400, 'Choose a password different from your current password.')
        updated = account_auth.hash_password(new_password)
        conn.execute('''UPDATE app_users SET password_hash=%s
            WHERE id=%s AND tenant_id=%s''', (updated, principal.user_id, principal.tenant_id))
        conn.execute('''UPDATE login_sessions SET revoked_at=now()
            WHERE user_id=%s AND revoked_at IS NULL''', (principal.user_id,))
        _audit(conn, principal, 'account.password.changed')
    password_throttle.success(throttle_key)
    return {'sign_in_required': token.startswith('rags_')}


def revoke_session(principal: Principal, token: str, session_id: int) -> dict:
    with db_connection() as conn:
        _lock_account(conn, principal, token)
        row = conn.execute('''UPDATE login_sessions SET revoked_at=now()
            WHERE id=%s AND user_id=%s AND revoked_at IS NULL AND expires_at>now()
            RETURNING token_hash=%s''', (session_id, principal.user_id, key_digest(token))).fetchone()
        if row is None:
            raise HTTPException(404, 'Active session not found.')
        _audit(conn, principal, 'account.session.revoked')
    return {'sign_in_required': bool(row[0]), 'revoked_count': 1}


def revoke_other_sessions(principal: Principal, token: str) -> dict:
    with db_connection() as conn:
        _lock_account(conn, principal, token)
        rows = conn.execute('''UPDATE login_sessions SET revoked_at=now()
            WHERE user_id=%s AND revoked_at IS NULL AND expires_at>now()
              AND token_hash<>%s RETURNING id''', (principal.user_id, key_digest(token))).fetchall()
        _audit(conn, principal, 'account.sessions.revoked')
    return {'sign_in_required': False, 'revoked_count': len(rows)}
