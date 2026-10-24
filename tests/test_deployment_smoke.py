"""Pure-Python tests; no Docker, PostgreSQL or inference needed."""
from urllib.error import HTTPError, URLError
from urllib.request import Request

from scripts import smoke_deployment as smoke


def test_smoke_all_three_checks(monkeypatch, capsys):
    called = []

    def fake(url, *, expected, timeout=10):
        called.append((url, expected))
        return expected

    monkeypatch.setattr(smoke, 'probe', fake)
    assert smoke.run('http://127.0.0.1:8080/') is True
    assert called == [
        ('http://127.0.0.1:8080/', 200),
        ('http://127.0.0.1:8080/api/health', 200),
        ('http://127.0.0.1:8080/api/documents', 401),
    ]
    assert capsys.readouterr().out.count('PASS') == 3


def test_direct_api_smoke_uses_backend_paths_without_proxy(monkeypatch):
    called = []
    def probe(url, *, expected, timeout=10):
        called.append((url, expected))
        return expected
    monkeypatch.setattr(smoke, 'probe', probe)
    assert smoke.run('https://api.example.com/', api_only=True)
    assert called == [('https://api.example.com/health', 200), ('https://api.example.com/documents', 401)]


def test_smoke_fails_closed_when_auth_is_missing(monkeypatch):
    def fake(url, *, expected, timeout=10):
        return 200  # /api/documents is accidentally unprotected

    monkeypatch.setattr(smoke, 'probe', fake)
    assert smoke.run('http://127.0.0.1:8080') is False


def test_smoke_handles_network_failure(monkeypatch):
    def fail(url, *, expected, timeout=10):
        raise URLError('unreachable')

    monkeypatch.setattr(smoke, 'probe', fail)
    assert smoke.run('http://127.0.0.1:8080') is False


def test_proxy_has_loopback_binding_and_separate_database_network():
    from pathlib import Path
    contents = (Path(__file__).resolve().parents[1] / 'deploy/compose.yaml').read_text()
    assert '127.0.0.1:${RAG_WEB_PORT:-8080}:80' in contents
    assert 'name: rag_shared' in contents
    assert 'DATABASE_URL: ${RAG_DEPLOY_DATABASE_URL:' in contents
    assert 'condition: service_healthy' in contents
    assert 'ports:' not in contents.split('  worker:')[0]  # no direct API port
