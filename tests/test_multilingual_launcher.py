"""Launch configuration is shared and applied before application imports."""
import os
from pathlib import Path
import sys

import pytest

from scripts import reembed_chunks, run_multilingual


@pytest.mark.parametrize('service,arguments,module', [
    ('api', ['--host', '127.0.0.1', '--port', '8000'], ['uvicorn', 'app.main:app']),
    ('worker', ['--poll-seconds', '3'], ['scripts.ingestion_worker']),
])
def test_both_services_share_models_and_forward_arguments(monkeypatch, service, arguments, module):
    for key in ('EMBEDDING_MODEL', 'RERANKER_MODEL', 'RAG_RETRIEVAL_MODE', 'HF_HOME', 'HF_HUB_OFFLINE'):
        monkeypatch.setenv(key, 'previous-value')
    monkeypatch.setenv('LLM_PROVIDER', 'unchanged-provider')
    seen = []
    monkeypatch.setattr(os, 'execv', lambda executable, args: seen.append((executable, args)))
    run_multilingual.main([service, *arguments])
    assert seen == [(sys.executable, [sys.executable, '-m', *module, *arguments])]
    assert os.environ['EMBEDDING_MODEL'] == reembed_chunks.DEFAULT_MODEL
    assert os.environ['RERANKER_MODEL'] == 'cross-encoder/mmarco-mMiniLMv2-L12-H384-v1'
    assert os.environ['RAG_RETRIEVAL_MODE'] == 'rerank'
    assert Path(os.environ['HF_HOME']) == Path(run_multilingual.__file__).resolve().parents[1] / '.model_cache'
    assert os.environ['HF_HUB_OFFLINE'] == '1'
    assert os.environ['LLM_PROVIDER'] == 'unchanged-provider'


def test_invalid_service_never_changes_configuration_or_starts_process(monkeypatch):
    monkeypatch.setenv('EMBEDDING_MODEL', 'previous-value')
    monkeypatch.setattr(os, 'execv', lambda *_: pytest.fail('Process started'))
    with pytest.raises(SystemExit) as error:
        run_multilingual.main(['unknown'])
    assert error.value.code == 2
    assert os.environ['EMBEDDING_MODEL'] == 'previous-value'
