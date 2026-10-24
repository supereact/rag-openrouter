"""Select immutable bundled models for the optional hosted entrypoints only."""
import os
from pathlib import Path


def configure(root: Path) -> None:
    if os.getenv('RAG_STORAGE_BACKEND', '').strip().lower() != 's3':
        raise RuntimeError('Hosted runtime requires private S3 storage')
    required = ('DATABASE_URL', 'AWS_ENDPOINT_URL_S3', 'AWS_ACCESS_KEY_ID',
                'AWS_SECRET_ACCESS_KEY', 'AWS_REGION')
    if any(not os.getenv(key) for key in required):
        raise RuntimeError('Hosted database/storage configuration is incomplete')
    bundle = root.resolve() / 'model_bundle'
    if not (bundle / 'manifest.json').is_file():
        raise RuntimeError('Build the deployment model bundle before hosted startup')
    os.environ.update(RAG_MODEL_BUNDLE=str(bundle), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    os.environ.setdefault('HF_HOME', '/tmp/rag-model-runtime')
