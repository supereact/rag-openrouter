from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app import answer_feedback as f
from app.security import Principal

OWNER = Principal(4, 1, 'reader', 'owner')
OUTSIDER = Principal(7, 2, 'reader', 'outsider')
ADMIN = Principal(1, 1, 'admin', 'admin')


class FakeConnection:
    def __init__(self, owned=True, sources=None):
        self.calls = []
        self.owned = owned
        self.sources = sources if sources is not None else [{'document_id': 11}]

    def execute(self, query, params=None):
        self.calls.append((query, params))
        return FakeCursor(self, query)


class FakeCursor:
    def __init__(self, conn, query):
        self.conn = conn
        self.query = query

    def fetchone(self):
        if 'SELECT m.sources' in self.query:
            return (self.conn.sources,) if self.conn.owned else None
        if 'RETURNING rating,reason,updated_at' in self.query:
            vals = self.conn.calls[-1][1]
            return (vals[4], vals[5], datetime(2026, 10, 16, tzinfo=timezone.utc))
        if 'SELECT id FROM conversations' in self.query:
            return (22,) if self.conn.owned else None
        if 'COUNT(*) FILTER' in self.query:
            return (3, 2, 1)
        return None

    def fetchall(self):
        if 'SELECT f.message_id' in self.query:
            return [(33, -1, 'incorrect', datetime(2026,10,16,tzinfo=timezone.utc))]
        if 'SELECT id,sources' in self.query:
            return [(33,self.conn.sources)]
        if 'COUNT(*) FILTER' in self.query:
            return [(datetime(2026,10,16,tzinfo=timezone.utc).date(),2,1)]
        if 'COALESCE(reason' in self.query:
            return [('incorrect',1)]
        if 'SELECT u.username' in self.query:
            return [('owner','incorrect',datetime(2026,10,16,tzinfo=timezone.utc))]
        return []


@pytest.fixture
def fake(monkeypatch):
    conn = FakeConnection()

    @contextmanager
    def connection():
        yield conn

    monkeypatch.setattr(f, 'db_connection', connection)
    monkeypatch.setattr(f, '_authorized_document_ids', lambda conn, principal, ids: ids)
    return conn


def test_owner_can_save_and_edit_feedback(fake):
    assert f.save_feedback(OWNER,22,33,'up')['rating'] == 'up'
    response = f.save_feedback(OWNER,22,33,'down','incorrect')
    assert response['reason'] == 'incorrect'
    calls = [params for query,params in fake.calls if 'INSERT INTO answer_feedback' in query]
    assert calls[0][:4] == (1,4,22,33)
    assert calls[1][4:] == (-1,'incorrect')


def test_reject_invalid_reason_without_database(fake):
    with pytest.raises(ValueError): f.save_feedback(OWNER,22,33,'up','incorrect')
    with pytest.raises(ValueError): f.save_feedback(OWNER,22,33,'down','secret')
    assert not fake.calls


def test_other_user_cannot_rate_message(fake):
    fake.owned=False
    with pytest.raises(HTTPException) as exc:
        f.save_feedback(OUTSIDER,22,33,'down')
    assert exc.value.status_code == 404
    assert not any('INSERT INTO answer_feedback' in query for query,_ in fake.calls)


def test_revoked_source_cannot_be_rated(fake,monkeypatch):
    monkeypatch.setattr(f, '_authorized_document_ids', lambda *a: set())
    with pytest.raises(HTTPException) as exc:
        f.save_feedback(OWNER,22,33,'up')
    assert exc.value.status_code == 404


def test_revoked_context_dependency_hides_feedback_and_prevents_rating(fake, monkeypatch):
    fake.sources = [{'document_id': 11, '_context_document_ids': [99]}]
    monkeypatch.setattr(f, '_authorized_document_ids', lambda conn, principal, ids: ids - {99})
    assert f.list_feedback(OWNER, 22) == []
    with pytest.raises(HTTPException) as error:
        f.save_feedback(OWNER, 22, 33, 'up')
    assert error.value.status_code == 404
    assert not any('INSERT INTO answer_feedback' in sql for sql, _ in fake.calls)


def test_malformed_source_dependencies_fail_closed(fake):
    fake.sources = [{'document_id': 11, '_context_document_ids': 'invalid'}]
    assert f.list_feedback(OWNER, 22) == []
    with pytest.raises(HTTPException):
        f.remove_feedback(OWNER, 22, 33)


def test_can_remove_own_rating(fake):
    f.remove_feedback(OWNER,22,33)
    assert any('DELETE FROM answer_feedback' in sql for sql,_ in fake.calls)


def test_list_only_owner_and_filter_revoked(fake,monkeypatch):
    assert f.list_feedback(OWNER,22)[0]['rating'] == 'down'
    monkeypatch.setattr(f,'_authorized_document_ids',lambda *a:set())
    assert f.list_feedback(OWNER,22) == []
    fake.owned=False
    with pytest.raises(HTTPException) as exc:
        f.list_feedback(OWNER,22)
    assert exc.value.status_code == 404


def test_admin_summary_is_tenant_scoped_and_no_chat_content(fake):
    result=f.admin_quality(ADMIN,7)
    assert result['all_time']=={'total':3,'up':2,'down':1}
    assert result['recent_downvotes'][0]['username']=='owner'
    assert 'answer' not in result['recent_downvotes'][0]
    for query,params in fake.calls:
        if 'FROM answer_feedback' in query or 'JOIN app_users' in query:
            assert params[0] == ADMIN.tenant_id


def test_admin_only_summary(fake):
    with pytest.raises(HTTPException) as exc:
        f.admin_quality(OWNER,7)
    assert exc.value.status_code == 403
    with pytest.raises(ValueError): f.admin_quality(ADMIN,365)
