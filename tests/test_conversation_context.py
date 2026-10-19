"""Follow-up context, provenance and authorization; no database/model calls."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import conversations, main, security, services, settings
from app.conversation_context import (
    ConversationContext, ContextTurn, MAX_TURNS, MAX_QUESTION_CHARS, MAX_ANSWER_CHARS,
    MAX_RETRIEVAL_CONTEXT_CHARS,
)
from app.schemas import SearchHit
from app.security import Principal

USER = Principal(5, 3, 'reader', 'reader')
HIT = SearchHit(source_number=1, document_id=22, title='Policy', chunk_index=0,
                content='Current authorized evidence', similarity=.8)


class Cursor:
    def __init__(self, rows=()): self.rows = list(rows)
    def fetchone(self): return self.rows[0] if self.rows else None
    def fetchall(self): return self.rows


class Database:
    def __init__(self, rows, allowed=(22,)):
        self.rows, self.allowed, self.calls = rows, allowed, []

    def execute(self, sql, args=()):
        self.calls.append((sql, args))
        if 'SELECT id,title,created_at,updated_at' in sql:
            stamp = datetime(2026, 10, 19, tzinfo=timezone.utc)
            return Cursor([(9, 'Policy', stamp, stamp)]) if args == (9, 5, 3) else Cursor()
        if 'SELECT question,answer,sources' in sql:
            assert args == (9, MAX_TURNS)
            return Cursor(self.rows[:MAX_TURNS])
        if 'SELECT d.id FROM documents d' in sql:
            assert args[1:1 + len(conversations.access_args(USER))] == conversations.access_args(USER)
            return Cursor([(doc,) for doc in self.allowed if doc in args[0]])
        if 'FROM (SELECT id,question,answer,sources,created_at' in sql:
            stamp = datetime(2026, 10, 19, tzinfo=timezone.utc)
            return Cursor([(i, *row, stamp) for i, row in enumerate(reversed(self.rows), 1)])
        if 'SELECT id FROM conversations' in sql:
            return Cursor([(9,)]) if args == (9, 5, 3) else Cursor()
        if 'INSERT INTO conversation_messages' in sql:
            self.saved = json.loads(args[-1])
            return Cursor([(8,)])
        return Cursor()


def bind(monkeypatch, rows, allowed=(22,)):
    db = Database(rows, allowed)
    @contextmanager
    def connection(): yield db
    monkeypatch.setattr(conversations, 'db_connection', connection)
    return db


def turn(question='What are the options?', answer='First A; second B [9].', **extra):
    return (question, answer, [{**HIT.model_dump(), **extra}])


def test_context_is_recent_chronological_bounded_and_owner_scoped(monkeypatch):
    db = bind(monkeypatch, [turn(f'{i}' * 1000, '答' * 3000) for i in range(6)])
    context = conversations.load_context(USER, 9)
    assert len(context.turns) == MAX_TURNS
    assert [t.question[0] for t in context.turns] == ['3', '2', '1', '0']
    assert all(len(t.question) == MAX_QUESTION_CHARS and len(t.answer) == MAX_ANSWER_CHARS
               for t in context.turns)
    assert context.document_ids == {22}
    assert db.calls[0][1] == (9, USER.user_id, USER.tenant_id)
    db.calls.clear()
    with pytest.raises(HTTPException) as error:
        conversations.load_context(Principal(99, 3, 'admin', 'other'), 9)
    assert error.value.status_code == 404 and len(db.calls) == 1


@pytest.mark.parametrize('sources', [None, {}, 'invalid JSON', [{'document_id': True}],
                                     [{'document_id': 22, '_context_document_ids': ['1']}], []])
def test_invalid_or_sourceless_latest_turn_cannot_enter_context(monkeypatch, sources):
    bind(monkeypatch, [('unavailable', 'Sensitive answer', sources), turn()])
    assert not conversations.load_context(USER, 9).turns


def test_revocation_is_a_context_boundary_and_checks_transitive_dependencies(monkeypatch):
    bind(monkeypatch, [turn('New topic'), turn(_context_document_ids=[99]), turn('Older topic')])
    context = conversations.load_context(USER, 9)
    assert [t.question for t in context.turns] == ['New topic']
    bind(monkeypatch, [turn(_context_document_ids=[99])])
    assert not conversations.load_context(USER, 9).turns


def test_knowledge_base_membership_filters_all_context_dependencies(monkeypatch):
    db = bind(monkeypatch, [turn()], allowed=())
    assert not conversations.load_context(USER, 9, knowledge_base_id=7).turns
    sql, args = db.calls[-1]
    assert 'knowledge_base_documents' in sql and 'kbd.tenant_id=d.tenant_id' in sql
    assert 'EXISTS' in sql and args[-1] == 7


def test_provenance_is_saved_without_becoming_a_current_source(monkeypatch):
    db = bind(monkeypatch, [])
    assert conversations.append_exchange(USER, 9, 'Follow-up', 'Answer [1]', [HIT],
                                         context_document_ids={99, 22}) == 8
    assert db.saved[0]['_context_document_ids'] == [22, 99]
    bind(monkeypatch, [('Follow-up', 'Sensitive derived answer', db.saved)])
    message = conversations.get_conversation(USER, 9)['messages'][0]
    assert message['redacted'] and message['sources'] == []
    bind(monkeypatch, [('Follow-up', 'Allowed answer [1]', db.saved)], allowed=(22, 99))
    message = conversations.get_conversation(USER, 9)['messages'][0]
    assert not message['redacted'] and message['sources'] == [HIT.model_dump()]


def test_context_query_retains_current_question_language_and_drops_old_citations():
    context = ConversationContext((
        ContextTurn('Earlier unrelated topic', 'Earlier answer', frozenset({11})),
        ContextTurn('Options?', '第二選項 [9] ' + 'x' * 2000, frozenset({22})),
    ))
    query = context.retrieval_query('第二個需要多少錢？')
    assert query.startswith('第二個需要多少錢？') and '第二選項' in query
    assert 'Earlier' not in query and '[9]' not in query
    assert len(query.split('Previous conversation topic:\n')[1]) <= MAX_RETRIEVAL_CONTEXT_CHARS
    assert '[9]' not in context.prompt()
    assert ConversationContext().retrieval_query('Original question?') == 'Original question?'


@pytest.fixture
def ask_client(monkeypatch):
    context = ConversationContext((ContextTurn('Which VPN options?', 'First A; second B [8].',
                                               frozenset({22})),))
    monkeypatch.setattr(main, 'warmup_local_models', lambda: None)
    monkeypatch.setattr(main.app, 'dependency_overrides', {security.require_principal: lambda: USER})
    monkeypatch.setattr(settings, 'LLM_PROVIDER', 'openrouter')
    monkeypatch.setattr(settings, 'RAG_WALLET_ENFORCEMENT', 'false')
    calls = SimpleNamespace(context=context, owned=Mock(), load=Mock(return_value=context),
        reserve=Mock(return_value='hold'), release=Mock(), settle=Mock(), append=Mock(return_value=8),
        search=Mock(return_value=[HIT]), provider=Mock(return_value='B costs $10 [1].'))
    for name, value in [('assert_owned', calls.owned), ('load_context', calls.load), ('append_exchange', calls.append)]:
        monkeypatch.setattr(conversations, name, value)
    for name, value in [('reserve_request', calls.reserve), ('release_before_generation', calls.release),
                        ('settle_request', calls.settle)]:
        monkeypatch.setattr(main.credit_budgets, name, value)
    monkeypatch.setattr(main, 'search_documents', calls.search)
    monkeypatch.setattr(services, 'generate_grounded_answer', calls.provider)
    with TestClient(main.app) as client:
        yield client, calls


def test_follow_up_uses_context_for_fresh_scoped_search_and_one_paid_call(ask_client, monkeypatch):
    client, calls = ask_client
    monkeypatch.setattr(main.knowledge_bases, 'assert_tenant_collection', Mock())
    question = 'What does the second option cost?'
    response = client.post('/conversations/9/ask', json={'question': question, 'knowledge_base_id': 7})
    assert response.status_code == 200
    assert response.json()['question'] == question
    assert response.json()['sources'][0]['content'] == HIT.content
    calls.load.assert_called_once_with(USER, 9, 7)
    calls.search.assert_called_once_with(calls.context.retrieval_query(question), 3,
                                         principal=USER, knowledge_base_id=7)
    calls.provider.assert_called_once()
    assert calls.provider.call_args.kwargs == {'conversation_context': calls.context.prompt()}
    assert 'Current authorized evidence' in calls.provider.call_args.args[1]
    calls.reserve.assert_called_once_with(USER)
    calls.settle.assert_called_once()
    calls.append.assert_called_once_with(USER, 9, question, response.json()['answer'], [HIT],
                                         context_document_ids={22})


@pytest.mark.parametrize('failure', ['empty', 'retrieval', 'generation', 'budget', 'ownership'])
def test_follow_up_preserves_reservation_and_failure_behavior(ask_client, failure):
    client, calls = ask_client
    if failure == 'empty': calls.search.return_value = []
    elif failure == 'retrieval': calls.search.side_effect = RuntimeError('Unavailable')
    elif failure == 'generation': calls.provider.side_effect = RuntimeError('Unavailable')
    elif failure == 'budget': calls.reserve.side_effect = HTTPException(429, 'Limit')
    else: calls.owned.side_effect = HTTPException(404, 'Conversation not found')
    response = client.post('/conversations/9/ask', json={'question': 'What about the second option?'})
    assert response.status_code == {'empty': 200, 'retrieval': 503, 'generation': 503,
                                    'budget': 429, 'ownership': 404}[failure]
    if failure in ('empty', 'retrieval'):
        calls.release.assert_called_once_with('hold', USER)
        calls.provider.assert_not_called()
        calls.settle.assert_not_called()
    elif failure == 'generation':
        calls.settle.assert_called_once()
        calls.release.assert_not_called()
    else:
        calls.search.assert_not_called()
        calls.provider.assert_not_called()
        calls.settle.assert_not_called()
    if failure == 'ownership': calls.load.assert_not_called()
    if failure != 'empty': calls.append.assert_not_called()


def test_standalone_ask_does_not_load_or_use_saved_context(ask_client):
    client, calls = ask_client
    assert client.post('/ask', json={'question': 'Standalone question?'}).status_code == 200
    calls.load.assert_not_called()
    calls.search.assert_called_once_with('Standalone question?', 3, principal=USER)
    assert calls.provider.call_args.kwargs == {}
