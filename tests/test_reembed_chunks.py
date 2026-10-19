"""Model migration rehearsals against an in-memory transaction, never live data."""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
import sys

import numpy as np
import pytest

from app import embeddings
from scripts import reembed_chunks


def database(monkeypatch, rows):
    state = {'rows': deepcopy(rows), 'commits': 0, 'rollbacks': 0, 'sql': []}

    @contextmanager
    def connect():
        staged = deepcopy(state['rows'])
        class Connection:
            def execute(self, sql, params=()):
                state['sql'].append((sql, params))
                if 'count(DISTINCT' in sql:
                    return SimpleNamespace(fetchone=lambda: (len(staged), len({r['document_id'] for r in staged})))
                if 'count(*)' in sql:
                    return SimpleNamespace(fetchone=lambda: (len(staged),))
                if 'SELECT id,content' in sql:
                    values = [(r['id'], r['content']) for r in staged if r['id'] > params[0]][:params[1]]
                    return SimpleNamespace(fetchall=lambda: values)

            @contextmanager
            def cursor(self):
                yield self

            def executemany(self, sql, values):
                assert sql == 'UPDATE chunks SET embedding=%s WHERE id=%s'
                for vector, chunk_id in values:
                    next(r for r in staged if r['id'] == chunk_id)['embedding'] = vector.tolist()
        try:
            yield Connection()
        except Exception:
            state['rollbacks'] += 1
            raise
        else:
            state['rows'] = staged
            state['commits'] += 1
    monkeypatch.setattr(reembed_chunks, 'db_connection', connect)
    return state


@pytest.fixture
def rows():
    return [dict(id=i, document_id=i, content='年假政策', page_number=3,
                 embedding=[0.] * 384) for i in (1, 5, 12)]


def test_default_plan_is_read_only_and_never_loads_weights(monkeypatch, rows):
    state = database(monkeypatch, rows)
    monkeypatch.setattr(embeddings, 'embed_many', lambda *_a, **_kw: pytest.fail('Model loaded'))
    assert reembed_chunks.plan('target') == dict(model='target', chunks=3, documents=3,
                                               dimensions=384, applied=False)
    assert state['sql'][0][0] == 'SET TRANSACTION READ ONLY'
    assert state['rows'] == rows


def test_apply_batches_only_embeddings_preserving_ids_content_and_pages(monkeypatch, rows):
    state = database(monkeypatch, rows)
    seen = []
    def encode(texts, **kwargs):
        seen.append((texts, kwargs))
        if len(seen) == 1:
            assert not state['sql']  # Warm/check model before locking anything.
        return np.ones((len(texts), 384))
    monkeypatch.setattr(embeddings, 'embed_many', encode)
    result = reembed_chunks.apply('target', 3, batch_size=2)
    assert result['applied'] is True
    assert result['chunks'] == 3
    assert [len(texts) for texts, _ in seen] == [1, 2, 1]
    assert all(kwargs == {'model_name': 'target'} for _, kwargs in seen)
    assert state['commits'] == 1
    assert state['rollbacks'] == 0
    assert any('LOCK TABLE documents,chunks' in sql for sql, _ in state['sql'])
    for before, after in zip(rows, state['rows']):
        assert {k: v for k, v in after.items() if k != 'embedding'} == {k: v for k, v in before.items() if k != 'embedding'}
        assert after['embedding'] == [1.] * 384


def test_inference_failure_rolls_back_earlier_batches(monkeypatch, rows):
    state = database(monkeypatch, rows)
    calls = 0
    def encode(texts, **_):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError('Model failed on second document batch')
        return np.ones((len(texts), 384))
    monkeypatch.setattr(embeddings, 'embed_many', encode)
    with pytest.raises(RuntimeError):
        reembed_chunks.apply('target', 3, batch_size=2)
    assert state['rows'] == rows
    assert state['commits'] == 0
    assert state['rollbacks'] == 1


def test_changed_count_refuses_writes(monkeypatch, rows):
    state = database(monkeypatch, rows)
    monkeypatch.setattr(embeddings, 'embed_many', lambda texts, **_: np.ones((len(texts), 384)))
    with pytest.raises(ValueError, match='count changed'):
        reembed_chunks.apply('target', 4)
    assert state['rows'] == rows
    assert not any('SELECT id,content' in sql for sql, _ in state['sql'])


@pytest.mark.parametrize('flags', [[], ['--expected-chunks', '3'], ['--confirm-services-stopped']])
def test_apply_requires_reviewed_count_and_maintenance_confirmation(monkeypatch, flags):
    monkeypatch.setattr(sys, 'argv', ['reembed_chunks', '--apply', *flags])
    monkeypatch.setattr(reembed_chunks, 'db_connection', lambda: pytest.fail('Database accessed'))
    with pytest.raises(SystemExit) as error:
        reembed_chunks.main()
    assert error.value.code == 2


def test_cli_does_not_print_database_errors_or_document_text(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['reembed_chunks'])
    def fail(_):
        raise RuntimeError('Secret database connection or private document text')
    monkeypatch.setattr(reembed_chunks, 'plan', fail)
    assert reembed_chunks.main() == 1
    output = capsys.readouterr().out
    assert 'Secret' not in output
    assert 'RuntimeError' in output
