"""Durable per-user OpenRouter usage ledger (no prompts or document contents).

This is *application-observed* usage, not an OpenRouter account balance.
Costs are recorded only when the provider explicitly returns them; unknown
costs remain NULL rather than being inferred or treated as zero-priced calls.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.db import db_connection
from app.security import Principal


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _reported_cost(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite() or result < 0 or result >= Decimal('1000000000000'):
        return None
    return result


def record_openrouter_usage(principal: Principal, model: str, usage: dict[str, Any] | None) -> bool:
    """Write one observed provider response; no record for missing usage.

    The caller runs this only for OpenRouter. This function does not read or
    store question text, retrieved chunks, raw responses, or session tokens.
    """
    if not usage:
        return False
    input_tokens = _nonnegative_int(usage.get('prompt_tokens'))
    output_tokens = _nonnegative_int(usage.get('completion_tokens'))
    cost = _reported_cost(usage.get('provider_cost_credits'))
    if input_tokens is None and output_tokens is None and cost is None:
        return False
    with db_connection() as conn:
        conn.execute(
            '''INSERT INTO openrouter_usage_events
               (id, tenant_id, user_id, model, prompt_tokens, completion_tokens, cost_credits)
               VALUES (%s, %s, %s, %s, %s, %s, %s)''',
            (uuid4(), principal.tenant_id, principal.user_id, model[:200],
             input_tokens, output_tokens, cost),
        )
    return True


def _amount(value: object) -> str:
    """Decimal-as-string avoids JSON float rounding of tiny credit amounts."""
    return format(Decimal(str(value if value is not None else 0)), 'f')


def get_usage_dashboard(principal: Principal, days: int = 30) -> dict:
    """Return all-time, calendar-week and daily usage, isolated to one tenant.

    Current week begins Monday 00:00 UTC. The chart includes today's partial
    UTC day and zero-fills days without events. Only OpenRouter requests count.
    """
    if principal.role != 'admin':
        raise HTTPException(status_code=403, detail='Admin access required')
    if days not in (7, 30):
        raise ValueError('days must be 7 or 30')

    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    week_start = datetime.combine(monday, datetime.min.time(), tzinfo=timezone.utc)
    chart_start = today - timedelta(days=days - 1)

    with db_connection() as conn:
        summary = conn.execute('''
            SELECT COALESCE(SUM(cost_credits),0),
                   COALESCE(SUM(cost_credits) FILTER (WHERE created_at >= %s),0),
                   COUNT(*), COUNT(cost_credits),
                   COUNT(*) FILTER (WHERE created_at >= %s),
                   COUNT(cost_credits) FILTER (WHERE created_at >= %s)
            FROM openrouter_usage_events
            WHERE tenant_id = %s
        ''', (week_start, week_start, week_start, principal.tenant_id)).fetchone()
        user_rows = conn.execute('''
            SELECT u.id, u.username, u.email, u.is_active,
                   COALESCE(SUM(e.cost_credits),0),
                   COALESCE(SUM(e.cost_credits) FILTER (WHERE e.created_at >= %s),0),
                   COUNT(e.id), COUNT(e.cost_credits),
                   COUNT(e.id) FILTER (WHERE e.created_at >= %s),
                   COUNT(e.cost_credits) FILTER (WHERE e.created_at >= %s)
            FROM app_users u
            LEFT JOIN openrouter_usage_events e
              ON e.user_id=u.id AND e.tenant_id=u.tenant_id
            WHERE u.tenant_id=%s
            GROUP BY u.id, u.username, u.email, u.is_active
            ORDER BY COALESCE(SUM(e.cost_credits),0) DESC, u.username
        ''', (week_start, week_start, week_start, principal.tenant_id)).fetchall()
        daily_rows = conn.execute('''
            SELECT (created_at AT TIME ZONE 'UTC')::date AS utc_day,
                   COALESCE(SUM(cost_credits),0), COUNT(*), COUNT(cost_credits)
            FROM openrouter_usage_events
            WHERE tenant_id=%s AND created_at >= %s
            GROUP BY utc_day
            ORDER BY utc_day
        ''', (principal.tenant_id, datetime.combine(chart_start, datetime.min.time(), tzinfo=timezone.utc))).fetchall()

    daily_map = {r[0].isoformat(): r for r in daily_rows}
    daily = []
    for offset in range(days):
        date_str = (chart_start + timedelta(days=offset)).isoformat()
        row = daily_map.get(date_str)
        daily.append({
            'date': date_str,
            'credits': _amount(row[1]) if row else '0',
            'requests': int(row[2]) if row else 0,
            'cost_reported_requests': int(row[3]) if row else 0,
        })

    users = [
        {
            'user_id': int(r[0]), 'username': r[1], 'email': r[2], 'is_active': r[3],
            'overall_credits': _amount(r[4]), 'week_credits': _amount(r[5]),
            'requests': int(r[6]), 'cost_reported_requests': int(r[7]),
            'week_requests': int(r[8]), 'week_cost_reported_requests': int(r[9]),
        }
        for r in user_rows
    ]
    return {
        'scope': 'tenant',
        'provider': 'openrouter',
        'cost_unit': 'provider_reported_credits',
        'history_since': 'usage ledger migration (not historical OpenRouter account usage)',
        'week_starts_utc': monday.isoformat(),
        'chart_days': days,
        'overall_credits': _amount(summary[0]),
        'week_credits': _amount(summary[1]),
        'requests': int(summary[2]),
        'cost_reported_requests': int(summary[3]),
        'week_requests': int(summary[4]),
        'week_cost_reported_requests': int(summary[5]),
        'daily': daily,
        'users': users,
    }
