"""Local 384-dimensional embedding model; first use downloads model weights."""
from functools import lru_cache

# Load .env before Hugging Face captures cache/offline settings at import time.
from app.settings import EMBEDDING_MODEL
from app.model_loading import load_cached_model

import numpy as np
from sentence_transformers import SentenceTransformer


@lru_cache(maxsize=2)
def get_model(model_name: str | None = None) -> SentenceTransformer:
    return load_cached_model(SentenceTransformer, model_name or EMBEDDING_MODEL)


def embed_many(texts: list[str], *, query: bool = False,
               model_name: str | None = None) -> np.ndarray:
    if not texts:
        raise ValueError("Cannot embed an empty list")
    name = model_name or EMBEDDING_MODEL
    # E5 requires these English prefixes even for non-English inputs.
    inputs = texts
    if name.startswith('intfloat/multilingual-e5'):
        prefix = 'query: ' if query else 'passage: '
        inputs = [prefix + text for text in texts]
    model = get_model(model_name) if model_name else get_model()
    vectors = model.encode(
        inputs, normalize_embeddings=True, convert_to_numpy=True,
        show_progress_bar=False,
    )
    if vectors.ndim != 2 or vectors.shape != (len(texts), 384):
        raise ValueError(
            f"Expected {len(texts)} embeddings with 384 dimensions, got {vectors.shape}. "
            "A different dimension requires a schema change; every model change requires re-embedding."
        )
    if not np.isfinite(vectors).all():
        raise ValueError('Embedding model returned non-finite values')
    return vectors
