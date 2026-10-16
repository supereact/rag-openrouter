# Per-answer feedback: owner-only votes and tenant-only aggregate reporting.
# Do not store user questions or answers in feedback.
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException

from app.db import db_connection
from app.security import Principal
from app.conversations import _authorized_document_ids

REASONS = frozenset({'incorrect', 'incomplete', 'irrelevant', 'outdated', 'other'})


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail='Answer not found')


def _owned_message(conn, principal: Principal, conversation_id: int, message_id: int):
    # Source snapshots must remain authorized when someone rates an older answer.
    row = conn.execute('''SELECT m.sources FROM conversation_messages m
        JOIN conversations c ON c.id=m.conversation_id
        WHERE m.id=%s AND c.id=%s AND c.tenant_id=%s AND c.user_id=%s''',
        (message_id, conversation_id, principal.tenant_id, principal.user_id)).fetchone()
    if row is None:
        raise _not_found()
    sources = row[0]
    if isinstance(sources, str):
        sources = json.loads(sources)
    if not isinstance(sources, list):
        raise _not_found()
    ids = {int(src['document_id']) for src in sources
           if isinstance(src, dict) and 'document_id' in src}
    if ids - _authorized_document_ids(conn, principal, ids):
        raise _not_found()


def save_feedback(principal: Principal, conversation_id: int, message_id: int,
                  rating: str, reason: str | None = None) -> dict:
    if rating not in ('up', 'down'):
        raise ValueError('rating must be up or down')
    if reason is not None and (reason not in REASONS or rating != 'down'):
        raise ValueError('reason must be a supported downvote reason')
    score = 1 if rating == 'up' else -1
    with db_connection() as conn:
        _owned_message(conn, principal, conversation_id, message_id)
        row = conn.execute('''INSERT INTO answer_feedback
          (tenant_id,user_id,conversation_id,message_id,rating,reason)
          VALUES (%s,%s,%s,%s,%s,%s)
          ON CONFLICT (message_id) DO UPDATE SET rating=EXCLUDED.rating,
              reason=EXCLUDED.reason, updated_at=now()
          WHERE answer_feedback.tenant_id=EXCLUDED.tenant_id
            AND answer_feedback.user_id=EXCLUDED.user_id
          RETURNING rating,reason,updated_at''',
          (principal.tenant_id, principal.user_id, conversation_id,
           message_id, score, reason)).fetchone()
        if row is None:
            raise _not_found()
    return {'message_id':message_id, 'rating':'up' if row[0] == 1 else 'down',
            'reason':row[1], 'updated_at':row[2]}


def remove_feedback(principal: Principal, conversation_id: int, message_id: int) -> None:
    with db_connection() as conn:
        _owned_message(conn, principal, conversation_id, message_id)
        conn.execute('''DELETE FROM answer_feedback
            WHERE message_id=%s AND conversation_id=%s
              AND tenant_id=%s AND user_id=%s''',
            (message_id, conversation_id, principal.tenant_id, principal.user_id))


def list_feedback(principal: Principal, conversation_id: int) -> list[dict]:
    with db_connection() as conn:
        found = conn.execute('''SELECT id FROM conversations
            WHERE id=%s AND tenant_id=%s AND user_id=%s''',
            (conversation_id,principal.tenant_id,principal.user_id)).fetchone()
        if found is None:
            raise HTTPException(status_code=404, detail='Conversation not found')
        rows = conn.execute('''SELECT f.message_id,f.rating,f.reason,f.updated_at
            FROM answer_feedback f WHERE f.conversation_id=%s
              AND f.tenant_id=%s AND f.user_id=%s
            ORDER BY f.message_id''',
            (conversation_id,principal.tenant_id,principal.user_id)).fetchall()
        # Avoid returning ratings tied to now-revoked source content.
        message_rows = conn.execute('''SELECT id,sources FROM conversation_messages
            WHERE conversation_id=%s AND id = ANY(%s)''',
            (conversation_id,[int(row[0]) for row in rows])).fetchall() if rows else []
        source_ids = {}
        all_ids = set()
        for msg_id, sources in message_rows:
            if isinstance(sources,str): sources=json.loads(sources)
            ids={int(src['document_id']) for src in sources
                 if isinstance(src,dict) and 'document_id' in src} if isinstance(sources,list) else set()
            source_ids[int(msg_id)]=ids
            all_ids.update(ids)
        authorized = _authorized_document_ids(conn,principal,all_ids)
    return [{'message_id':row[0], 'rating':'up' if row[1]==1 else 'down',
             'reason':row[2], 'updated_at':row[3]}
            for row in rows if row[0] in source_ids and source_ids[row[0]] <= authorized]


