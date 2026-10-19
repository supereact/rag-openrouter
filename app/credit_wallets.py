"""Prepaid balance mutations on the caller's transaction; amounts are never floats."""
from decimal import Decimal

from fastapi import HTTPException

from app import settings
from app.security import Principal


def enforcement_enabled() -> bool:
    value = settings.RAG_WALLET_ENFORCEMENT
    if value not in ('true', 'false'):
        raise HTTPException(503, 'RAG_WALLET_ENFORCEMENT must be true or false')
    if value == 'false':
        return False
    if settings.RAG_PAYMENTS_MODE != 'live' or settings.LLM_PROVIDER != 'openrouter':
        raise HTTPException(503, 'Prepaid usage requires live payment mode and OpenRouter')
    return True


def lock_wallet(conn, principal: Principal, mode: str):
    args = (principal.tenant_id, principal.user_id, mode)
    conn.execute('''INSERT INTO credit_wallets(tenant_id,user_id,mode)
        VALUES (%s,%s,%s) ON CONFLICT DO NOTHING''', args)
    return conn.execute('''SELECT balance,held FROM credit_wallets
        WHERE tenant_id=%s AND user_id=%s AND mode=%s FOR UPDATE''', args).fetchone()


def reserve(conn, principal: Principal, reservation_id, amount: Decimal) -> None:
    balance, held = lock_wallet(conn, principal, 'live')
    if balance - held < amount:
        raise HTTPException(402, 'Insufficient prepaid credits. Add credits on the Credits page.')
    conn.execute('''INSERT INTO credit_wallet_holds
        (reservation_id,tenant_id,user_id,amount) VALUES (%s,%s,%s,%s)''',
        (reservation_id, principal.tenant_id, principal.user_id, amount))
    conn.execute('''UPDATE credit_wallets SET held=held+%s
        WHERE tenant_id=%s AND user_id=%s AND mode='live' ''',
        (amount, principal.tenant_id, principal.user_id))


def finalize(conn, principal: Principal, reservation_id, *, cost=None, release=False) -> None:
    # Only live mode participates in generation. Sandbox purchases remain isolated.
    # Settlement still works when enforcement is disabled during a live rollout.
    if settings.RAG_PAYMENTS_MODE != 'live':
        return
    hold = conn.execute('''SELECT amount FROM credit_wallet_holds
        WHERE reservation_id=%s AND tenant_id=%s AND user_id=%s AND active FOR UPDATE''',
        (reservation_id, principal.tenant_id, principal.user_id)).fetchone()
    if hold is None or (cost is None and not release):
        return
    lock_wallet(conn, principal, 'live')
    charge = Decimal(0) if release else cost
    if not release:
        conn.execute('''INSERT INTO credit_wallet_ledger
            (tenant_id,user_id,mode,kind,amount,reservation_id)
            VALUES (%s,%s,'live','usage',%s,%s)''',
            (principal.tenant_id, principal.user_id, -charge, reservation_id))
    conn.execute('''UPDATE credit_wallets SET held=held-%s,balance=balance-%s
        WHERE tenant_id=%s AND user_id=%s AND mode='live' ''',
        (hold[0], charge, principal.tenant_id, principal.user_id))
    conn.execute('''UPDATE credit_wallet_holds SET active=FALSE
        WHERE reservation_id=%s AND tenant_id=%s AND user_id=%s''',
        (reservation_id, principal.tenant_id, principal.user_id))
