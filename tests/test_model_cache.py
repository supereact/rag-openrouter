"""Cache reuse and cold-start behavior without model downloads or DB access."""
from unittest.mock import Mock
import errno

import pytest
import sentence_transformers

from app import embeddings, services
from app.model_loading import load_cached_model


def test_embedding_loader_prefers_cache_and_reuses_in_memory_model(monkeypatch):
    model = object()
    loader = Mock(return_value=model)
    monkeypatch.setattr(embeddings, 'SentenceTransformer', loader)
    embeddings.get_model.cache_clear()
    try:
        assert embeddings.get_model('test/embedding') is model
        assert embeddings.get_model('test/embedding') is model
        loader.assert_called_once_with('test/embedding', local_files_only=True)
    finally:
        embeddings.get_model.cache_clear()


def test_reranker_loader_prefers_cache_and_reuses_in_memory_model(monkeypatch):
    model = object()
    loader = Mock(return_value=model)
    monkeypatch.setattr(sentence_transformers, 'CrossEncoder', loader)
    services._get_reranker.cache_clear()
    try:
        assert services._get_reranker() is model
        assert services._get_reranker() is model
        loader.assert_called_once_with(services.RERANKER_MODEL, local_files_only=True)
    finally:
        services._get_reranker.cache_clear()


def test_cached_model_never_attempts_online_loading(caplog):
    model = object()
    factory = Mock(return_value=model)
    with caplog.at_level('INFO', logger='app.model_loading'):
        assert load_cached_model(factory, 'test/model') is model
    factory.assert_called_once_with('test/model', local_files_only=True)
    assert 'Loaded model from local cache' in caplog.text


def test_missing_cache_downloads_once_without_changing_model(monkeypatch):
    monkeypatch.delenv('HF_HUB_OFFLINE', raising=False)
    monkeypatch.delenv('TRANSFORMERS_OFFLINE', raising=False)
    model = object()
    factory = Mock(side_effect=[OSError('Synthetic cache miss'), model])
    assert load_cached_model(factory, 'test/requested-model') is model
    assert [call.args for call in factory.call_args_list] == [('test/requested-model',)] * 2
    assert [call.kwargs for call in factory.call_args_list] == [
        {'local_files_only': True}, {'local_files_only': False},
    ]


@pytest.mark.parametrize('variable,value', [
    ('HF_HUB_OFFLINE', '1'), ('HF_HUB_OFFLINE', 'true'),
    ('TRANSFORMERS_OFFLINE', ' YES '),
])
def test_offline_cache_miss_never_attempts_download(monkeypatch, variable, value):
    monkeypatch.setenv(variable, value)
    error = OSError('Synthetic cache miss')
    factory = Mock(side_effect=error)
    with pytest.raises(OSError) as failure:
        load_cached_model(factory, 'test/model')
    assert failure.value is error
    factory.assert_called_once_with('test/model', local_files_only=True)


@pytest.mark.parametrize('error', [
    ValueError('Synthetic invalid config'), RuntimeError('Synthetic invalid weights'),
    PermissionError('Synthetic unreadable cache'), OSError(errno.EIO, 'Synthetic I/O failure'),
])
def test_loading_errors_are_not_hidden_by_online_retry(monkeypatch, error):
    monkeypatch.delenv('HF_HUB_OFFLINE', raising=False)
    monkeypatch.delenv('TRANSFORMERS_OFFLINE', raising=False)
    factory = Mock(side_effect=error)
    with pytest.raises(type(error)) as failure:
        load_cached_model(factory, 'test/model')
    assert failure.value is error
    factory.assert_called_once_with('test/model', local_files_only=True)


def test_download_failure_propagates_without_further_retries(monkeypatch):
    monkeypatch.delenv('HF_HUB_OFFLINE', raising=False)
    monkeypatch.delenv('TRANSFORMERS_OFFLINE', raising=False)
    error = OSError('Synthetic download failure')
    factory = Mock(side_effect=[OSError('Synthetic cache miss'), error])
    with pytest.raises(OSError) as failure:
        load_cached_model(factory, 'test/model')
    assert failure.value is error
    assert factory.call_count == 2
