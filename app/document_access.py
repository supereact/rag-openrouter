"""Owner/admin management of explicit, same-tenant document permissions."""
from app.db import db_connection
from app.security import Principal
from app.services import _audit, _ensure_can_write


def _owner(conn, principal: Principal, document_id: int, *, lock: bool = False) -> int:
    _ensure_can_write(principal)
    row = conn.execute(
        """SELECT owner_user_id FROM documents WHERE id=%s AND tenant_id=%s
           AND (owner_user_id=%s OR %s='admin')""" + (" FOR UPDATE" if lock else ""),
        (document_id, principal.tenant_id, principal.user_id, principal.role),
    ).fetchone()
    if row is None:
        raise PermissionError('Document not found or not writable')
    return int(row[0])


def _users(conn, principal: Principal, document_id: int, owner_id: int) -> dict:
    rows = conn.execute(
        """SELECT u.id,u.username,u.email,u.is_active,u.role,
                  EXISTS (SELECT 1 FROM document_acl a
                    WHERE a.document_id=%s AND a.tenant_id=u.tenant_id AND a.user_id=u.id)
           FROM app_users u WHERE u.tenant_id=%s ORDER BY lower(u.username),u.id""",
        (document_id, principal.tenant_id),
    ).fetchall()
    return {'users': [dict(
        id=uid, username=name, email=email, is_active=active, shared=shared,
        automatic_access='owner' if uid == owner_id else 'admin' if role == 'admin' else None,
    ) for uid, name, email, active, role, shared in rows]}


def get_access(principal: Principal, document_id: int) -> dict:
    _ensure_can_write(principal)
    with db_connection() as conn:
        owner_id = _owner(conn, principal, document_id)
        return _users(conn, principal, document_id, owner_id)


def update_access(principal: Principal, document_id: int,
                  grant_user_ids: list[int], revoke_user_ids: list[int]) -> dict:
    """Apply a delta so unrelated concurrent grants/removals are preserved."""
    _ensure_can_write(principal)
    grants, revokes = set(grant_user_ids), set(revoke_user_ids)
    if grants & revokes:
        raise ValueError('A user cannot be granted and revoked in the same request')
    targets = sorted(grants | revokes)
    with db_connection() as conn:
        owner_id = _owner(conn, principal, document_id, lock=True)
        if targets:
            rows = conn.execute(
                """SELECT id,role,is_active FROM app_users
                   WHERE tenant_id=%s AND id=ANY(%s) ORDER BY id FOR SHARE""",
                (principal.tenant_id, targets),
            ).fetchall()
            if {row[0] for row in rows} != set(targets):
                raise ValueError('One or more users are unavailable in your tenant')
            if any(uid == owner_id or role == 'admin' for uid, role, _ in rows):
                raise ValueError('Owner and administrator access is automatic')
            if any(uid in grants and not active for uid, _, active in rows):
                raise ValueError('Access can only be granted to active users')
        # Validate every target before changing any ACL. All writes and the
        # audit event commit together through db_connection's transaction.
        if revokes:
            conn.execute(
                """DELETE FROM document_acl
                   WHERE document_id=%s AND tenant_id=%s AND user_id=ANY(%s)""",
                (document_id, principal.tenant_id, sorted(revokes)),
            )
        if grants:
            conn.execute(
                """INSERT INTO document_acl(document_id,tenant_id,user_id)
                   SELECT %s,%s,u.id FROM app_users u
                   WHERE u.tenant_id=%s AND u.id=ANY(%s) ON CONFLICT DO NOTHING""",
                (document_id, principal.tenant_id, principal.tenant_id, sorted(grants)),
            )
        if targets:
            _audit(conn, principal, 'document.access.update', document_id, len(targets))
        return _users(conn, principal, document_id, owner_id)
