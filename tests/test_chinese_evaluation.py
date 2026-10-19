"""Verify smoke-check plumbing; real model quality must be checked separately."""
import sys
from types import SimpleNamespace

import numpy as np

from scripts import evaluate_chinese


def test_smoke_check_uses_query_passage_roles_without_database(monkeypatch):
    calls = []
    def encode(texts, **kwargs):
        calls.append((texts, kwargs))
        if not kwargs.get('query'):
            return np.eye(4, 384)
        return np.asarray([np.eye(4, 384)[case[2]] for case in evaluate_chinese.CASES])
    monkeypatch.setattr(evaluate_chinese, 'embed_many', encode)
    report = evaluate_chinese.evaluate('test-model')
    assert report['passed'] == report['total'] == 6
    assert calls[0][1] == {'model_name': 'test-model'}
    assert calls[1][1] == {'query': True, 'model_name': 'test-model'}


def test_smoke_check_exposes_failed_rankings(monkeypatch):
    monkeypatch.setattr(evaluate_chinese, 'embed_many',
                        lambda texts, **_: np.ones((len(texts), 384)))
    report = evaluate_chinese.evaluate('test-model')
    assert report['passed'] < report['total']


def test_optional_reranker_scores_all_synthetic_pairs(monkeypatch):
    monkeypatch.setattr(evaluate_chinese, 'embed_many',
                        lambda texts, **_: np.ones((len(texts), 384)))
    calls = []
    class Reranker:
        def __init__(self, name):
            assert name == 'test-reranker'
        def predict(self, pairs, **_):
            index = len(calls)
            calls.append(pairs)
            return [int(i == evaluate_chinese.CASES[index][2]) for i in range(4)]
    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(CrossEncoder=Reranker))
    report = evaluate_chinese.evaluate('test-model', 'test-reranker')
    assert report['passed'] == 6
    assert len(calls) == 6
    assert all(len(pairs) == 4 for pairs in calls)
