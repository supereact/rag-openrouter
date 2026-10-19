"""Milestone 10.4: collections never bypass document or tenant permissions."""
from contextlib import contextmanager
import pytest

pytest.importorskip('psycopg')
pytest.importorskip('pgvector')

from fastapi import HTTPException
from app import knowledge_bases, services
from app.security import Principal

ADMIN = Principal(1, 10, 'admin', 'admin')
EDITOR = Principal(2, 10, 'editor', 'editor')
READER = Principal(3, 10, 'reader', 'reader')
OTHER = Principal(4, 11, 'admin', 'outside')


class Result:
    def __init__(self, one=None, many=None):
        self.one = one
        self.many = many or []

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.many


@contextmanager
def fake_db(calls, *, exists=True):
    class Conn:
        def execute(self, sql, args=()):
            calls.append((sql, args))
            if 'SELECT 1' in sql:
                return Result((1,) if exists else None)
            return Result()
    yield Conn()


def test_reader_cannot_create_knowledge_base():
    with pytest.raises(HTTPException) as exc:
        knowledge_bases.create_base(READER, 'Example')
    assert exc.value.status_code == 403


def test_foreign_collection_is_404(monkeypatch):
    calls = []
    monkeypatch.setattr(knowledge_bases, 'db_connection', lambda: fake_db(calls, exists=False))
    with pytest.raises(HTTPException) as exc:
        knowledge_bases.assert_tenant_collection(OTHER, 123)
    assert exc.value.status_code == 404
    assert calls[0][1] == (123, OTHER.tenant_id)


def test_membership_requires_owner_or_admin(monkeypatch):
    calls = []
    monkeypatch.setattr(knowledge_bases, 'db_connection', lambda: fake_db(calls, exists=False))
    with pytest.raises(HTTPException) as exc:
        knowledge_bases.add_document(EDITOR, 7, 13)
    assert exc.value.status_code == 404
    assert not any('INSERT INTO knowledge_base_documents' in s for s, _ in calls)


def test_document_removal_never_deletes_document(monkeypatch):
    calls = []
    monkeypatch.setattr(knowledge_bases, 'db_connection', lambda: fake_db(calls))
    knowledge_bases.remove_document(ADMIN, 7, 13)
    assert any('DELETE FROM knowledge_base_documents' in s for s, _ in calls)
    assert not any('DELETE FROM documents ' in s for s, _ in calls)


def test_collection_is_checked_before_embeddings(monkeypatch):
    monkeypatch.setattr(knowledge_bases, 'assert_tenant_collection',
                        lambda *_: (_ for _ in ()).throw(HTTPException(404, 'Not found')))
    monkeypatch.setattr(services, 'embed_many', lambda *_: (_ for _ in ()).throw(AssertionError('Embeddings called')))
    with pytest.raises(HTTPException) as exc:
        services.search_documents('What is a backup?', 5, mode='hybrid', principal=READER,
                                  knowledge_base_id=999)
    assert exc.value.status_code == 404


def test_hybrid_both_branches_use_collection_and_acl(monkeypatch):
    calls = []
    monkeypatch.setattr(knowledge_bases, 'assert_tenant_collection', lambda *_: None)
    monkeypatch.setattr(services, 'embed_many', lambda *_, **_kwargs: [[0.1] * 384])
    monkeypatch.setattr(services, '_audit', lambda *_a, **_kw: None)
    monkeypatch.setattr(services, 'db_connection', lambda: fake_db(calls))
    services.search_documents('VPN troubleshooting', 5, mode='hybrid', principal=READER,
                              knowledge_base_id=7)
    assert len(calls) == 2
    for sql, params in calls:
        assert 'document_acl' in sql
        assert 'knowledge_base_documents' in sql
        assert 'kbd.tenant_id=d.tenant_id' in sql
        assert params.count(7) == 1
        assert params.count(READER.tenant_id) >= 1


def test_all_documents_mode_has_no_collection_filter(monkeypatch):
    calls = []
    monkeypatch.setattr(services, 'embed_many', lambda *_, **_kwargs: [[0.1] * 384])
    monkeypatch.setattr(services, '_audit', lambda *_a, **_kw: None)
    monkeypatch.setattr(services, 'db_connection', lambda: fake_db(calls))
    services.search_documents('VPN troubleshooting', 5, mode='vector', principal=READER)
    assert len(calls) == 1
    assert 'knowledge_base_documents' not in calls[0][0]


def test_delete_collection_does_not_delete_documents(monkeypatch):
    calls = []
    monkeypatch.setattr(knowledge_bases, 'db_connection', lambda: fake_db(calls))
    knowledge_bases.delete_base(ADMIN, 7)
    assert any('DELETE FROM knowledge_bases' in sql for sql, _ in calls)
    assert not any('DELETE FROM documents ' in sql for sql, _ in calls)
