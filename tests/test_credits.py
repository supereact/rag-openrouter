"""Payment and wallet regressions using transactional in-memory DB/provider doubles.

These tests never connect to PostgreSQL or a payment/LLM provider.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import json
from threading import RLock
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import credit_budgets, credit_payments as payments, credit_wallets as wallets, main, nowpayments, observability, security, settings
from app.security import Principal

USER = Principal(2, 10, 'reader', 'buyer')
OTHER = Principal(3, 11, 'admin', 'outside')
NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)


class Cursor:
    def __init__(self, rows=None):
        self.rows = rows
    def fetchone(self):
        return self.rows
    def fetchall(self):
        return self.rows


class Store:
    def __init__(self):
        self.orders, self.wallets, self.holds = {}, {}, {}
        self.ledger, self.receipts, self.log = [], set(), []
        self.reservations, self.usage = {}, []
        self.fail_ledger = False
        self.lock = RLock()

    @contextmanager
    def connect(self):
        with self.lock:
            before = deepcopy((self.orders, self.wallets, self.holds, self.ledger, self.receipts, self.reservations, self.usage))
            try:
                yield self
            except Exception:
                self.orders, self.wallets, self.holds, self.ledger, self.receipts, self.reservations, self.usage = before
                raise

    def execute(self, sql, args=()):
        q = ' '.join(sql.lower().split())
        self.log.append((q, args))
        if q.startswith('select pg_advisory_xact_lock'):
            return Cursor()
        if q.startswith('select monthly_limit_credits'):
            return Cursor(None)
        if q.startswith('select coalesce((select sum(cost_credits)'):
            return Cursor((Decimal(0),)*4)  # No monthly policies in wallet integration cases.
        if q.startswith('insert into credit_reservations'):
            self.reservations[args[0]] = dict(tenant=args[1], user=args[2], amount=args[3], status='reserved')
            return Cursor()
        if q.startswith('select status from credit_reservations'):
            row = self.reservations.get(args[0])
            return Cursor((row['status'],) if row and (row['tenant'], row['user']) == tuple(args[1:]) else None)
        if q.startswith("update credit_reservations set status='released'"):
            self.reservations[args[0]]['status'] = 'released'
            return Cursor()
        if q.startswith('update credit_reservations set status=%s'):
            self.reservations[args[2]]['status'] = args[0]
            return Cursor()
        if q.startswith('insert into openrouter_usage_events'):
            self.usage.append(args)
            return Cursor()
        if q.startswith('set transaction'):
            return Cursor()
        if q.startswith('insert into credit_wallets('):
            self.wallets.setdefault(tuple(args), [Decimal(0), Decimal(0)])
            return Cursor()
        if q.startswith('select balance,held from credit_wallets'):
            return Cursor(tuple(self.wallets[tuple(args)]) if tuple(args) in self.wallets else None)
        if q.startswith('update credit_wallets set held=held+'):
            self.wallets[(*args[1:], 'live')][1] += args[0]
            return Cursor()
        if q.startswith('update credit_wallets set held=held-'):
            wallet = self.wallets[(*args[2:], 'live')]
            wallet[0] -= args[1]
            wallet[1] -= args[0]
            return Cursor()
        if q.startswith('update credit_wallets set balance=balance'):
            self.wallets[tuple(args[1:])][0] += args[0] if 'balance=balance+' in q else -args[0]
            return Cursor()
        if q.startswith('insert into credit_payment_orders'):
            row = dict(zip(payments.ORDER_FIELDS[:9], args))
            for name in ('credits', 'service_fee', 'total_usd'):
                row[name] = Decimal(row[name])
            row.update(status='creating', provider_payment_id=None, pay_address=None,
                       pay_amount=None, expires_at=None, credited_at=None, created_at=NOW)
            self.orders[row['id']] = row
            return Cursor()
        if q.startswith('select id from credit_payment_orders'):
            matches = [r for r in self.orders.values() if
                       (r['tenant_id'], r['user_id'], r['mode'], r['request_key']) == tuple(args)]
            return Cursor((matches[0]['id'],) if matches else None)
        if 'from credit_payment_orders where id=%s' in q:
            row = self.orders.get(args[0])
            if row and len(args) >= 3 and (row['tenant_id'], row['user_id']) != tuple(args[1:3]):
                row = None
            if row and len(args) in (2, 4) and row['mode'] != args[-1]:
                row = None
            return Cursor(tuple(row[name] for name in payments.ORDER_FIELDS) if row else None)
        if q.startswith('select count(*) from credit_payment_orders'):
            return Cursor((sum((r['tenant_id'], r['user_id'], r['mode']) == tuple(args[:3]) for r in self.orders.values()),))
        if q.startswith('select count(*) from credit_wallet_ledger'):
            return Cursor((sum((r['tenant_id'], r['user_id'], r['mode']) == tuple(args) for r in self.ledger),))
        if q.startswith('select ') and 'from credit_payment_orders' in q and 'limit %s offset %s' in q:
            rows = sorted((r for r in self.orders.values() if
                           (r['tenant_id'], r['user_id'], r['mode']) == tuple(args[:3])),
                          key=lambda r: (r['created_at'], r['id']), reverse=True)
            return Cursor([tuple(r[n] for n in payments.ORDER_FIELDS) for r in rows[args[4]:args[4]+args[3]]])
        if q.startswith('select id,kind,amount,created_at from credit_wallet_ledger'):
            rows = [r for r in self.ledger if (r['tenant_id'], r['user_id'], r['mode']) == tuple(args[:3])][::-1]
            return Cursor([tuple(r[n] for n in ('id', 'kind', 'amount', 'created_at')) for r in rows[args[4]:args[4]+args[3]]])
        if q.startswith('update credit_payment_orders set provider_payment_id='):
            row = self.orders[args[-1]]
            row.update(provider_payment_id=args[0], pay_address=args[1], pay_amount=args[2], expires_at=args[3])
            if row['status'] == 'creating':
                row['status'] = 'waiting'
            return Cursor()
        if q.startswith("update credit_payment_orders set status='review'"):
            if self.orders[args[0]]['status'] == 'creating':
                self.orders[args[0]]['status'] = 'review'
            return Cursor()
        if q.startswith('update credit_payment_orders set credited_at='):
            self.orders[args[0]]['credited_at'] = NOW
            return Cursor()
        if q.startswith('update credit_payment_orders set status=%s'):
            self.orders[args[2]].update(status=args[0], provider_payment_id=args[1])
            return Cursor()
        if q.startswith('insert into credit_wallet_ledger'):
            if self.fail_ledger:
                raise RuntimeError('synthetic transaction failure')
            if "'usage'" in q:
                tenant, user, amount, reservation = args
                row = dict(tenant_id=tenant, user_id=user, mode='live', kind='usage', amount=amount, reservation_id=reservation)
            else:
                tenant, user, mode, amount, order_id = args
                row = dict(tenant_id=tenant, user_id=user, mode=mode, kind='topup' if "'topup'" in q else 'refund', amount=amount, order_id=order_id)
            assert not any(r.get('order_id') == row.get('order_id') and r['kind'] == row['kind'] and row.get('order_id') for r in self.ledger)
            row.update(id=len(self.ledger)+1, created_at=NOW)
            self.ledger.append(row)
            return Cursor()
        if q.startswith('select 1 from credit_payment_notifications'):
            return Cursor((1,) if tuple(args) in self.receipts else None)
        if q.startswith('insert into credit_payment_notifications'):
            self.receipts.add(tuple(args[:2]))
            return Cursor()
        if q.startswith('insert into credit_wallet_holds'):
            self.holds[args[0]] = dict(tenant=args[1], user=args[2], amount=args[3], active=True)
            return Cursor()
        if q.startswith('select amount from credit_wallet_holds'):
            row = self.holds.get(args[0])
            return Cursor((row['amount'],) if row and row['active'] and (row['tenant'], row['user']) == tuple(args[1:]) else None)
        if q.startswith('update credit_wallet_holds set active=false'):
            self.holds[args[0]]['active'] = False
            return Cursor()
        raise AssertionError('Unexpected SQL: ' + q)


@pytest.fixture
def state(monkeypatch):
    store = Store()
    monkeypatch.setattr(payments, 'db_connection', store.connect)
    monkeypatch.setattr(credit_budgets, 'db_connection', store.connect)
    monkeypatch.setattr(settings, 'RAG_PAYMENTS_MODE', 'sandbox')
    monkeypatch.setattr(settings, 'RAG_WALLET_ENFORCEMENT', 'false')
    monkeypatch.setattr(settings, 'RAG_PAYMENTS_CALLBACK_BASE_URL', 'https://rag.example/api')
    for name in ('NOWPAYMENTS_API_KEY', 'NOWPAYMENTS_SANDBOX_API_KEY'):
        monkeypatch.setattr(settings, name, 'synthetic-key')
    for name in ('NOWPAYMENTS_IPN_SECRET', 'NOWPAYMENTS_SANDBOX_IPN_SECRET'):
        monkeypatch.setattr(settings, name, 'synthetic-secret-' + name)
    provider = {}
    def request(mode, method, path, body=None):
        if method == 'POST':
            identity = str(1000 + len(provider))
            data = {**body, 'payment_id': identity, 'payment_status': 'waiting',
                    'pay_address': 'synthetic-public-test-address', 'pay_amount': body['price_amount'],
                    'actually_paid': '0'}
            provider[identity] = data
            return deepcopy(data)
        return deepcopy(provider[path.rsplit('/', 1)[1]])
    adapter = Mock(side_effect=request)
    monkeypatch.setattr(nowpayments, 'api_request', adapter)
    store.provider, store.adapter = provider, adapter
    return store


def create(state, user=USER, **kwargs):
    return payments.create_order(user, kwargs.get('credits', '10.00'), kwargs.get('network', 'usdttrc20'), kwargs.get('key', uuid4()))


def payload(state, order, status='finished', **changes):
    row = state.orders[order['id']]
    data = state.provider[row['provider_payment_id']]
    data.update(payment_status=status, actually_paid=data['pay_amount'])
    data.update(changes)
    return deepcopy(data)


def signed(data, mode='sandbox'):
    raw = json.dumps(data).encode()
    canonical = json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    secret = nowpayments.credentials(mode)[1]
    return raw, hmac.new(secret.encode(), canonical, hashlib.sha512).hexdigest()


@pytest.mark.parametrize('amount,fee,total', [('10', '0.55', '10.55'), ('25', '1.38', '26.38'), ('100', '5.50', '105.50')])
def test_purchase_fee_is_added_once(amount, fee, total):
    assert payments.quote(amount) == {'credits': f'{Decimal(amount):.2f}', 'service_fee': fee, 'total_usd': total}


@pytest.mark.parametrize('amount', ['NaN', 'Infinity', '-1', '9.99', '1000.01', '10.001', '1e2', ' 10', '10.'])
def test_invalid_purchase_amounts(amount):
    with pytest.raises(HTTPException):
        payments.quote(amount)


def test_order_creation_has_no_credit_and_reuses_checkout_key(state):
    key = uuid4()
    order = create(state, key=key)
    assert create(state, key=key) == order
    assert state.adapter.call_count == 1
    body = state.adapter.call_args.args[3]
    assert body['price_amount'] == '10.55'
    assert body['is_fee_paid_by_user'] is False
    assert body['case'] == 'success'
    assert body['ipn_callback_url'] == 'https://rag.example/api/payments/nowpayments/sandbox/ipn'
    assert not state.ledger
    assert payments.summary(USER)['available'] == '0'
    with pytest.raises(HTTPException) as error:
        create(state, key=key, credits='20')
    assert error.value.status_code == 409


def test_disabled_payments_and_invalid_network_never_create_order(state, monkeypatch):
    monkeypatch.setattr(settings, 'RAG_PAYMENTS_MODE', 'disabled')
    with pytest.raises(HTTPException):
        create(state)
    assert not state.orders and not state.adapter.called
    assert payments.summary(USER)['payments_enabled'] is False
    monkeypatch.setattr(settings, 'RAG_PAYMENTS_MODE', 'sandbox')
    with pytest.raises(HTTPException):
        create(state, network='btc')
    assert not state.orders


def test_uncertain_create_is_not_retried_automatically(state):
    key = uuid4()
    state.adapter.side_effect = HTTPException(502, 'synthetic timeout')
    with pytest.raises(HTTPException):
        create(state, key=key)
    review = create(state, key=key)
    assert review['status'] == 'review'
    assert state.adapter.call_count == 1
    assert not state.ledger


def test_duplicate_and_reordered_notifications_credit_once(state):
    order = create(state)
    complete = payload(state, order)
    raw, sig = signed(complete)
    payments.notification('sandbox', raw, sig)
    payments.notification('sandbox', raw, sig)
    payments.notification('sandbox', *signed({**complete, 'payment_status': 'waiting'}))
    payments.notification('sandbox', *signed({**complete, 'extra': 'distinct-event'}))
    assert payments.summary(USER)['available'] == '10.00'
    assert len(state.ledger) == 1
    assert state.orders[order['id']]['status'] == 'finished'
    assert state.orders[order['id']]['credited_at'] is not None


@pytest.mark.parametrize('changes', [
    {'price_amount': '11'}, {'price_currency': 'eur'}, {'pay_currency': 'usdterc20'},
    {'pay_amount': '0.01'}, {'payment_id': '9999'}, {'order_id': str(uuid4())},
])
def test_signed_but_mismatched_notifications_cannot_credit(state, changes):
    order = create(state)
    with pytest.raises(HTTPException):
        payments.notification('sandbox', *signed(payload(state, order, **changes)))
    assert not state.ledger and not state.receipts
    assert payments.summary(USER)['available'] == '0'


@pytest.mark.parametrize('status', ['waiting', 'confirming', 'confirmed', 'sending', 'partially_paid', 'failed', 'expired'])
def test_nonfinal_status_does_not_credit(state, status):
    order = create(state)
    payments.notification('sandbox', *signed(payload(state, order, status)))
    assert not state.ledger


def test_full_payment_required_even_if_status_says_finished(state):
    order = create(state)
    payments.notification('sandbox', *signed(payload(state, order, actually_paid='1')))
    assert not state.ledger
    assert state.orders[order['id']]['status'] == 'review'


@pytest.mark.parametrize('status', ['partially_paid', 'review', 'failed', 'expired'])
def test_delayed_progress_cannot_restore_full_payment_instructions(state, status):
    order = create(state)
    state.orders[order['id']]['status'] = status
    payments.notification('sandbox', *signed(payload(state, order, 'waiting')))
    assert state.orders[order['id']]['status'] == status
    assert not state.ledger


def test_admin_in_same_tenant_cannot_browse_someone_elses_wallet(state):
    order = create(state)
    admin = Principal(9, USER.tenant_id, 'admin', 'tenant-admin')
    assert payments.history(admin, 1, 20)['total'] == 0
    assert payments.summary(admin)['balance'] == '0'
    with pytest.raises(HTTPException) as error:
        payments.check_order(admin, order['id'])
    assert error.value.status_code == 404


def test_verified_refund_reverses_once_and_blocks_late_finished_event(state):
    order = create(state)
    payments.notification('sandbox', *signed(payload(state, order)))
    refund = payload(state, order, 'refunded')
    payments.notification('sandbox', *signed(refund))
    payments.notification('sandbox', *signed({**refund, 'extra': 'second-refund'}))
    payments.notification('sandbox', *signed({**refund, 'payment_status': 'finished'}))
    assert payments.summary(USER)['available'] == '0'
    assert [entry['kind'] for entry in state.ledger] == ['topup', 'refund']
    assert state.orders[order['id']]['status'] == 'refunded'


def test_provider_lookup_failure_and_db_failure_leave_credit_retryable(state):
    order = create(state)
    event = signed(payload(state, order))
    original = state.adapter.side_effect
    state.adapter.side_effect = HTTPException(502, 'synthetic provider outage')
    with pytest.raises(HTTPException):
        payments.notification('sandbox', *event)
    assert not state.ledger and not state.receipts
    state.adapter.side_effect = original
    state.fail_ledger = True
    with pytest.raises(RuntimeError):
        payments.notification('sandbox', *event)
    assert not state.ledger and not state.receipts
    assert state.orders[order['id']]['credited_at'] is None
    state.fail_ledger = False
    payments.notification('sandbox', *event)
    assert payments.summary(USER)['available'] == '10.00'


def test_history_scope_stable_pagination_and_admin_privacy(state):
    first = create(state)
    create(state, OTHER)
    pages = payments.history(USER, 99, 20)
    assert pages['page'] == 1 and pages['total'] == 1
    assert [row['id'] for row in pages['items']] == [first['id']]
    with pytest.raises(HTTPException) as error:
        payments.check_order(OTHER, first['id'])
    assert error.value.status_code == 404
    assert payments.history(OTHER, 1, 20)['total'] == 1
    for _ in range(3):
        create(state)
    expected = sorted((r for r in state.orders.values() if r['user_id'] == USER.user_id), key=lambda r: r['id'], reverse=True)
    assert [r['id'] for r in payments.history(USER, 2, 2)['items']] == [r['id'] for r in expected[2:4]]


def test_sandbox_never_funds_live_balance(state, monkeypatch):
    order = create(state)
    payments.notification('sandbox', *signed(payload(state, order)))
    monkeypatch.setattr(settings, 'RAG_PAYMENTS_MODE', 'live')
    assert payments.summary(USER)['available'] == '0'
    assert payments.history(USER, 1, 20)['total'] == 0
    with pytest.raises(HTTPException):
        payments.notification('live', *signed(payload(state, order), 'live'))
    assert ('live', USER.tenant_id, USER.user_id) not in state.wallets


def test_wallet_holds_balance_checks_overage_and_idempotency(state, monkeypatch):
    monkeypatch.setattr(settings, 'RAG_PAYMENTS_MODE', 'live')
    state.wallets[(USER.tenant_id, USER.user_id, 'live')] = [Decimal('.02'), Decimal(0)]
    rid1, rid2 = uuid4(), uuid4()
    with state.connect() as conn:
        wallets.reserve(conn, USER, rid1, Decimal('.01'))
        wallets.reserve(conn, USER, rid2, Decimal('.01'))
    with pytest.raises(HTTPException) as error, state.connect() as conn:
        wallets.reserve(conn, USER, uuid4(), Decimal('.01'))
    assert error.value.status_code == 402
    wallets.finalize(state, USER, rid1)  # Unknown cost retains the hold.
    assert payments.summary(USER)['reserved'] == '0.02'
    wallets.finalize(state, USER, rid1, cost=Decimal('.025'))
    wallets.finalize(state, USER, rid1, cost=Decimal('.025'))
    wallets.finalize(state, USER, rid2, release=True)
    assert payments.summary(USER)['balance'] == '-0.005'
    assert payments.summary(USER)['reserved'] == '0.00'
    assert len(state.ledger) == 1 and state.ledger[0]['amount'] == Decimal('-.025')


def test_wallet_unknown_hold_not_released_for_other_identity(state, monkeypatch):
    monkeypatch.setattr(settings, 'RAG_PAYMENTS_MODE', 'live')
    state.wallets[(USER.tenant_id, USER.user_id, 'live')] = [Decimal('1'), Decimal(0)]
    rid = uuid4()
    wallets.reserve(state, USER, rid, Decimal('.01'))
    wallets.finalize(state, OTHER, rid, release=True)
    assert state.holds[rid]['active']
    assert payments.summary(USER)['reserved'] == '0.01'


def test_canonical_signature_nested_fields_invalid_body_and_mode_secrets(state):
    event = {'payment_id': 1, 'nested': {'z': 2, 'a': ['中文', 3]}}
    raw, sig = signed(event)
    assert nowpayments.verify_ipn('sandbox', raw, sig)[0] == event
    for selected, body, signature in [('live', raw, sig), ('sandbox', raw+b' ', '0'*128),
                                       ('sandbox', b'{"a":1,"a":2}', sig), ('sandbox', b'{"a":NaN}', sig)]:
        with pytest.raises(HTTPException):
            nowpayments.verify_ipn(selected, body, signature)


def test_payment_attempt_rate_bound(state):
    for _ in range(5):
        create(state)
    with pytest.raises(HTTPException) as error:
        create(state)
    assert error.value.status_code == 429 and state.adapter.call_count == 5


@pytest.fixture
def client(state, monkeypatch):
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    monkeypatch.setattr(main.app, 'dependency_overrides', {security.require_principal: lambda: USER})
    with TestClient(main.app) as client:
        yield client


def test_api_reader_can_purchase_and_cannot_choose_identity(client, state):
    response = client.post('/credits/orders', json={'credits': '10', 'network': 'usdttrc20', 'request_key': str(uuid4())})
    assert response.status_code == 201
    assert response.json()['total_usd'] == '10.55'
    assert response.headers['cache-control'] == 'no-store'
    assert 'tenant_id' not in response.json() and 'provider_payment_id' not in response.json()
    assert client.get('/credits').json()['balance'] == '0'
    assert client.get('/credits/orders?page=99').json()['page'] == 1
    assert client.get('/credits/orders?page_size=21').status_code == 422
    assert client.get('/credits/transactions').json()['total'] == 0
    assert client.post('/credits/orders', json={'credits': '10', 'network': 'usdttrc20', 'request_key': str(uuid4()), 'user_id': 4}).status_code == 422


def test_api_auth_csrf_signature_and_body_limits(client, state, monkeypatch):
    main.app.dependency_overrides.clear()
    for method, path in [('get', '/credits'), ('get', '/credits/orders'), ('get', '/credits/transactions'),
                         ('post', '/credits/orders'), ('post', f'/credits/orders/{uuid4()}/check')]:
        assert getattr(client, method)(path).status_code == 401
    monkeypatch.setattr(security, 'principal_from_api_key', lambda token: USER)
    client.cookies.set('rag_browser_session', 'rags_' + 'x'*40)
    assert client.post('/credits/orders', json={}).status_code == 403
    assert client.post('/payments/nowpayments/sandbox/ipn', content=b'{}').status_code == 401
    assert client.post('/payments/nowpayments/sandbox/ipn', content=b'x'*64001).status_code == 413
    assert not state.orders


def test_authorized_manual_check_recovers_missed_callback(client, state):
    order = create(state)
    payload(state, order)
    assert client.post(f"/credits/orders/{order['id']}/check").status_code == 200
    assert client.post(f"/credits/orders/{order['id']}/check").status_code == 200
    assert client.get('/credits').json()['available'] == '10.00'
    assert len(state.ledger) == 1


def test_callback_has_no_user_session_requirement(client, state):
    order = create(state)
    raw, sig = signed(payload(state, order))
    main.app.dependency_overrides.clear()
    assert client.post('/payments/nowpayments/sandbox/ipn', content=raw, headers={'x-nowpayments-sig': sig}).status_code == 204
    assert len(state.ledger) == 1


def test_enforcement_rejects_unsupported_mode_and_provider(state, monkeypatch):
    monkeypatch.setattr(settings, 'RAG_WALLET_ENFORCEMENT', 'true')
    with pytest.raises(HTTPException):
        wallets.enforcement_enabled()
    monkeypatch.setattr(settings, 'RAG_PAYMENTS_MODE', 'live')
    monkeypatch.setattr(settings, 'LLM_PROVIDER', 'openai')
    with pytest.raises(HTTPException):
        wallets.enforcement_enabled()
    monkeypatch.setattr(settings, 'LLM_PROVIDER', 'openrouter')
    monkeypatch.setattr(settings, 'OPENROUTER_MODEL', 'synthetic/model')
    assert wallets.enforcement_enabled()


def enable_wallet(state, monkeypatch, balance='1'):
    monkeypatch.setattr(settings, 'RAG_PAYMENTS_MODE', 'live')
    monkeypatch.setattr(settings, 'RAG_WALLET_ENFORCEMENT', 'true')
    monkeypatch.setattr(settings, 'LLM_PROVIDER', 'openrouter')
    state.wallets[(USER.tenant_id, USER.user_id, 'live')] = [Decimal(balance), Decimal(0)]


def test_insufficient_wallet_rolls_back_monthly_reservation(state, monkeypatch):
    enable_wallet(state, monkeypatch, '0')
    with pytest.raises(HTTPException) as error:
        credit_budgets.reserve_request(USER)
    assert error.value.status_code == 402
    assert not state.reservations and not state.holds


def test_concurrent_reservations_cannot_spend_the_same_available_credit(state, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    enable_wallet(state, monkeypatch, '.01')
    def reserve():
        try:
            return credit_budgets.reserve_request(USER)
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reserve(), range(2)))
    assert results.count(402) == 1
    assert len(state.reservations) == len(state.holds) == 1
    assert payments.summary(USER)['reserved'] == '0.01'
    assert any('for update' in sql for sql, _ in state.log)


def test_failed_wallet_settlement_keeps_all_accounting_unchanged(state, monkeypatch):
    enable_wallet(state, monkeypatch)
    rid = credit_budgets.reserve_request(USER)
    state.fail_ledger = True
    with pytest.raises(RuntimeError):
        credit_budgets.settle_request(rid, USER, 'synthetic/model', {'provider_cost_credits': .002})
    assert state.reservations[rid]['status'] == 'reserved'
    assert state.holds[rid]['active']
    assert not state.usage and not state.ledger
    assert payments.summary(USER)['balance'] == '1'
    assert payments.summary(USER)['reserved'] == '0.01'


@pytest.mark.parametrize('path', ['/ask', '/conversations/7/ask'])
@pytest.mark.parametrize('outcome', ['paid', 'empty', 'retrieval_failure', 'missing_cost', 'zero_cost'])
def test_question_paths_preserve_wallet_usage_and_unknown_holds(state, monkeypatch, path, outcome):
    from app.schemas import SearchHit
    enable_wallet(state, monkeypatch)
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    monkeypatch.setattr(main.app, 'dependency_overrides', {security.require_principal: lambda: USER})
    sources = [SearchHit(source_number=1, document_id=11, title='Synthetic policy',
                         chunk_index=0, content='Synthetic authorized evidence.', similarity=.9)]
    search = Mock(return_value=[] if outcome == 'empty' else sources)
    if outcome == 'retrieval_failure':
        search.side_effect = RuntimeError('Synthetic retrieval failure')
    monkeypatch.setattr(main, 'search_documents', search)
    provider = Mock()
    def answer(question, hits, **kwargs):
        assert kwargs == ({'conversation_context': context.prompt()} if path != '/ask' else {})
        if not hits:
            return 'No indexed sources are available to answer that question.'
        provider()
        usage = {'prompt_tokens': 3, 'completion_tokens': 2}
        if outcome != 'missing_cost':
            usage['cost'] = 0 if outcome == 'zero_cost' else .002
        observability.capture_llm_usage(usage, provider='openrouter')
        return 'Synthetic answer [1]'
    monkeypatch.setattr(main, 'answer_question', answer)
    monkeypatch.setattr(main.conversations, 'assert_owned', Mock())
    from app.conversation_context import ConversationContext, ContextTurn
    context = ConversationContext((ContextTurn('Earlier question?', 'Earlier answer [8]', frozenset({11})),))
    monkeypatch.setattr(main.conversations, 'load_context', Mock(return_value=context))
    monkeypatch.setattr(main.conversations, 'append_exchange', Mock(return_value=22))
    with TestClient(main.app) as client:
        response = client.post(path, json={'question': 'Synthetic wallet question?', 'top_k': 1})
    assert response.status_code == (503 if outcome == 'retrieval_failure' else 200)
    account = payments.summary(USER)
    if outcome in ('empty', 'retrieval_failure'):
        provider.assert_not_called()
        assert not state.usage and not state.ledger
        assert account['reserved'] == '0.00' and account['balance'] == '1'
    elif outcome == 'missing_cost':
        assert len(state.usage) == 1 and state.usage[0][-1] is None
        assert not state.ledger and account['reserved'] == '0.01'
        assert next(iter(state.reservations.values()))['status'] == 'unknown'
    else:
        assert len(state.ledger) == len(state.usage) == 1
        assert account['reserved'] == '0.00'
        assert Decimal(account['balance']) == Decimal('1') - (Decimal(0) if outcome == 'zero_cost' else Decimal('.002'))
