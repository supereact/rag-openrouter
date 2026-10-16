"""Unit tests for credit reservation, parsing, isolation and fail-closed behavior."""
from contextlib import contextmanager
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import HTTPException

from app import credit_budgets as budget
from app.security import Principal

ADMIN = Principal(1, 10, 'admin', 'admin')
READER = Principal(2, 10, 'reader', 'reader')
OTHER = Principal(3, 11, 'admin', 'outside')


class Cursor:
    def __init__(self, row=None):
        self.row = row
    def fetchone(self):
        return self.row
    def fetchall(self):
        return self.row


class FakeConn:
    def __init__(self, tenant=None, user=None, totals=None, existing=(1,)):
        self.tenant = tenant
        self.user = user
        self.totals = totals or (Decimal(0),)*4
        self.existing = existing
        self.log = []
        self.reservations = {}
        self.event_inserts = 0
    def execute(self, sql, args=()):
        self.log.append((sql,args))
        if 'SELECT pg_advisory_xact_lock' in sql: return Cursor()
        if 'FROM tenant_credit_budgets WHERE tenant_id=' in sql: return Cursor(self.tenant)
        if 'FROM user_credit_budgets WHERE tenant_id=' in sql: return Cursor(self.user)
        if 'SELECT\n          COALESCE' in sql: return Cursor(self.totals)
        if 'INSERT INTO credit_reservations' in sql:
            self.reservations[args[0]] = 'reserved'
            return Cursor()
        if 'SELECT status FROM credit_reservations' in sql:
            return Cursor((self.reservations.get(args[0]),) if args[0] in self.reservations and args[1] == 10 and args[2] == 2 else None)
        if "UPDATE credit_reservations SET status='released'" in sql:
            if args[0] in self.reservations and args[1:] == (10,2):
                self.reservations[args[0]] = 'released'
            return Cursor()
        if 'UPDATE credit_reservations SET status' in sql:
            self.reservations[args[2]] = args[0]
            return Cursor()
        if 'INSERT INTO openrouter_usage_events' in sql:
            self.event_inserts += 1
            return Cursor()
        if 'SELECT 1 FROM app_users' in sql:
            return Cursor(self.existing)
        if 'INSERT INTO tenant_credit_budgets' in sql or 'INSERT INTO user_credit_budgets' in sql: return Cursor()
        raise AssertionError('Unexpected SQL: '+sql)


@contextmanager
def connection(conn):
    yield conn


def inject(monkeypatch, conn):
    monkeypatch.setattr(budget, 'db_connection', lambda: connection(conn))


def test_money_validation():
    assert budget.parse_credits('0.0000001') == Decimal('0.0000001')
    assert budget.parse_credits('0') == 0
    assert budget.parse_credits(None) is None
    for value in ('NaN', '-1', 'Infinity', '1000001', '0.1234567890123', 'abc'):
        with pytest.raises(ValueError): budget.parse_credits(value)
    with pytest.raises(ValueError): budget.parse_credits('0', positive=True)


def test_unlimited_existing_behavior(monkeypatch):
    conn = FakeConn()
    inject(monkeypatch, conn)
    assert budget.reserve_request(READER) is None
    assert not conn.reservations
    assert conn.log[0][1] == (READER.tenant_id,)


def test_rejects_tenant_budget_before_openrouter(monkeypatch):
    conn = FakeConn(tenant=(Decimal('0.01'), False, Decimal('0.01')),
                    totals=(Decimal('0.004'),Decimal('0'),Decimal('0'),Decimal('0')))
    inject(monkeypatch, conn)
    with pytest.raises(HTTPException) as e:
        budget.reserve_request(READER)
    assert e.value.status_code == 429
    assert not conn.reservations


def test_per_user_limit_includes_unknown_and_other_holds(monkeypatch):
    conn = FakeConn(tenant=(None,False,Decimal('0.01')),
                    user=(Decimal('0.02'),False),
                    totals=(Decimal('.01'),Decimal('.012'),Decimal('.01'),Decimal('.005')))
    inject(monkeypatch, conn)
    with pytest.raises(HTTPException) as e:
        budget.reserve_request(READER)
    assert e.value.status_code == 429


def test_tenant_paused_without_limit_blocks(monkeypatch):
    conn = FakeConn(tenant=(None,True,Decimal('0.01')))
    inject(monkeypatch, conn)
    with pytest.raises(HTTPException): budget.reserve_request(READER)


def test_successful_reservation_settlement_is_idempotent(monkeypatch):
    conn = FakeConn(tenant=(Decimal('2'),False,Decimal('0.01')))
    inject(monkeypatch,conn)
    rid = budget.reserve_request(READER)
    assert isinstance(rid, UUID)
    assert budget.settle_request(rid, READER, 'test/model',
        {'prompt_tokens':10,'completion_tokens':4,'provider_cost_credits':0.000123}) == 'settled'
    assert conn.event_inserts == 1
    assert budget.settle_request(rid, READER, 'test/model',
        {'prompt_tokens':10,'completion_tokens':4,'provider_cost_credits':0.000123}) == 'settled'
    assert conn.event_inserts == 1
    assert conn.reservations[rid]=='settled'


@pytest.mark.parametrize('usage,expected_events', [
    (None, 0),
    ({}, 0),
    ({'prompt_tokens': 9}, 1),
])
def test_unreported_cost_keeps_hold(monkeypatch, usage, expected_events):
    conn = FakeConn(tenant=(Decimal('2'),False,Decimal('0.01')))
    inject(monkeypatch,conn)
    rid = budget.reserve_request(READER)
    assert budget.settle_request(rid, READER, 'test/model', usage)=='unknown'
    assert conn.reservations[rid]=='unknown'
    assert conn.event_inserts==expected_events


def test_cross_tenant_settlement_not_permitted(monkeypatch):
    conn = FakeConn(tenant=(Decimal('2'),False,Decimal('0.01')))
    inject(monkeypatch,conn)
    rid = budget.reserve_request(READER)
    with pytest.raises(RuntimeError): budget.settle_request(rid, OTHER, 'test', {'provider_cost_credits':0.01})
    assert conn.event_inserts == 0


def test_reader_cannot_update_budget_without_sql(monkeypatch):
    monkeypatch.setattr(budget, 'db_connection',lambda: (_ for _ in ()).throw(AssertionError('SQL should not run')))
    with pytest.raises(HTTPException) as e: budget.update_tenant_budget(READER,'1',False,'0.01')
    assert e.value.status_code == 403


def test_update_user_requires_tenant_match(monkeypatch):
    conn = FakeConn(existing=None)
    inject(monkeypatch,conn)
    with pytest.raises(HTTPException) as e:
        budget.update_user_budget(ADMIN, 999, '1', False)
    assert e.value.status_code == 404
    assert (999, ADMIN.tenant_id) in [args for sql,args in conn.log if 'SELECT 1 FROM app_users' in sql]


def test_retrieval_failure_releases_unused_reservation(monkeypatch):
    conn = FakeConn(tenant=(Decimal('2'),False,Decimal('0.01')))
    inject(monkeypatch,conn)
    rid = budget.reserve_request(READER)
    budget.release_before_generation(rid, READER)
    assert conn.reservations[rid]=='released'
    assert conn.event_inserts == 0
