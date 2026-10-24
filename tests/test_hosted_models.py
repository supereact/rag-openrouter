"""Model bundles preserve selected identities and prohibit runtime downloads."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import hosted_runtime
from app.model_loading import load_cached_model
from scripts.prepare_model_bundle import prepare


def test_bundle_uses_local_files_and_never_falls_back_to_network(monkeypatch, tmp_path):
    (tmp_path / 'embedding').mkdir()
    (tmp_path / 'manifest.json').write_text(json.dumps({'version':1,'models':{'intfloat/multilingual-e5-small':'embedding'}}))
    monkeypatch.setenv('RAG_MODEL_BUNDLE', str(tmp_path))
    factory = Mock(return_value='model')
    assert load_cached_model(factory, 'intfloat/multilingual-e5-small') == 'model'
    factory.assert_called_once_with(str(tmp_path / 'embedding'), local_files_only=True)
    factory.reset_mock()
    with pytest.raises(ValueError, match='absent'):
        load_cached_model(factory, 'unknown-model')
    factory.assert_not_called()
    factory.side_effect = OSError('incomplete bundle')
    with pytest.raises(OSError):
        load_cached_model(factory, 'intfloat/multilingual-e5-small')
    assert factory.call_count == 1


@pytest.mark.parametrize('relative', ['..','../elsewhere','escape'])
def test_bundle_rejects_paths_outside_its_directory(monkeypatch, tmp_path, relative):
    root = tmp_path / 'bundle'; root.mkdir()
    (root / 'escape').symlink_to(tmp_path, target_is_directory=True)
    (root / 'manifest.json').write_text(json.dumps({'version':1,'models':{'model':relative}}))
    monkeypatch.setenv('RAG_MODEL_BUNDLE', str(root))
    factory = Mock()
    with pytest.raises(ValueError, match='directory'):
        load_cached_model(factory, 'model')
    factory.assert_not_called()


@pytest.fixture
def fake_models(monkeypatch):
    monkeypatch.delenv('RAG_MODEL_BUNDLE', raising=False)
    monkeypatch.setenv('HF_HUB_OFFLINE', '1')
    monkeypatch.setenv('TRANSFORMERS_OFFLINE', '1')
    monkeypatch.delenv('RAG_EMBEDDING_REVISION', raising=False)
    monkeypatch.delenv('RAG_RERANKER_REVISION', raising=False)
    monkeypatch.setitem(sys.modules, 'app.settings', SimpleNamespace(EMBEDDING_MODEL='embed',RERANKER_MODEL='rank'))
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(version=SimpleNamespace(cuda=None)))
    saved = []
    class Model:
        def __init__(self, name, **options):
            expected = {'device':'cpu','local_files_only':True}
            revision = os.getenv('RAG_EMBEDDING_REVISION' if name == 'embed' else 'RAG_RERANKER_REVISION')
            if revision:
                expected['revision'] = revision
            assert options == expected
            self.name = name
        def get_sentence_embedding_dimension(self):
            return 384
        def save(self, path, safe_serialization, create_model_card):
            assert safe_serialization
            assert not create_model_card
            Path(path).mkdir()
            (Path(path) / 'config.json').write_text('{}')
            saved.append(self.name)
    monkeypatch.setitem(sys.modules,'sentence_transformers',SimpleNamespace(SentenceTransformer=Model,CrossEncoder=Model))
    return saved


@pytest.mark.parametrize('mode, names', [('vector',['embed']),('hybrid',['embed']),('rerank',['embed','rank'])])
def test_packaging_selects_only_needed_models_and_refuses_overwrites(fake_models, monkeypatch, tmp_path, mode, names):
    monkeypatch.setenv('RAG_RETRIEVAL_MODE', mode)
    output = tmp_path / 'bundle'
    manifest = prepare(output, offline=True, require_cpu=True)
    assert list(manifest['models']) == names
    assert fake_models == names
    assert json.loads((output / 'manifest.json').read_text()) == manifest
    with pytest.raises(ValueError, match='already exists'):
        prepare(output)


def test_packaging_rejects_cuda_dependencies_before_creating_bundle(fake_models, monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(version=SimpleNamespace(cuda='synthetic')))
    output = tmp_path / 'bundle'
    with pytest.raises(ValueError, match='CPU-only'):
        prepare(output,require_cpu=True)
    assert not output.exists() and not fake_models


def test_release_build_requires_immutable_revisions_before_creating_output(fake_models, monkeypatch, tmp_path):
    monkeypatch.setenv('RAG_RETRIEVAL_MODE','rerank')
    with pytest.raises(ValueError, match='commit revisions'):
        prepare(tmp_path / 'bundle', require_revisions=True)
    assert not (tmp_path / 'bundle').exists() and not fake_models


def test_pinned_release_packages_both_selected_revisions(fake_models, monkeypatch, tmp_path):
    monkeypatch.setenv('RAG_RETRIEVAL_MODE','rerank')
    monkeypatch.setenv('RAG_EMBEDDING_REVISION','a'*40)
    monkeypatch.setenv('RAG_RERANKER_REVISION','b'*40)
    manifest = prepare(tmp_path / 'bundle', require_revisions=True)
    assert manifest['revisions'] == {'embed':'a'*40, 'rank':'b'*40}
    assert fake_models == ['embed','rank']


def test_worker_default_release_pins_match_runtime_reference_when_builder_omits_args():
    from dotenv import dotenv_values
    root=Path(__file__).resolve().parents[1]
    defaults={}
    for line in (root/'Dockerfile.vercel-worker').read_text().splitlines():
        if line.startswith('ARG '):
            key,separator,value=line[4:].partition('=')
            if separator:defaults[key]=value
    reference=dotenv_values(root/'deploy/.env.vercel.example',interpolate=False)
    for key in ('EMBEDDING_MODEL','RERANKER_MODEL','RAG_RETRIEVAL_MODE','RAG_EMBEDDING_REVISION','RAG_RERANKER_REVISION'):
        assert defaults[key] == reference[key]
    assert len(defaults['RAG_EMBEDDING_REVISION']) == len(defaults['RAG_RERANKER_REVISION']) == 40


def test_cli_reports_only_safe_configuration_messages(fake_models, monkeypatch, tmp_path, capsys):
    from scripts import prepare_model_bundle as bundle
    monkeypatch.setenv('RAG_RETRIEVAL_MODE','rerank')
    monkeypatch.setattr(sys,'argv',['prepare_model_bundle','--output',str(tmp_path/'bundle'),'--require-revisions'])
    assert bundle.main() == 1
    assert 'Pin selected models to full Hugging Face commit revisions' in capsys.readouterr().out
    def private_error(*args,**kwargs):
        raise ValueError('synthetic-private-provider-detail')
    monkeypatch.setattr(bundle,'prepare',private_error)
    assert bundle.main() == 1
    output=capsys.readouterr().out
    assert 'synthetic-private-provider-detail' not in output


def test_runtime_rejects_revision_drift_without_loading_model(monkeypatch, tmp_path):
    (tmp_path / 'embedding').mkdir()
    (tmp_path / 'manifest.json').write_text(json.dumps({'version':1,'models':{'model':'embedding'},'revisions':{'model':'a'*40}}))
    monkeypatch.setenv('RAG_MODEL_BUNDLE',str(tmp_path))
    monkeypatch.setenv('RAG_EMBEDDING_REVISION','b'*40)
    factory=Mock()
    with pytest.raises(ValueError,match='revision differs'):
        load_cached_model(factory,'model')
    factory.assert_not_called()


def test_hosted_entrypoints_require_remote_storage_and_built_models(monkeypatch, tmp_path):
    monkeypatch.setenv('RAG_STORAGE_BACKEND','local')
    with pytest.raises(RuntimeError, match='S3'):
        hosted_runtime.configure(tmp_path)
    monkeypatch.setenv('RAG_STORAGE_BACKEND','s3')
    for name in ('DATABASE_URL','AWS_ENDPOINT_URL_S3','AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_REGION'):
        monkeypatch.setenv(name,'synthetic')
    with pytest.raises(RuntimeError, match='bundle'):
        hosted_runtime.configure(tmp_path)
    bundle = tmp_path / 'model_bundle'; bundle.mkdir()
    (bundle / 'manifest.json').write_text('{}')
    for name in ('RAG_MODEL_BUNDLE','HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE','OMP_NUM_THREADS','TOKENIZERS_PARALLELISM','HF_HOME'):
        monkeypatch.setenv(name, '')
    hosted_runtime.configure(tmp_path)
    assert os.environ['RAG_MODEL_BUNDLE'] == str(bundle)
    assert os.environ['HF_HUB_OFFLINE'] == '1'
