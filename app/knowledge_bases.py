"""Tenant-scoped knowledge bases; membership never grants document access.

A collection chooses a subset of documents. Every read still requires the
original document ACL, checked in SQL before embedding results reach the LLM.
"""
from fastapi import HTTPException

from app.db import db_connection
from app.security import Principal
from app.services import ACCESS_SQL, access_args


def _missing() -> HTTPException:
    return HTTPException(status_code=404, detail="Knowledge base not found")


def _require_editor(principal: Principal) -> None:
    if principal.role not in ("editor", "admin"):
        raise HTTPException(status_code=403, detail="Editor or admin access required")


def assert_tenant_collection(principal: Principal, collection_id: int) -> None:
    """Fail closed for nonexistent or foreign-tenant collections."""
    with db_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM knowledge_bases WHERE id=%s AND tenant_id=%s",
            (collection_id, principal.tenant_id),
        ).fetchone()
    if row is None:
        raise _missing()


def _editable(conn, principal: Principal, collection_id: int) -> None:
    _require_editor(principal)
    row = conn.execute(
        """SELECT 1 FROM knowledge_bases
           WHERE id=%s AND tenant_id=%s
             AND (created_by=%s OR %s='admin')""",
        (collection_id, principal.tenant_id, principal.user_id, principal.role),
    ).fetchone()
    if row is None:
        raise _missing()


def list_bases(principal: Principal) -> list[dict]:
    """Counts only documents visible to this principal."""
    with db_connection() as conn:
        rows = conn.execute(
            f"""SELECT kb.id, kb.name, kb.description, kb.created_by,
                       kb.created_at, COUNT(d.id) AS accessible_count
                FROM knowledge_bases kb
                LEFT JOIN knowledge_base_documents kbd
                  ON kbd.knowledge_base_id=kb.id AND kbd.tenant_id=kb.tenant_id
                LEFT JOIN documents d
                  ON d.id=kbd.document_id AND {ACCESS_SQL}
                WHERE kb.tenant_id=%s
                GROUP BY kb.id, kb.name, kb.description, kb.created_by, kb.created_at
                ORDER BY kb.name, kb.id""",
            (*access_args(principal), principal.tenant_id),
        ).fetchall()
    return [dict(id=r[0], name=r[1], description=r[2], created_by=r[3],
                 created_at=r[4], document_count=int(r[5]),
                 can_manage=(principal.role == 'admin' or
                             (principal.role == 'editor' and r[3] == principal.user_id)))
            for r in rows if int(r[5]) > 0 or principal.role in ('editor','admin')]


def create_base(principal: Principal, name: str, description: str = '') -> dict:
    _require_editor(principal)
    with db_connection() as conn:
        row = conn.execute(
            """INSERT INTO knowledge_bases(tenant_id,created_by,name,description)
               VALUES (%s,%s,%s,%s)
               ON CONFLICT DO NOTHING
               RETURNING id,name,description,created_by,created_at""",
            (principal.tenant_id, principal.user_id, name, description),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=409, detail="Knowledge base name already exists")
    return dict(id=row[0], name=row[1], description=row[2], created_by=row[3],
                created_at=row[4], document_count=0, can_manage=True)


def rename_base(principal: Principal, collection_id: int, name: str, description: str) -> dict:
    with db_connection() as conn:
        _editable(conn, principal, collection_id)
        found = conn.execute(
            """SELECT 1 FROM knowledge_bases WHERE tenant_id=%s
               AND lower(name)=lower(%s) AND id<>%s""",
            (principal.tenant_id, name, collection_id),
        ).fetchone()
        if found:
            raise HTTPException(status_code=409, detail="Knowledge base name already exists")
        row = conn.execute(
            """UPDATE knowledge_bases SET name=%s,description=%s
               WHERE id=%s AND tenant_id=%s
               RETURNING id,name,description,created_by,created_at""",
            (name, description, collection_id, principal.tenant_id),
        ).fetchone()
    return dict(id=row[0], name=row[1], description=row[2], created_by=row[3],
                created_at=row[4], can_manage=True)


def delete_base(principal: Principal, collection_id: int) -> None:
    """Deletes only the collection and its memberships, never documents."""
    with db_connection() as conn:
        _editable(conn, principal, collection_id)
        conn.execute("DELETE FROM knowledge_bases WHERE id=%s AND tenant_id=%s",
                     (collection_id, principal.tenant_id))


def list_base_documents(principal: Principal, collection_id: int) -> list[dict]:
    assert_tenant_collection(principal, collection_id)
    with db_connection() as conn:
        rows = conn.execute(
            f"""SELECT d.id,d.title,d.owner_user_id,d.created_at
                FROM knowledge_base_documents kbd
                JOIN documents d ON d.id=kbd.document_id
                WHERE kbd.knowledge_base_id=%s AND kbd.tenant_id=%s
                  AND {ACCESS_SQL}
                ORDER BY d.title,d.id""",
            (collection_id, principal.tenant_id, *access_args(principal)),
        ).fetchall()
    return [dict(id=r[0], title=r[1], owner_user_id=r[2], created_at=r[3])
            for r in rows]


def add_document(principal: Principal, collection_id: int, document_id: int) -> None:
    with db_connection() as conn:
        _editable(conn, principal, collection_id)
        # Only an owner or tenant admin may enroll their document. Membership
        # never changes document_acl, preventing privilege escalation.
        row = conn.execute(
            """SELECT 1 FROM documents WHERE id=%s AND tenant_id=%s
               AND (owner_user_id=%s OR %s='admin')""",
            (document_id, principal.tenant_id, principal.user_id, principal.role),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Document not found or not writable")
        conn.execute(
            """INSERT INTO knowledge_base_documents(knowledge_base_id,document_id,tenant_id)
               VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""",
            (collection_id, document_id, principal.tenant_id),
        )


def remove_document(principal: Principal, collection_id: int, document_id: int) -> None:
    with db_connection() as conn:
        _editable(conn, principal, collection_id)
        # Same document write authorization required for unlinking.
        row = conn.execute(
            """SELECT 1 FROM documents WHERE id=%s AND tenant_id=%s
               AND (owner_user_id=%s OR %s='admin')""",
            (document_id, principal.tenant_id, principal.user_id, principal.role),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Document not found or not writable")
        conn.execute(
            """DELETE FROM knowledge_base_documents
               WHERE knowledge_base_id=%s AND document_id=%s AND tenant_id=%s""",
            (collection_id, document_id, principal.tenant_id),
        )
