"""Reuse cached model files before allowing Hugging Face update/download checks."""
from collections.abc import Callable
import errno
import logging
import os
import json
from pathlib import Path
from typing import TypeVar

Model = TypeVar('Model')
logger = logging.getLogger(__name__)


def load_cached_model(factory: Callable[..., Model], model_name: str) -> Model:
    bundle = os.getenv('RAG_MODEL_BUNDLE', '')
    if bundle:
        # A hosted build ships precisely the configured models. Never download
        # a replacement or silently use another model when this bundle is wrong.
        root = Path(bundle).resolve()
        manifest = json.loads((root / 'manifest.json').read_text())
        if manifest.get('version') != 1:
            raise ValueError('Unsupported deployment model bundle')
        relative = manifest['models'].get(model_name)
        if not isinstance(relative, str):
            raise ValueError('Configured model is absent from the deployment bundle')
        revision_key = {'embedding': 'RAG_EMBEDDING_REVISION', 'reranker': 'RAG_RERANKER_REVISION'}.get(relative)
        expected = os.getenv(revision_key, '') if revision_key else ''
        if expected and manifest.get('revisions', {}).get(model_name) != expected:
            raise ValueError('Configured model revision differs from the deployment bundle')
        path = (root / relative).resolve()
        if path == root or not path.is_relative_to(root) or not path.is_dir():
            raise ValueError('Invalid deployment model directory')
        return factory(str(path), local_files_only=True)
    try:
        model = factory(model_name, local_files_only=True)
    except OSError as exc:
        offline = any(os.getenv(key, '').strip().upper() in {'1', 'TRUE', 'YES', 'ON'}
                      for key in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE'))
        # Missing model/config files can be fetched on first use. Filesystem
        # permission/I/O failures and explicit offline mode must remain failures.
        if offline or isinstance(exc, PermissionError) or exc.errno not in (None, errno.ENOENT):
            raise
        logger.info('Model not available locally; downloading required files for %s', model_name)
        return factory(model_name, local_files_only=False)
    logger.info('Loaded model from local cache: %s', model_name)
    return model
