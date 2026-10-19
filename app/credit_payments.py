"""User-owned USDT orders, verified notifications and atomic prepaid top-ups."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from uuid import UUID, uuid4

from fastapi import HTTPException

from app import credit_wallets, nowpayments
from app.db import db_connection
from app.security import Principal

MIN_CREDITS = Decimal('10.00')
MAX_CREDITS = Decimal('1000.00')
FEE_RATE = Decimal('0.055')
ORDER_FIELDS = ('id', 'tenant_id', 'user_id', 'mode', 'request_key', 'credits',
                'service_fee', 'total_usd', 'network', 'status', 'provider_payment_id',
                'pay_address', 'pay_amount', 'expires_at', 'credited_at', 'created_at')
ORDER_SELECT = ','.join(ORDER_FIELDS)
STATUSES = ('waiting', 'confirming', 'confirmed', 'sending', 'partially_paid',
            'finished', 'failed', 'expired', 'refunded')


def money(value) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError('Invalid amount')
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError('Invalid amount') from exc
    if not amount.is_finite() or amount < 0 or amount >= Decimal('1000000000000'):
        raise ValueError('Invalid amount')
    return amount


def quote(credits: str) -> dict:
    if not re.fullmatch(r'[0-9]{1,4}(?:\.[0-9]{1,2})?', credits):
        raise HTTPException(422, 'Credits must be a USD amount with at most two decimal places')
    value = money(credits)
    if not MIN_CREDITS <= value <= MAX_CREDITS:
        raise HTTPException(422, 'Choose between $10 and $1,000 of usable credits')
    fee = (value * FEE_RATE).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return {'credits': format(value, '.2f'), 'service_fee': format(fee, '.2f'),
            'total_usd': format(value + fee, '.2f')}


def _order(conn, order_id, *, principal=None, selected=None, lock=False):
    where, args = 'id=%s', [order_id]
    if principal is not None:
        where += ' AND tenant_id=%s AND user_id=%s'
        args += [principal.tenant_id, principal.user_id]
    if selected is not None:
        where += ' AND mode=%s'
        args.append(selected)
    row = conn.execute(f'SELECT {ORDER_SELECT} FROM credit_payment_orders WHERE {where}' +
                       (' FOR UPDATE' if lock else ''), tuple(args)).fetchone()
    if row is None:
        raise HTTPException(404, 'Payment order not found')
    return dict(zip(ORDER_FIELDS, row))


def _public(row):
    return {key: (format(row[key], 'f') if isinstance(row[key], Decimal) else row[key])
            for key in ('id', 'mode', 'credits', 'service_fee', 'total_usd', 'network',
                        'status', 'pay_address', 'pay_amount', 'expires_at', 'created_at')}


def summary(principal: Principal) -> dict:
    selected = nowpayments.mode()
    balance, held = Decimal(0), Decimal(0)
    if selected != 'disabled':
        with db_connection() as conn:
            row = conn.execute('''SELECT balance,held FROM credit_wallets
                WHERE tenant_id=%s AND user_id=%s AND mode=%s''',
                (principal.tenant_id, principal.user_id, selected)).fetchone()
            if row:
                balance, held = row
    return {'mode': selected, 'payments_enabled': nowpayments.ready(selected),
            'usage_enforced': credit_wallets.enforcement_enabled(),
            'balance': format(balance, 'f'), 'reserved': format(held, 'f'),
            'available': format(max(Decimal(0), balance-held), 'f'),
            'service_fee_percent': '5.5', 'minimum_credits': str(MIN_CREDITS),
            'maximum_credits': str(MAX_CREDITS),
            'networks': [{'id': key, 'label': label} for key, label in nowpayments.NETWORKS.items()]}


def history(principal: Principal, page: int, page_size: int, *, transactions=False) -> dict:
    selected = nowpayments.mode()
    if selected == 'disabled':
        return {'items': [], 'page': 1, 'page_size': page_size, 'total': 0, 'pages': 1}
    table = 'credit_wallet_ledger' if transactions else 'credit_payment_orders'
    fields = 'id,kind,amount,created_at' if transactions else ORDER_SELECT
    args = (principal.tenant_id, principal.user_id, selected)
    with db_connection() as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        total = conn.execute(f'SELECT count(*) FROM {table} WHERE tenant_id=%s AND user_id=%s AND mode=%s', args).fetchone()[0]
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        rows = conn.execute(f'''SELECT {fields} FROM {table}
            WHERE tenant_id=%s AND user_id=%s AND mode=%s
            ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s''',
            (*args, page_size, (page-1)*page_size)).fetchall()
    items = ([{'id': row[0], 'kind': row[1], 'amount': format(row[2], 'f'), 'created_at': row[3]}
              for row in rows] if transactions else [_public(dict(zip(ORDER_FIELDS, row))) for row in rows])
    return {'items': items, 'page': page, 'page_size': page_size, 'total': total, 'pages': pages}


def _payment_id(value) -> str:
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]{1,40}', str(value)):
        raise HTTPException(400, 'Invalid provider payment identity')
    return str(value)


def _validate(row: dict, data: dict):
    try:
        identity = _payment_id(data.get('payment_id'))
        if (str(data.get('order_id')) != str(row['id']) or
                (row['provider_payment_id'] is not None and identity != row['provider_payment_id']) or
                data.get('price_currency', '').lower() != 'usd' or
                money(data.get('price_amount')) != row['total_usd'] or
                data.get('pay_currency', '').lower() != row['network'] or
                data.get('payment_status') not in STATUSES):
            raise ValueError('Payment details do not match')
        required = money(data.get('pay_amount'))
        if required <= 0 or (row['pay_amount'] is not None and required != row['pay_amount']):
            raise ValueError('Payment quote does not match')
    except (ValueError, AttributeError) as exc:
        raise HTTPException(400, 'Payment details do not match this order') from exc


def create_order(principal: Principal, credits: str, network: str, request_key: UUID):
    selected = nowpayments.mode()
    if selected == 'disabled' or not nowpayments.ready(selected):
        raise HTTPException(503, 'USDT payments are not enabled or configured')
    if network not in nowpayments.NETWORKS:
        raise HTTPException(422, 'Unsupported USDT network')
    amounts = quote(credits)
    with db_connection() as conn:
        # Serializes duplicate checkout attempts and bounds provider order spam.
        credit_wallets.lock_wallet(conn, principal, selected)
        previous = conn.execute('''SELECT id FROM credit_payment_orders
            WHERE tenant_id=%s AND user_id=%s AND mode=%s AND request_key=%s''',
            (principal.tenant_id, principal.user_id, selected, request_key)).fetchone()
        if previous:
            row = _order(conn, previous[0], principal=principal, selected=selected)
            if row['credits'] != money(amounts['credits']) or row['network'] != network:
                raise HTTPException(409, 'This checkout key was already used for different purchase details')
            return _public(row)
        count = conn.execute('''SELECT count(*) FROM credit_payment_orders
            WHERE tenant_id=%s AND user_id=%s AND mode=%s
              AND created_at>now()-interval '15 minutes' ''',
            (principal.tenant_id, principal.user_id, selected)).fetchone()[0]
        if count >= 5:
            raise HTTPException(429, 'Too many payment attempts. Review existing orders before trying again.')
        order_id = uuid4()
        conn.execute('''INSERT INTO credit_payment_orders
            (id,tenant_id,user_id,mode,request_key,credits,service_fee,total_usd,network)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (order_id, principal.tenant_id, principal.user_id, selected, request_key,
             amounts['credits'], amounts['service_fee'], amounts['total_usd'], network))
    body = {'price_amount': amounts['total_usd'], 'price_currency': 'usd',
            'pay_currency': network, 'order_id': str(order_id),
            'order_description': 'Prepaid AI credits',
            'ipn_callback_url': nowpayments.callback_url(selected),
            'is_fixed_rate': True, 'is_fee_paid_by_user': False}
    if selected == 'sandbox':
        body['case'] = 'success'
    try:
        data = nowpayments.api_request(selected, 'POST', '/payment', body)
        with db_connection() as conn:
            row = _order(conn, order_id, principal=principal, selected=selected, lock=True)
            _validate(row, data)
            address = data.get('pay_address')
            if not isinstance(address, str) or not 1 <= len(address) <= 256:
                raise HTTPException(502, 'Payment address unavailable; review this order')
            expiry = data.get('expiration_estimate_date')
            expiry = datetime.fromisoformat(expiry.replace('Z', '+00:00')) if expiry else None
            if expiry is not None and expiry.tzinfo is None:
                raise ValueError('Payment expiry must include its timezone')
            conn.execute('''UPDATE credit_payment_orders SET provider_payment_id=%s,
                pay_address=%s,pay_amount=%s,expires_at=%s,
                status=CASE WHEN status='creating' THEN 'waiting' ELSE status END,updated_at=now()
                WHERE id=%s''', (_payment_id(data['payment_id']), address,
                                money(data['pay_amount']), expiry, order_id))
            return _public(_order(conn, order_id, principal=principal))
    except (HTTPException, ValueError):
        with db_connection() as conn:
            conn.execute('''UPDATE credit_payment_orders SET status='review',updated_at=now()
                WHERE id=%s AND status='creating' ''', (order_id,))
        # Creation timeouts are ambiguous. Never silently create another payment.
        raise HTTPException(502, 'Payment creation needs review. Refresh payment history before trying again.')


def _apply(conn, row: dict, data: dict):
    _validate(row, data)
    state = data['payment_status']
    owner = Principal(row['user_id'], row['tenant_id'], '', '')
    if state == 'finished' and row['status'] != 'refunded':
        try:
            full = money(data.get('actually_paid')) >= money(data['pay_amount'])
        except ValueError:
            full = False
        if not full:
            state = 'review'
        elif row['credited_at'] is None:
            credit_wallets.lock_wallet(conn, owner, row['mode'])
            conn.execute('''INSERT INTO credit_wallet_ledger
                (tenant_id,user_id,mode,kind,amount,order_id) VALUES (%s,%s,%s,'topup',%s,%s)''',
                (row['tenant_id'], row['user_id'], row['mode'], row['credits'], row['id']))
            conn.execute('''UPDATE credit_wallets SET balance=balance+%s
                WHERE tenant_id=%s AND user_id=%s AND mode=%s''',
                (row['credits'], row['tenant_id'], row['user_id'], row['mode']))
            conn.execute('UPDATE credit_payment_orders SET credited_at=now() WHERE id=%s', (row['id'],))
    elif state == 'refunded' and row['credited_at'] is not None and row['status'] != 'refunded':
        credit_wallets.lock_wallet(conn, owner, row['mode'])
        conn.execute('''INSERT INTO credit_wallet_ledger
            (tenant_id,user_id,mode,kind,amount,order_id) VALUES (%s,%s,%s,'refund',%s,%s)''',
            (row['tenant_id'], row['user_id'], row['mode'], -row['credits'], row['id']))
        conn.execute('''UPDATE credit_wallets SET balance=balance-%s
            WHERE tenant_id=%s AND user_id=%s AND mode=%s''',
            (row['credits'], row['tenant_id'], row['user_id'], row['mode']))
    # Terminal credited/refunded orders cannot be downgraded by delayed events.
    if row['status'] == 'refunded' or (row['credited_at'] is not None and state != 'refunded'):
        state = row['status']
    progress = {'creating': 0, 'waiting': 1, 'confirming': 2, 'confirmed': 3,
                'sending': 4, 'partially_paid': 5, 'review': 6, 'failed': 7, 'expired': 7}
    if state in progress and progress.get(row['status'], 0) > progress[state]:
        state = row['status']
    conn.execute('''UPDATE credit_payment_orders SET status=%s,provider_payment_id=%s,updated_at=now()
        WHERE id=%s''', (state, _payment_id(data['payment_id']), row['id']))


def check_order(principal: Principal, order_id: UUID):
    selected = nowpayments.mode()
    with db_connection() as conn:
        row = _order(conn, order_id, principal=principal, selected=selected)
    if row['provider_payment_id'] is None:
        return _public(row)
    data = nowpayments.api_request(selected, 'GET', f"/payment/{_payment_id(row['provider_payment_id'])}")
    with db_connection() as conn:
        row = _order(conn, order_id, principal=principal, selected=selected, lock=True)
        _apply(conn, row, data)
        return _public(_order(conn, order_id, principal=principal))


def notification(selected: str, raw: bytes, signature: str):
    payload, digest = nowpayments.verify_ipn(selected, raw, signature)
    try:
        order_id = UUID(str(payload.get('order_id')))
    except ValueError as exc:
        raise HTTPException(400, 'Invalid payment order identity') from exc
    with db_connection() as conn:
        row = _order(conn, order_id, selected=selected)
        if conn.execute('''SELECT 1 FROM credit_payment_notifications
            WHERE mode=%s AND payload_hash=%s''', (selected, digest)).fetchone():
            return
    _validate(row, payload)
    if payload['payment_status'] in ('finished', 'refunded'):
        verified = nowpayments.api_request(selected, 'GET', f"/payment/{_payment_id(payload['payment_id'])}")
        _validate(row, verified)
        if verified['payment_status'] not in ('finished', 'refunded'):
            raise HTTPException(503, 'Final payment status is not yet available; retry notification')
        if payload['payment_status'] == 'refunded' and verified['payment_status'] != 'refunded':
            raise HTTPException(503, 'Refund status is not yet available; retry notification')
        payload = verified
    with db_connection() as conn:
        row = _order(conn, order_id, selected=selected, lock=True)
        if conn.execute('''SELECT 1 FROM credit_payment_notifications
            WHERE mode=%s AND payload_hash=%s''', (selected, digest)).fetchone():
            return
        _apply(conn, row, payload)
        conn.execute('''INSERT INTO credit_payment_notifications(mode,payload_hash,order_id,payment_status)
            VALUES (%s,%s,%s,%s)''', (selected, digest, order_id, payload['payment_status']))
