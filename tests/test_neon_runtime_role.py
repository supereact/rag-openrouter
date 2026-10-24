"""Runtime-role setup refuses unsafe roles and never reveals passwords."""
from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from scripts import neon_runtime_role as role


@pytest.fixture
def database(monkeypatch, tmp_path):
    path = tmp_path / '.env.neon'
    path.write_text('DATABASE_URL=postgresql://owner:synthetic@ep-test-pooler.aws.neon.tech/db?sslmode=require\n')
    monkeypatch.setattr(role, 'environment', lambda *args, **kwargs: {'DATABASE_URL': 'synthetic-owner-url'})
    connection = Mock()
    @contextmanager
    def connect(*args, **kwargs):
        yield connection
    monkeypatch.setattr(role.psycopg, 'connect', connect)
    return path, connection


def test_preview_never_creates_role_or_updates_configuration(database):
    path, connection = database
    connection.execute.return_value.fetchone.return_value = None
    before = path.read_bytes()
    role.configure(path)
    assert path.read_bytes() == before
    assert connection.execute.call_count == 1
    assert connection.execute.call_args.args[0].startswith('SELECT')


@pytest.mark.parametrize('flags,membership', [((True, False, False, False), False),
    ((False, False, False, False), True)])
def test_elevated_role_is_rejected_without_rotation(database, flags, membership):
    path, connection = database
    connection.execute.return_value.fetchone.side_effect = [flags, (membership,)]
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match='elevated'):
        role.configure(path, apply=True)
    assert path.read_bytes() == before
    assert all(call.args[0].startswith('SELECT') for call in connection.execute.call_args_list)


def test_existing_role_requires_its_current_credentials(database):
    path, connection = database
    connection.execute.return_value.fetchone.side_effect = [(False, False, False, False), (False,)]
    with pytest.raises(RuntimeError, match='without rotating'):
        role.configure(path, apply=True)


def test_new_runtime_url_keeps_pooler_tls_and_owner_configuration(database, monkeypatch, capsys):
    path, connection = database
    path.write_text(path.read_text() + 'DATABASE_URL_UNPOOLED=synthetic-owner-url\n')
    connection.execute.return_value.fetchone.side_effect = [None, ('db',), ('owner',)]
    monkeypatch.setattr(role.secrets, 'token_urlsafe', lambda _: 'synthetic-private-password')
    role.configure(path, apply=True)
    values = role.dotenv_values(path)
    assert values['DATABASE_URL'] == 'postgresql://rag_app:synthetic-private-password@ep-test-pooler.aws.neon.tech/db?sslmode=require'
    assert values['DATABASE_URL_UNPOOLED'] == 'synthetic-owner-url'
    assert 'synthetic-private-password' not in capsys.readouterr().out
    assert path.stat().st_mode & 0o777 == 0o600
