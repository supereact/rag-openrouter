"""Tenant-scoped API key authentication and authorization (local security MVP).

The API accepts a 256-bit random bearer key, stores only its SHA-256 digest,
and obtains tenant/role identity from PostgreSQL, not client-provided headers.
"""
from dataclasses import dataclass
from hashlib import sha256
import os
import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import db_connection
from app.browser_auth import COOKIE_NAME, SAFE_METHODS, require_browser_request

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: int
    tenant_id: int
    role: str
    username: str


def key_digest(key: str) -> str:
    return sha256(key.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    return "rag_" + secrets.token_urlsafe(32)


def principal_from_api_key(key: str) -> Principal | None:
    # Existing, operator-generated long-lived API keys remain supported.
    if key.startswith("rag_") and not key.startswith("rags_") and len(key) >= 40:
        with db_connection() as conn:
            row = conn.execute(
                """SELECT u.id,u.tenant_id,u.role,u.username
                   FROM api_keys k JOIN app_users u ON u.id=k.user_id
                   WHERE k.key_hash=%s AND k.revoked_at IS NULL AND u.is_active""",
                (key_digest(key),),
            ).fetchone()
        return Principal(*row) if row else None
    # Browser sessions expire and are revoked on logout, role change or deactivation.
    if key.startswith("rags_") and len(key) >= 45:
        with db_connection() as conn:
            row = conn.execute(
                """SELECT u.id,u.tenant_id,u.role,u.username
                   FROM login_sessions s JOIN app_users u ON u.id=s.user_id
                   WHERE s.token_hash=%s AND s.revoked_at IS NULL
                     AND s.expires_at>now() AND u.is_active""",
                (key_digest(key),),
            ).fetchone()
        return Principal(*row) if row else None
    return None


def require_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Principal:
    # Explicit credentials always take priority; never silently fall back to a
    # cookie when an invalid Authorization header was supplied.
    token = credentials.credentials if credentials else None
    if request.headers.get('authorization') is None:
        cookie = request.cookies.get(COOKIE_NAME, '')
        if cookie.startswith('rags_'):
            if request.method not in SAFE_METHODS:
                require_browser_request(request)
            token = cookie
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer API key required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    principal = principal_from_api_key(token)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


def require_editor(principal: Principal = Depends(require_principal)) -> Principal:
    if principal.role not in ("admin", "editor"):
        raise HTTPException(status_code=403, detail="Write permission required")
    return principal


def local_admin_principal() -> Principal:
    """For trusted local scripts only: load key from .env, never bypass auth."""
    from dotenv import load_dotenv
    load_dotenv()
    key = os.getenv("RAG_ADMIN_API_KEY", "")
    principal = principal_from_api_key(key)
    if principal is None or principal.role != "admin":
        raise RuntimeError("Configure a valid RAG_ADMIN_API_KEY in .env first")
    return principal
