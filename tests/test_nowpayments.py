"""Adapter and additive migration checks without provider or database connections."""
from contextlib import contextmanager
import json
from unittest.mock import Mock
from urllib.error import URLError

import pytest
from fastapi import HTTPException

from app import nowpayments, settings
from scripts import migrate_credits


@pytest.mark.parametrize('mode,host', [('sandbox', 'api-sandbox.nowpayments.io'), ('live', 'api.nowpayments.io')])
def test_adapter_fixed_hosts_and_safe_credentials(monkeypatch, mode, host):
    monkeypatch.setattr(settings, 'NOWPAYMENTS_API_KEY', 'synthetic-live')
    monkeypatch.setattr(settings, 'NOWPAYMENTS_SANDBOX_API_KEY', 'synthetic-sandbox')
    response = Mock()
    response.read.return_value = b'{"payment_id": 123}'
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(nowpayments, 'build_opener', lambda *args: opener)
    assert nowpayments.api_request(mode, 'POST', '/payment', {'price_amount': '10.55'}) == {'payment_id': 123}
    request = opener.open.call_args.args[0]
    assert request.full_url == f'https://{host}/v1/payment'
    assert request.get_header('X-api-key') == f'synthetic-{mode}'
    assert json.loads(request.data) == {'price_amount': '10.55'}
    with pytest.raises(ValueError):
        nowpayments.api_request(mode, 'GET', '/payment/../../evil')
    assert nowpayments.NoRedirects().redirect_request(None, None, 302, '', {}, 'https://other.example') is None


def test_adapter_error_does_not_leak_secrets_and_does_not_retry(monkeypatch):
    monkeypatch.setattr(settings, 'NOWPAYMENTS_SANDBOX_API_KEY', 'synthetic-private-key')
    opener = Mock()
    opener.open.side_effect = URLError('synthetic-private-key')
    monkeypatch.setattr(nowpayments, 'build_opener', lambda *args: opener)
    with pytest.raises(HTTPException) as error:
        nowpayments.api_request('sandbox', 'POST', '/payment', {})
    assert error.value.status_code == 502
    assert 'synthetic-private-key' not in error.value.detail
    assert opener.open.call_count == 1


@pytest.mark.parametrize('url', ['http://rag.example', 'https://user:password@rag.example', 'https://rag.example?key=value', ''])
def test_callback_configuration_requires_https_origin_without_credentials(monkeypatch, url):
    monkeypatch.setattr(settings, 'RAG_PAYMENTS_CALLBACK_BASE_URL', url)
    with pytest.raises(HTTPException):
        nowpayments.callback_url('sandbox')


def test_migration_only_adds_empty_tables_and_indexes(monkeypatch):
    statements = []
    class Connection:
        def execute(self, sql):
            statements.append(' '.join(sql.split()).lower())
    @contextmanager
    def connect(*args, **kwargs):
        yield Connection()
    monkeypatch.setattr(migrate_credits.psycopg, 'connect', connect)
    monkeypatch.setattr(migrate_credits, '_database_url', lambda: 'unused-synthetic-dsn')
    migrate_credits.migrate()
    first = list(statements)
    migrate_credits.migrate()
    assert statements[len(first):] == first
    assert sum(sql.startswith('create table if not exists') for sql in first) == 5
    assert all(sql.startswith(('select pg_advisory_xact_lock', 'create table if not exists', 'create index if not exists', 'create unique index if not exists')) for sql in first)
    assert any('foreign key(user_id,tenant_id) references app_users(id,tenant_id)' in sql for sql in first)
    assert any('unique(order_id,kind)' in sql for sql in first)
