"""Explicit cloud configuration must never fall back to the local database."""
import pytest

from scripts.run_neon import environment


@pytest.fixture
def config(tmp_path):
    path = tmp_path / '.env.neon'
    path.write_text('''DATABASE_URL=postgresql://app:synthetic@ep-test-pooler.c-1.aws.neon.tech/ragdb?sslmode=require
DATABASE_URL_UNPOOLED=postgresql://owner:synthetic@ep-test.c-1.aws.neon.tech/ragdb?sslmode=require
AWS_ENDPOINT_URL_S3=https://br-test.storage.c-1.aws.neon.tech
AWS_ACCESS_KEY_ID=synthetic-access
AWS_SECRET_ACCESS_KEY=synthetic-secret
AWS_REGION=us-east-2
''')
    return path


def test_explicit_neon_file_overrides_local_database_and_storage(config, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://local/private')
    monkeypatch.setenv('RAG_STORAGE_BACKEND', 'local')
    result = environment(config)
    assert '-pooler.' in result['DATABASE_URL']
    assert result['RAG_STORAGE_BACKEND'] == 's3'
    assert result['RAG_ENV_FILE'] == str(config.resolve())
    assert '-pooler.' not in environment(config, direct=True)['DATABASE_URL']


@pytest.mark.parametrize('url', ['postgresql://user:secret@localhost/ragdb?sslmode=require',
    'postgresql://user:secret@ep-test.aws.neon.tech/ragdb?sslmode=disable', '',
    'postgresql://user:secret@neon.tech.attacker.test/ragdb?sslmode=require'])
def test_missing_or_non_neon_configuration_fails_closed(config, url):
    lines = config.read_text().splitlines()
    lines[0] = 'DATABASE_URL=' + url
    config.write_text('\n'.join(lines))
    with pytest.raises(ValueError, match='explicit TLS Neon'):
        environment(config)


def test_migrations_reject_pooled_connection(config):
    config.write_text(config.read_text().replace('ep-test.c-1', 'ep-test-pooler.c-1'))
    with pytest.raises(ValueError, match='not the pooler'):
        environment(config, direct=True)


def test_missing_cloud_storage_credentials_never_use_local_credentials(config, monkeypatch):
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'local-secret')
    config.write_text(config.read_text().replace('AWS_SECRET_ACCESS_KEY=synthetic-secret', ''))
    with pytest.raises(ValueError, match='missing object-storage'):
        environment(config)
