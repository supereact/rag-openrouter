"""Local 384-dimensional embedding model; first use downloads model weights."""
from functools import lru_cache
from dotenv import load_dotenv

import numpy as np
from sentence_transformers import SentenceTransformer

from app.settings import EMBEDDING_MODEL

load_dotenv()

@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL)


def embed_many(texts: list[str]) -> np.ndarray:
    if not texts:
        raise ValueError("Cannot embed an empty list")
    vectors = get_model().encode(
        texts, normalize_embeddings=True, convert_to_numpy=True,
        show_progress_bar=False,
    )
    if vectors.shape[1] != 384:
        raise ValueError(
            f"Expected 384-dimensional embeddings, got {vectors.shape[1]}. "
            "Changing embedding models requires changing the database schema and reindexing."
        )
    return vectors