def admin_quality(principal: Principal, days: int = 30) -> dict:
    if principal.role != 'admin':
        raise HTTPException(status_code=403, detail='Admin access required')
    if days not in (7, 30):
        raise ValueError('days must be 7 or 30')
    # All-time numbers and rolling UTC daily series; never disclose chat content.
    now = datetime.now(timezone.utc)
    cutoff_date = now.date() - timedelta(days=days-1)
    with db_connection() as conn:
        totals = conn.execute('''SELECT COUNT(*),
            COUNT(*) FILTER (WHERE rating=1), COUNT(*) FILTER (WHERE rating=-1)
            FROM answer_feedback WHERE tenant_id=%s''',
            (principal.tenant_id,)).fetchone()
        rows = conn.execute('''SELECT (updated_at AT TIME ZONE 'UTC')::date,
            COUNT(*) FILTER (WHERE rating=1), COUNT(*) FILTER (WHERE rating=-1)
            FROM answer_feedback WHERE tenant_id=%s AND updated_at >= %s
            GROUP BY 1 ORDER BY 1''',
            (principal.tenant_id, datetime.combine(cutoff_date,datetime.min.time(),tzinfo=timezone.utc))).fetchall()
        reasons = conn.execute('''SELECT COALESCE(reason,'unspecified'),COUNT(*)
            FROM answer_feedback WHERE tenant_id=%s AND rating=-1
              AND updated_at >= %s GROUP BY 1 ORDER BY 2 DESC,1''',
            (principal.tenant_id,datetime.combine(cutoff_date,datetime.min.time(),tzinfo=timezone.utc))).fetchall()
        recent = conn.execute('''SELECT u.username,f.reason,f.updated_at
            FROM answer_feedback f
            JOIN app_users u ON u.id=f.user_id AND u.tenant_id=f.tenant_id
            WHERE f.tenant_id=%s AND f.rating=-1
            ORDER BY f.updated_at DESC LIMIT 10''',
            (principal.tenant_id,)).fetchall()
    daily_map={d:(int(up),int(down)) for d,up,down in rows}
    daily=[{'date':(cutoff_date+timedelta(days=i)).isoformat(),
            'up':daily_map.get(cutoff_date+timedelta(days=i),(0,0))[0],
            'down':daily_map.get(cutoff_date+timedelta(days=i),(0,0))[1]}
           for i in range(days)]
    all_count,all_up,all_down=map(int,totals)
    period_up=sum(day['up'] for day in daily)
    period_down=sum(day['down'] for day in daily)
    return {'scope':'tenant', 'days':days, 'all_time':{'total':all_count,'up':all_up,'down':all_down},
            'period':{'total':period_up+period_down,'up':period_up,'down':period_down},
            'positive_rate':round(period_up/(period_up+period_down),4) if period_up+period_down else None,
            'daily':daily,
            'downvote_reasons':[{'reason':name,'count':int(count)} for name,count in reasons],
            'recent_downvotes':[{'username':username,'reason':reason,'created_at':at}
                                for username,reason,at in recent],
            'disclaimer':'User ratings are subjective signals, not verified answer correctness. Content is private.'}
