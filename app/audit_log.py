"""Read-only tenant audit history. Never include request text or credentials."""
from datetime import date, datetime, time, timezone

from app.account_auth import admin_required
from app.db import db_connection
from app.security import Principal


def list_events(principal: Principal, page: int = 1, page_size: int = 20,
                action: str = '', user_id: int | None = None,
                date_from: date | None = None, date_to: date | None = None) -> dict:
    admin_required(principal)
    if date_from and date_to and date_from > date_to:
        raise ValueError('Start date must be on or before end date')
    where = ['a.tenant_id=%s']
    args: list = [principal.tenant_id]
    if action:
        where.append('a.action=%s')
        args.append(action)
    if user_id is not None:
        where.append('a.user_id=%s')
        args.append(user_id)
    if date_from:
        where.append('a.created_at >= %s')
        args.append(datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        where.append('a.created_at <= %s')
        args.append(datetime.combine(date_to, time.max, tzinfo=timezone.utc))
    base = '''FROM audit_events a JOIN app_users u
        ON u.id=a.user_id AND u.tenant_id=a.tenant_id
        LEFT JOIN documents d ON d.id=a.document_id AND d.tenant_id=a.tenant_id
        WHERE ''' + ' AND '.join(where)
    with db_connection() as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        total = conn.execute('SELECT count(*) ' + base, args).fetchone()[0]
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        rows = conn.execute('''SELECT a.id,a.created_at,a.user_id,u.username,
            a.action,a.document_id,d.title,a.result_count ''' + base + '''
            ORDER BY a.created_at DESC,a.id DESC LIMIT %s OFFSET %s''',
            (*args, page_size, (page - 1) * page_size)).fetchall()
        actions = conn.execute('''SELECT DISTINCT a.action FROM audit_events a
            JOIN app_users u ON u.id=a.user_id AND u.tenant_id=a.tenant_id
            WHERE a.tenant_id=%s ORDER BY a.action''', (principal.tenant_id,)).fetchall()
        users = conn.execute('''SELECT DISTINCT u.id,u.username FROM app_users u
            JOIN audit_events a ON a.user_id=u.id AND a.tenant_id=u.tenant_id
            WHERE a.tenant_id=%s ORDER BY u.username,u.id''', (principal.tenant_id,)).fetchall()
    return dict(items=[dict(zip(('id', 'created_at', 'user_id', 'username', 'action',
                                 'document_id', 'document_title', 'result_count'), row)) for row in rows],
                page=page, page_size=page_size, total=total, pages=pages,
                actions=[row[0] for row in actions],
                users=[dict(id=row[0], username=row[1]) for row in users])
