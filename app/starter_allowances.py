"""One-time provider-cost allowance for accounts created after migration.

Existing users have no row and retain their current policies. This is an
application spending guardrail, not money credited to an OpenRouter account.
"""
from decimal import Decimal

from app.security import Principal

INITIAL_CREDITS = Decimal('0.001')


def provision(conn, tenant_id: int, user_id: int) -> None:
    # Called only inside account creation, never login/session restoration.
    conn.execute('''INSERT INTO user_starter_allowances(tenant_id,user_id,limit_credits)
        VALUES (%s,%s,%s)''', (tenant_id, user_id, INITIAL_CREDITS))


def remaining(conn, principal: Principal) -> Decimal | None:
    row = conn.execute('''SELECT limit_credits FROM user_starter_allowances
        WHERE tenant_id=%s AND user_id=%s''',
        (principal.tenant_id, principal.user_id)).fetchone()
    if row is None:
        return None
    totals = conn.execute('''SELECT
        COALESCE((SELECT SUM(cost_credits) FROM openrouter_usage_events
            WHERE tenant_id=%s AND user_id=%s),0),
        COALESCE((SELECT SUM(reserved_credits) FROM credit_reservations
            WHERE tenant_id=%s AND user_id=%s AND status IN ('reserved','unknown')),0)
    ''', (principal.tenant_id, principal.user_id,
          principal.tenant_id, principal.user_id)).fetchone()
    # No monthly date filter: neither month rollover nor a new session refills it.
    return Decimal(str(row[0])) - sum(Decimal(str(value)) for value in totals)
