"""Invitation-only password accounts and admin management (local development MVP).

No public tenant joining: an administrator must issue an email-bound invitation.
Session bearer tokens and invitation codes are stored as SHA-256 digests;
password hashes use PBKDF2-HMAC-SHA256 with a random salt.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time

import psycopg
from fastapi import HTTPException

from app.db import db_connection
from app.security import Principal, key_digest

PASSWORD_ITERATIONS = 600_000
SESSION_HOURS = 12
INVITE_HOURS = 48
EMAIL_REGEX = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
USERNAME_REGEX = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{1,79}$')


def normalize_email(raw: str) -> str:
    result = raw.strip().casefold()
    if len(result) > 254 or not EMAIL_REGEX.fullmatch(result):
        raise ValueError('Enter a valid email address')
    return result


def validate_password(password: str) -> None:
    if not 12 <= len(password) <= 128 or len(password.encode('utf-8')) > 512:
        raise ValueError('Password must contain 12–128 characters (512 UTF-8 bytes maximum)')


def hash_password(password: str) -> str:
    validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PASSWORD_ITERATIONS)
    return f'pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}'


def verify_password(password: str, encoded: str | None) -> bool:
    try:
        if not encoded:
            raise ValueError('No password')
        algorithm, rounds, salt_hex, digest_hex = encoded.split('$', 3)
        if algorithm != 'pbkdf2_sha256' or not 100_000 <= int(rounds) <= 2_000_000:
            raise ValueError('Unsupported hash')
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(actual, expected)
    except (ValueError, OverflowError, TypeError, UnicodeError):
        # Equalize timing for nonexistent and legacy API-key-only accounts.
        hashlib.pbkdf2_hmac('sha256', b'not-a-real-password', b'0' * 16, PASSWORD_ITERATIONS)
        return False


class LoginThrottle:
    """In-process best-effort throttle; replace with shared limiter before public deployment."""
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failed: dict[str, tuple[int, float]] = {}

    def allowed(self, identifier: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._failed) > 5000:
                self._failed = {k: v for k, v in self._failed.items() if v[1] > now}
            count, expiry = self._failed.get(identifier, (0, now + 900))
            if expiry < now:
                self._failed.pop(identifier, None)
                return True
            return count < 8

    def failure(self, identifier: str) -> None:
        now = time.monotonic()
        with self._lock:
            count, expiry = self._failed.get(identifier, (0, now + 900))
            if expiry < now:
                count, expiry = 0, now + 900
            if identifier not in self._failed and len(self._failed) >= 5000:
                self._failed.pop(next(iter(self._failed)))
            self._failed[identifier] = (count + 1, expiry)

    def success(self, identifier: str) -> None:
        with self._lock:
            self._failed.pop(identifier, None)


login_throttle = LoginThrottle()


def _session(conn, user_id: int) -> dict:
    token = 'rags_' + secrets.token_urlsafe(40)
    conn.execute('''INSERT INTO login_sessions(user_id,token_hash,expires_at)
                    VALUES (%s,%s,now() + (%s * interval '1 hour'))''',
                 (user_id, key_digest(token), SESSION_HOURS))
    return {'access_token': token, 'token_type': 'bearer', 'expires_in': SESSION_HOURS * 3600}


def login(email: str, password: str, client_ip: str) -> dict:
    # Normalize early, but do not disclose whether an email exists.
    try:
        normalized = normalize_email(email)
    except ValueError:
        normalized = email.strip().casefold()[:254]
    throttle_key = f'{client_ip}:{normalized}'
    if not login_throttle.allowed(throttle_key):
        raise HTTPException(status_code=429, detail='Too many attempts. Try again later.')
    with db_connection() as conn:
        row = conn.execute('''SELECT id,password_hash,is_active FROM app_users
                              WHERE lower(email)=%s''', (normalized,)).fetchone()
        correct = verify_password(password, row[1] if row else None)
        if row is None or not correct or not row[2]:
            login_throttle.failure(throttle_key)
            raise HTTPException(status_code=401, detail='Invalid email or password')
        token = _session(conn, int(row[0]))
    login_throttle.success(throttle_key)
    return token


def register(code: str, email: str, username: str, password: str) -> dict:
    normalized = normalize_email(email)
    if not USERNAME_REGEX.fullmatch(username):
        raise ValueError('Username must be 2–80 letters, numbers, dots, hyphens or underscores')
    if not code.startswith('invite_') or len(code) < 35:
        raise ValueError('Invalid or expired invitation')
    validate_password(password)
    with db_connection() as conn:
        invite = conn.execute('''SELECT id,tenant_id,email,role FROM signup_invitations
            WHERE code_hash=%s AND used_at IS NULL AND expires_at>now() FOR UPDATE''',
            (key_digest(code),)).fetchone()
        if invite is None or invite[2] != normalized:
            raise ValueError('Invalid or expired invitation')
        pw_hash = hash_password(password)
        try:
            user_id = conn.execute('''INSERT INTO app_users
                (tenant_id,username,role,email,password_hash)
                VALUES (%s,%s,%s,%s,%s) RETURNING id''',
                (invite[1], username, invite[3], normalized, pw_hash)).fetchone()[0]
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError('Email or username is already registered') from exc
        conn.execute('UPDATE signup_invitations SET used_at=now() WHERE id=%s', (invite[0],))
        return _session(conn, int(user_id))


def logout(token: str) -> None:
    # Legacy API keys intentionally remain valid: signout only clears browser state.
    if not token.startswith('rags_'):
        return
    with db_connection() as conn:
        conn.execute('''UPDATE login_sessions SET revoked_at=now()
                        WHERE token_hash=%s AND revoked_at IS NULL''', (key_digest(token),))


def admin_required(principal: Principal) -> None:
    if principal.role != 'admin':
        raise HTTPException(status_code=403, detail='Admin access required')


def invitation(principal: Principal, email: str, role: str) -> dict:
    admin_required(principal)
    normalized = normalize_email(email)
    if role not in ('reader', 'editor'):
        raise ValueError('Invitations can only grant reader or editor roles')
    code = 'invite_' + secrets.token_urlsafe(36)
    with db_connection() as conn:
        # Confirm the same email is not already associated with an account.
        if conn.execute('SELECT 1 FROM app_users WHERE lower(email)=%s', (normalized,)).fetchone():
            raise ValueError('An account already exists for that email')
        row = conn.execute('''INSERT INTO signup_invitations
            (tenant_id,invited_by,email,role,code_hash,expires_at)
            VALUES (%s,%s,%s,%s,%s,now()+(%s*interval '1 hour')) RETURNING id''',
            (principal.tenant_id, principal.user_id, normalized, role,
             key_digest(code), INVITE_HOURS)).fetchone()
    return {'invitation_id': row[0], 'invitation_code': code, 'email': normalized,
            'role': role, 'expires_in_hours': INVITE_HOURS}


def list_invitations(principal: Principal) -> list[dict]:
    admin_required(principal)
    with db_connection() as conn:
        rows = conn.execute('''SELECT id,email,role,created_at,expires_at,used_at
           FROM signup_invitations WHERE tenant_id=%s ORDER BY created_at DESC LIMIT 100''',
           (principal.tenant_id,)).fetchall()
    return [dict(zip(('id','email','role','created_at','expires_at','used_at'), row)) for row in rows]


def list_users(principal: Principal) -> list[dict]:
    admin_required(principal)
    with db_connection() as conn:
        rows = conn.execute('''SELECT id,username,email,role,is_active,created_at
            FROM app_users WHERE tenant_id=%s ORDER BY id''', (principal.tenant_id,)).fetchall()
    return [dict(zip(('id','username','email','role','is_active','created_at'), row)) for row in rows]


def update_user(principal: Principal, user_id: int, role: str | None, is_active: bool | None) -> dict:
    admin_required(principal)
    if role is not None and role not in ('admin','editor','reader'):
        raise ValueError('Invalid role')
    if role is None and is_active is None:
        raise ValueError('Specify role or is_active')
    if user_id == principal.user_id:
        raise ValueError('Cannot change your own role or active status')
    with db_connection() as conn:
        # Lock tenant row so concurrently demoting admins cannot remove last admin.
        conn.execute('SELECT id FROM tenants WHERE id=%s FOR UPDATE', (principal.tenant_id,))
        row = conn.execute('''SELECT username,email,role,is_active FROM app_users
            WHERE id=%s AND tenant_id=%s FOR UPDATE''',
            (user_id, principal.tenant_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail='User not found')
        new_role = role if role is not None else row[2]
        active = is_active if is_active is not None else row[3]
        if row[2] == 'admin' and row[3] and (new_role != 'admin' or not active):
            count = conn.execute('''SELECT COUNT(*) FROM app_users WHERE tenant_id=%s
                                   AND role='admin' AND is_active''', (principal.tenant_id,)).fetchone()[0]
            if count <= 1:
                raise ValueError('Cannot remove the last active administrator')
        conn.execute('''UPDATE app_users SET role=%s,is_active=%s
                        WHERE id=%s AND tenant_id=%s''',
                     (new_role, active, user_id, principal.tenant_id))
        # Session permissions do not persist after role/active changes.
        conn.execute('''UPDATE login_sessions SET revoked_at=now()
                        WHERE user_id=%s AND revoked_at IS NULL''', (user_id,))
        conn.execute('''INSERT INTO audit_events(tenant_id,user_id,action)
                        VALUES (%s,%s,%s)''',
                     (principal.tenant_id, principal.user_id, 'admin_user_updated'))
    return {'id': user_id, 'username': row[0], 'email': row[1],
            'role': new_role, 'is_active': active}


def revoke_sessions(principal: Principal, user_id: int) -> None:
    admin_required(principal)
    with db_connection() as conn:
        row = conn.execute('SELECT id FROM app_users WHERE id=%s AND tenant_id=%s',
                           (user_id,principal.tenant_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail='User not found')
        conn.execute('''UPDATE login_sessions SET revoked_at=now()
                        WHERE user_id=%s AND revoked_at IS NULL''', (user_id,))


def dashboard(principal: Principal) -> dict:
    admin_required(principal)
    with db_connection() as conn:
        users = conn.execute('''SELECT COUNT(*), COUNT(*) FILTER (WHERE is_active)
           FROM app_users WHERE tenant_id=%s''', (principal.tenant_id,)).fetchone()
        docs = conn.execute('SELECT COUNT(*) FROM documents WHERE tenant_id=%s',
                            (principal.tenant_id,)).fetchone()[0]
        jobs = conn.execute('''SELECT status,COUNT(*) FROM ingestion_jobs
           WHERE tenant_id=%s GROUP BY status''', (principal.tenant_id,)).fetchall()
        audit = conn.execute('''SELECT a.action, u.username, a.created_at FROM audit_events a
           JOIN app_users u ON a.user_id=u.id
           WHERE a.tenant_id=%s ORDER BY a.created_at DESC LIMIT 10''',
           (principal.tenant_id,)).fetchall()
    return {'users_total': int(users[0]), 'users_active': int(users[1]),
            'documents_total': int(docs),
            'jobs': {status: int(count) for status, count in jobs},
            'recent_actions': [{'action': row[0], 'username': row[1], 'created_at': row[2]}
                               for row in audit]}
