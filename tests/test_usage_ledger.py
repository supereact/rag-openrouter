"""Per-user OpenRouter usage: accounting, UTC rollups, and tenant isolation."""
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app import usage_ledger
from app.security import Principal

ADMIN_A = Principal(1, 12, 'admin', 'admin-a')
ADMIN_B = Principal(4, 34, 'admin', 'admin-b')
READER = Principal(2, 12, 'reader', 'reader-a')


class FakeCursor:
    def __init__(self, sql, values):
        self.sql = sql
        self.values = values

    def fetchone(self):
        # one known-cost request, one request with cost unreported
        return (Decimal('0.000042'), Decimal('0.000012'), 2, 1, 1, 1)

    def fetchall(self):
        if 'FROM app_users u' in self.sql:
            return [(1, 'admin-a', 'admin@example.com', True,
                     Decimal('0.000042'), Decimal('0.000012'), 2, 1, 1, 1),
                    (2, 'reader-a', None, True,
                     Decimal('0'), Decimal('0'), 0, 0, 0, 0)]
        if 'utc_day' in self.sql:
            return [(date.today(), Decimal('0.000012'), 1, 1)]
        raise AssertionError('Unexpected query')


class FakeConn:
    def __init__(self):
        self.queries = []

    def execute(self, sql, args=()):
        self.queries.append((sql, args))
        return FakeCursor(sql, args)


@contextmanager
def connection(conn):
    yield conn


def test_persists_exact_cost_and_correct_principal(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(usage_ledger, 'db_connection', lambda: connection(conn))
    assert usage_ledger.record_openrouter_usage(ADMIN_A, 'google/small', {
        'provider_cost_credits': 0.000000123456,
        'prompt_tokens': 100,
        'completion_tokens': 40,
    })
    sql, values = conn.queries[0]
    assert 'INSERT INTO openrouter_usage_events' in sql
    assert values[1:4] == (12, 1, 'google/small')
    assert values[4:6] == (100, 40)
    assert values[6] == Decimal('0.000000123456')
    assert 'document' not in str(values).lower()


def test_unreported_cost_is_null_not_fabricated_zero(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(usage_ledger, 'db_connection', lambda: connection(conn))
    assert usage_ledger.record_openrouter_usage(READER, 'model', {
        'prompt_tokens': 2, 'completion_tokens': 0,
    })
    assert conn.queries[0][1][-1] is None
    assert not usage_ledger.record_openrouter_usage(READER, 'model', None)
    assert len(conn.queries) == 1


@pytest.mark.parametrize('value', [-0.01, float('nan'), '0.0001', True])
def test_invalid_cost_never_recorded_as_reported(monkeypatch, value):
    conn = FakeConn()
    monkeypatch.setattr(usage_ledger, 'db_connection', lambda: connection(conn))
    usage_ledger.record_openrouter_usage(ADMIN_A, 'model', {'prompt_tokens': 1, 'provider_cost_credits': value})
    assert conn.queries[0][1][-1] is None


def test_reader_forbidden_before_database_access(monkeypatch):
    monkeypatch.setattr(usage_ledger, 'db_connection', lambda: (_ for _ in ()).throw(AssertionError('query attempted')))
    with pytest.raises(HTTPException) as exc:
        usage_ledger.get_usage_dashboard(READER)
    assert exc.value.status_code == 403


def test_rollup_tenant_scope_and_daily_zero_fill(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(usage_ledger, 'db_connection', lambda: connection(conn))
    dashboard = usage_ledger.get_usage_dashboard(ADMIN_A, days=7)
    assert len(conn.queries) == 3
    assert all(q[1][-1] == 12 or (len(q[1]) == 2 and q[1][0] == 12) for q in conn.queries)
    assert dashboard['overall_credits'] == '0.000042'
    assert dashboard['week_credits'] == '0.000012'
    assert dashboard['requests'] == 2
    assert dashboard['cost_reported_requests'] == 1
    assert dashboard['users'][0]['username'] == 'admin-a'
    assert dashboard['users'][1]['username'] == 'reader-a'
    assert len(dashboard['daily']) == 7
    assert dashboard['daily'][0]['credits'] == '0' or dashboard['daily'][0]['credits'] == '0.000012'
    assert dashboard['daily'][-1]['date'] == datetime.now(timezone.utc).date().isoformat()
    assert dashboard['scope'] == 'tenant'


def test_different_tenant_uses_only_own_id(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(usage_ledger, 'db_connection', lambda: connection(conn))
    usage_ledger.get_usage_dashboard(ADMIN_B, days=30)
    assert all(q[1][-1] == 34 or (len(q[1]) == 2 and q[1][0] == 34) for q in conn.queries)


def test_unsupported_chart_window_rejected():
    with pytest.raises(ValueError):
        usage_ledger.get_usage_dashboard(ADMIN_A, days=365)
