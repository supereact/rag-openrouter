"""Reuse cached model files before allowing Hugging Face update/download checks."""
from collections.abc import Callable
import errno
import logging
import os
from typing import TypeVar

Model = TypeVar('Model')
logger = logging.getLogger(__name__)


def load_cached_model(factory: Callable[..., Model], model_name: str) -> Model:
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
