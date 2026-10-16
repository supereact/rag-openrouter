"""Paged library of authorized documents and unfinished upload jobs."""
from app.db import db_connection
from app.security import Principal
from app.services import ACCESS_SQL, access_args


def list_library(principal: Principal, page=1, page_size=20, q='', status=None,
                 file_type=None) -> dict:
    # Both branches authorize before filters, counts, and pagination. Completed
    # jobs are never listed, including jobs whose document has since been deleted.
    sql = f'''WITH visible AS (
        SELECT 'document' AS kind, d.id::text AS id, d.title,
               d.created_at, 'indexed' AS status, d.owner_user_id,
               NULL::text AS error
        FROM documents d WHERE {ACCESS_SQL}
        UNION ALL
        SELECT 'upload', j.id::text, j.filename, j.created_at, j.status,
               j.user_id, j.error
        FROM ingestion_jobs j WHERE j.tenant_id=%s
          AND (j.user_id=%s OR %s='admin') AND j.status <> 'completed'
    ), filtered AS (
        SELECT * FROM visible WHERE strpos(lower(title), lower(%s)) > 0
          AND (%s::text IS NULL OR status=%s)
          AND (%s::text IS NULL OR lower(title) LIKE %s)
    ) '''
    args = (*access_args(principal), principal.tenant_id, principal.user_id,
            principal.role, q.strip(), status, status, file_type,
            f'%.{file_type}' if file_type else None)
    with db_connection() as conn:
        # Count, page, and sharing summaries must use one authorization snapshot.
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        total = conn.execute(sql + 'SELECT count(*) FROM filtered', args).fetchone()[0]
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        rows = conn.execute(sql + '''SELECT kind,id,title,created_at,status,owner_user_id,error
            FROM filtered ORDER BY created_at DESC, kind, id DESC
            LIMIT %s OFFSET %s''', (*args, page_size, (page - 1) * page_size)).fetchall()
        items = []
        for kind, id_, title, created, state, owner, error in rows:
            can_manage = (principal.role in ('admin', 'editor') and
                          (principal.role == 'admin' or owner == principal.user_id))
            items.append(dict(kind=kind, id=id_, title=title, created_at=created,
                              status=state, owner_user_id=owner, error=error,
                              can_manage=can_manage, assigned_users=None))
        managed = [int(item['id']) for item in items
                   if item['kind'] == 'document' and item['can_manage']]
        if managed:
            recipients = conn.execute('''SELECT a.document_id,u.id,u.username
                FROM document_acl a JOIN app_users u
                  ON u.id=a.user_id AND u.tenant_id=a.tenant_id
                WHERE a.tenant_id=%s AND a.document_id=ANY(%s)
                ORDER BY u.username,u.id''', (principal.tenant_id, managed)).fetchall()
            by_doc = {id_: [] for id_ in managed}
            for doc, uid, username in recipients:
                by_doc[doc].append(dict(id=uid, username=username))
            for item in items:
                if item['kind'] == 'document' and item['can_manage']:
                    item['assigned_users'] = by_doc[int(item['id'])]
    return dict(items=items, total=total, page=page, page_size=page_size, pages=pages)
