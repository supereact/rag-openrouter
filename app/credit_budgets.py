"""Tenant/user monthly OpenRouter guardrails, with transactional reservations.

An upfront reservation makes concurrent requests count toward a limit. Provider
charges above the reservation can still exceed the configured cap; this is a
soft budget guardrail rather than a hard provider-enforced spending limit.
Unknown charges retain the reservation until reviewed, never treated as free.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from fastapi import HTTPException

from app.db import db_connection
from app.security import Principal
from app.usage_ledger import _nonnegative_int, _reported_cost

DEFAULT_RESERVE = Decimal('0.01')
MAX_CREDITS = Decimal('1000000')


def month_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def parse_credits(value: str | Decimal | None, *, positive: bool = False) -> Decimal | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except (ValueError, InvalidOperation, TypeError) as exc:
        raise ValueError('Invalid credit amount') from exc
    if not amount.is_finite() or amount < 0 or amount > MAX_CREDITS or (positive and amount == 0):
        raise ValueError('Credit amount must be finite and within the permitted range')
    if amount.as_tuple().exponent < -12:
        raise ValueError('At most 12 decimal places supported')
    return amount


def _display(amount: Decimal | None) -> str | None:
    return format(amount, 'f') if amount is not None else None


def _lock_tenant(conn, tenant_id: int):
    # All reservations and policy changes for a tenant acquire this transaction
    # lock, serializing balance reads and writes across API worker processes.
    conn.execute('SELECT pg_advisory_xact_lock(%s)', (tenant_id,))


def _budget_rows(conn, principal: Principal):
    tenant = conn.execute('''
        SELECT monthly_limit_credits, paused, reservation_credits
        FROM tenant_credit_budgets WHERE tenant_id=%s
    ''', (principal.tenant_id,)).fetchone()
    user = conn.execute('''
        SELECT monthly_limit_credits, paused
        FROM user_credit_budgets WHERE tenant_id=%s AND user_id=%s
    ''', (principal.tenant_id, principal.user_id)).fetchone()
    return tenant, user


def _totals(conn, principal: Principal, start: datetime) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    # One SQL statement, scoped to the authenticated tenant. Unknown-cost
    # requests hold their reservation, even if a provider supplied no usage.
    row = conn.execute('''
        SELECT
          COALESCE((SELECT SUM(cost_credits) FROM openrouter_usage_events
              WHERE tenant_id=%s AND created_at >= %s),0),
          COALESCE((SELECT SUM(cost_credits) FROM openrouter_usage_events
              WHERE tenant_id=%s AND user_id=%s AND created_at >= %s),0),
          COALESCE((SELECT SUM(reserved_credits) FROM credit_reservations
              WHERE tenant_id=%s AND created_at >= %s AND status IN ('reserved','unknown')),0),
          COALESCE((SELECT SUM(reserved_credits) FROM credit_reservations
              WHERE tenant_id=%s AND user_id=%s AND created_at >= %s AND status IN ('reserved','unknown')),0)
    ''', (principal.tenant_id, start, principal.tenant_id, principal.user_id, start,
          principal.tenant_id, start, principal.tenant_id, principal.user_id, start)).fetchone()
    return tuple(Decimal(str(value)) for value in row)


def reserve_request(principal: Principal) -> UUID | None:
    """Atomically reserve allowance BEFORE contacting OpenRouter.

    Returns None if no active policy exists, preserving the original usage
    ledger path. Storage failure fails closed rather than bypassing budgets.
    """
    with db_connection() as conn:
        _lock_tenant(conn, principal.tenant_id)
        tenant, user = _budget_rows(conn, principal)
        if tenant and tenant[1] or user and user[1]:
            raise HTTPException(status_code=429, detail='OpenRouter generation paused by administrator')
        limit_t = Decimal(str(tenant[0])) if tenant and tenant[0] is not None else None
        limit_u = Decimal(str(user[0])) if user and user[0] is not None else None
        if limit_t is None and limit_u is None:
            return None
        reserve = Decimal(str(tenant[2])) if tenant else DEFAULT_RESERVE
        spent_t, spent_u, held_t, held_u = _totals(conn, principal, month_start_utc())
        if (limit_t is not None and spent_t + held_t + reserve > limit_t or
                limit_u is not None and spent_u + held_u + reserve > limit_u):
            raise HTTPException(status_code=429, detail='OpenRouter monthly credit budget reached')
        rid = uuid4()
        conn.execute('''INSERT INTO credit_reservations
            (id, tenant_id, user_id, reserved_credits, status)
            VALUES (%s,%s,%s,%s,'reserved')''',
            (rid, principal.tenant_id, principal.user_id, reserve))
        return rid


def release_before_generation(reservation_id: UUID, principal: Principal) -> None:
    """Release the hold only when the LLM was definitely not called."""
    with db_connection() as conn:
        conn.execute("""UPDATE credit_reservations SET status='released', finalized_at=now()
            WHERE id=%s AND tenant_id=%s AND user_id=%s AND status='reserved'""",
            (reservation_id, principal.tenant_id, principal.user_id))


def settle_request(reservation_id: UUID, principal: Principal, model: str,
                   usage: dict | None) -> str:
    """Settle provider-reported cost and ledger row in the SAME DB transaction.

    Missing cost (including missing usage) retains the reservation as 'unknown'.
    A retry of settlement never posts duplicate usage.
    """
    cost = _reported_cost(usage.get('provider_cost_credits')) if usage else None
    prompt = _nonnegative_int(usage.get('prompt_tokens')) if usage else None
    completion = _nonnegative_int(usage.get('completion_tokens')) if usage else None
    with db_connection() as conn:
        row = conn.execute('''SELECT status FROM credit_reservations
            WHERE id=%s AND tenant_id=%s AND user_id=%s FOR UPDATE''',
            (reservation_id, principal.tenant_id, principal.user_id)).fetchone()
        if row is None:
            raise RuntimeError('Reservation not found for user')
        if row[0] != 'reserved':
            return row[0]
        if usage and (prompt is not None or completion is not None or cost is not None):
            conn.execute('''INSERT INTO openrouter_usage_events
                (id,tenant_id,user_id,model,prompt_tokens,completion_tokens,cost_credits)
                VALUES (%s,%s,%s,%s,%s,%s,%s)''',
                (uuid4(), principal.tenant_id, principal.user_id, model[:200], prompt, completion, cost))
        state = 'settled' if cost is not None else 'unknown'
        conn.execute('''UPDATE credit_reservations SET status=%s, actual_cost_credits=%s,
            finalized_at=now() WHERE id=%s''', (state, cost, reservation_id))
        return state


def _admin(principal: Principal) -> None:
    if principal.role != 'admin':
        raise HTTPException(status_code=403, detail='Admin access required')


def update_tenant_budget(principal: Principal, limit: str | None, paused: bool,
                         reserve: str) -> None:
    _admin(principal)
    cap = parse_credits(limit)
    hold = parse_credits(reserve, positive=True)
    with db_connection() as conn:
        _lock_tenant(conn, principal.tenant_id)
        conn.execute('''INSERT INTO tenant_credit_budgets
              (tenant_id, monthly_limit_credits, paused, reservation_credits)
              VALUES (%s,%s,%s,%s)
              ON CONFLICT (tenant_id) DO UPDATE SET monthly_limit_credits=EXCLUDED.monthly_limit_credits,
                paused=EXCLUDED.paused, reservation_credits=EXCLUDED.reservation_credits''',
              (principal.tenant_id, cap, paused, hold))


def update_user_budget(principal: Principal, user_id: int, limit: str | None, paused: bool) -> None:
    _admin(principal)
    cap = parse_credits(limit)
    with db_connection() as conn:
        _lock_tenant(conn, principal.tenant_id)
        existing = conn.execute('''SELECT 1 FROM app_users WHERE id=%s AND tenant_id=%s''',
                                (user_id, principal.tenant_id)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail='User not found')
        conn.execute('''INSERT INTO user_credit_budgets
              (tenant_id,user_id,monthly_limit_credits,paused)
              VALUES (%s,%s,%s,%s)
              ON CONFLICT (tenant_id,user_id) DO UPDATE SET
                monthly_limit_credits=EXCLUDED.monthly_limit_credits,
                paused=EXCLUDED.paused''', (principal.tenant_id, user_id, cap, paused))


def get_budget_dashboard(principal: Principal) -> dict:
    _admin(principal)
    start = month_start_utc()
    with db_connection() as conn:
        tenant = conn.execute('''SELECT monthly_limit_credits, paused, reservation_credits
             FROM tenant_credit_budgets WHERE tenant_id=%s''', (principal.tenant_id,)).fetchone()
        rows = conn.execute('''
            SELECT u.id, u.username, u.email, b.monthly_limit_credits, COALESCE(b.paused,false),
               COALESCE((SELECT SUM(cost_credits) FROM openrouter_usage_events e
                   WHERE e.tenant_id=u.tenant_id AND e.user_id=u.id AND e.created_at >= %s),0),
               COALESCE((SELECT SUM(reserved_credits) FROM credit_reservations r
                   WHERE r.tenant_id=u.tenant_id AND r.user_id=u.id AND r.created_at >= %s
                     AND r.status IN ('reserved','unknown')),0),
               (SELECT COUNT(*) FROM credit_reservations r WHERE r.tenant_id=u.tenant_id
                   AND r.user_id=u.id AND r.created_at >= %s AND r.status='unknown')
            FROM app_users u LEFT JOIN user_credit_budgets b
              ON u.id=b.user_id AND u.tenant_id=b.tenant_id
            WHERE u.tenant_id=%s ORDER BY u.username
        ''', (start, start, start, principal.tenant_id)).fetchall()
        totals = conn.execute('''
            SELECT COALESCE(SUM(cost_credits),0) FROM openrouter_usage_events
            WHERE tenant_id=%s AND created_at >= %s''',
            (principal.tenant_id, start)).fetchone()
        holds = conn.execute('''
            SELECT COALESCE(SUM(reserved_credits),0), COUNT(*) FILTER (WHERE status='unknown')
            FROM credit_reservations
            WHERE tenant_id=%s AND created_at >= %s AND status IN ('reserved','unknown')''',
            (principal.tenant_id, start)).fetchone()

    def balance(cap: Decimal | None, spent: Decimal, held: Decimal):
        return _display(max(Decimal(0), cap-spent-held)) if cap is not None else None
    tcap = Decimal(str(tenant[0])) if tenant and tenant[0] is not None else None
    t_spent, t_held = Decimal(str(totals[0])), Decimal(str(holds[0]))
    people = []
    for uid, username, email, limit, paused, spent, held, unknown in rows:
        cap = Decimal(str(limit)) if limit is not None else None
        spent, held = Decimal(str(spent)), Decimal(str(held))
        people.append({'user_id':uid, 'username':username, 'email':email,
                       'monthly_limit_credits':_display(cap), 'paused':paused,
                       'spent_credits':_display(spent), 'reserved_credits':_display(held),
                       'remaining_credits':balance(cap,spent,held), 'unknown_cost_requests':int(unknown)})
    return {'month_start_utc':start.isoformat(), 'tenant':{
        'monthly_limit_credits':_display(tcap),
        'reservation_credits':_display(Decimal(str(tenant[2])) if tenant else DEFAULT_RESERVE),
        'paused':bool(tenant[1]) if tenant else False,
        'spent_credits':_display(t_spent), 'reserved_credits':_display(t_held),
        'remaining_credits':balance(tcap,t_spent,t_held),
        'unknown_cost_requests':int(holds[1])}, 'users':people}
