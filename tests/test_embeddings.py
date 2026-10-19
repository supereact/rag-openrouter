"""Model input contracts without loading or downloading model weights."""
from types import SimpleNamespace
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from app import embeddings


@pytest.mark.parametrize('query,prefix', [(True, 'query: '), (False, 'passage: ')])
def test_e5_roles_apply_to_all_languages(monkeypatch, query, prefix):
    seen = []
    def encode(texts, **kwargs):
        seen.append((texts, kwargs))
        return np.ones((len(texts), 384))
    monkeypatch.setattr(embeddings, 'get_model', lambda name: SimpleNamespace(encode=encode))
    vectors = embeddings.embed_many(['年假政策', 'Annual leave', '年假政策（繁體）'],
                                    query=query, model_name='intfloat/multilingual-e5-small')
    assert vectors.shape == (3, 384)
    assert seen[0][0] == [prefix + text for text in ['年假政策', 'Annual leave', '年假政策（繁體）']]
    assert seen[0][1]['normalize_embeddings'] is True


def test_configured_model_uses_query_prefix_without_explicit_override(monkeypatch):
    seen = []
    monkeypatch.setattr(embeddings, 'EMBEDDING_MODEL', 'intfloat/multilingual-e5-small')
    monkeypatch.setattr(embeddings, 'get_model', lambda: SimpleNamespace(
        encode=lambda texts, **_: seen.extend(texts) or np.ones((1, 384))))
    embeddings.embed_many(['年假'], query=True)
    assert seen == ['query: 年假']


def test_legacy_model_input_remains_unchanged(monkeypatch):
    seen = []
    monkeypatch.setattr(embeddings, 'EMBEDDING_MODEL', 'sentence-transformers/all-MiniLM-L6-v2')
    monkeypatch.setattr(embeddings, 'get_model', lambda: SimpleNamespace(
        encode=lambda texts, **_: seen.extend(texts) or np.ones((1, 384))))
    embeddings.embed_many(['original text'], query=True)
    assert seen == ['original text']


@pytest.mark.parametrize('vectors', [np.ones((1, 768)), np.ones((2, 384)),
                                      np.ones(384), np.full((1, 384), np.nan),
                                      np.full((1, 384), np.inf)])
def test_incompatible_or_invalid_vectors_are_rejected(monkeypatch, vectors):
    monkeypatch.setattr(embeddings, 'get_model', lambda: SimpleNamespace(encode=lambda *_a, **_kw: vectors))
    with pytest.raises(ValueError):
        embeddings.embed_many(['example'])


def test_empty_input_never_loads_model(monkeypatch):
    monkeypatch.setattr(embeddings, 'get_model', lambda: pytest.fail('Model loaded'))
    with pytest.raises(ValueError, match='empty'):
        embeddings.embed_many([])


def test_worker_loads_environment_before_importing_model_library():
    # A fresh interpreter reproduces the worker's first import without reading
    # the real .env, accessing the database, or importing model weights.
    program = '''
import builtins, os, sys
from types import SimpleNamespace
sys.modules['dotenv'] = SimpleNamespace(load_dotenv=lambda: os.environ.__setitem__('HF_HOME','test-cache'))
original_import = builtins.__import__
def checked_import(name, *args, **kwargs):
    if name == 'sentence_transformers':
        assert os.environ.get('HF_HOME') == 'test-cache', 'Model library imported before configuration'
        return SimpleNamespace(SentenceTransformer=object)
    return original_import(name, *args, **kwargs)
builtins.__import__ = checked_import
import app.embeddings
'''
    subprocess.run([sys.executable, '-c', program],
                   cwd=Path(__file__).resolve().parents[1], check=True,
                   capture_output=True, text=True)
