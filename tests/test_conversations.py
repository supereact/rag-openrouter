"""Storage permission/redaction tests with fake PostgreSQL responses."""
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from app import conversations
from app.security import Principal

USER = Principal(5, 3, 'reader', 'reader')


class Cursor:
    def __init__(self, rows=None): self.rows = rows or []
    def fetchone(self): return self.rows[0] if self.rows else None
    def fetchall(self): return self.rows


class FakeDb:
    def __init__(self): self.sql=[]; self.allow_sources=False
    def execute(self,sql,args=()):
        self.sql.append((sql,args))
        stamp = datetime(2026,10,16,tzinfo=timezone.utc)
        if 'FROM conversations WHERE id=' in sql and 'SELECT id,title' in sql:
            return Cursor([(9,'Security Notes',stamp,stamp)]) if args==(9,5,3) else Cursor()
        if 'FROM (SELECT id,question,answer,sources,created_at' in sql:
            return Cursor([(4,'Sensitive?', 'Secret text [1]',
                  [{'source_number':1,'document_id':22,'title':'secret.pdf','chunk_index':0,'content':'Secret excerpt','similarity':0.8,'page_number':1}],stamp)])
        if 'SELECT d.id FROM documents d' in sql:
            return Cursor([(22,)]) if self.allow_sources else Cursor()
        if 'DELETE FROM conversations' in sql:
            return Cursor([(9,)]) if args==(9,3,5) else Cursor()
        return Cursor()


def bind(monkeypatch, db):
    @contextmanager
    def connection(): yield db
    monkeypatch.setattr(conversations,'db_connection',connection)


def test_revoked_document_redacts_saved_answer_and_sources(monkeypatch):
    db=FakeDb();bind(monkeypatch,db)
    result=conversations.get_conversation(USER,9)
    msg=result['messages'][0]
    assert msg['redacted'] is True and msg['sources']==[]
    assert 'Secret' not in msg['answer']
    assert len(db.sql)==3
    assert db.sql[2][1][1:] == conversations.access_args(USER)


def test_authorized_document_keeps_original_citations(monkeypatch):
    db=FakeDb();db.allow_sources=True;bind(monkeypatch,db)
    msg=conversations.get_conversation(USER,9)['messages'][0]
    assert not msg['redacted']
    assert msg['sources'][0]['page_number']==1


def test_ownership_enforced_on_delete(monkeypatch):
    db=FakeDb();bind(monkeypatch,db)
    with pytest.raises(HTTPException) as exc:
        conversations.delete_conversation(USER,18)
    assert exc.value.status_code==404
    assert db.sql[0][1] == (18,3,5)


def test_invalid_title_rejected_before_database(monkeypatch):
    with pytest.raises(ValueError):
        conversations.create_conversation(USER,'   ')
    with pytest.raises(ValueError):
        conversations.rename_conversation(USER,9,'x'*121)
