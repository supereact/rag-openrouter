"""Preload local embedding and optional cross-encoder models at API startup.

OpenRouter remains remote and does not need local weight loading.
"""

import logging
import os

logger = logging.getLogger("uvicorn.error")


def warmup_local_models() -> None:
    """Load models and run a tiny inference before serving requests.

    The embedding model is always used for /search and /ask. The reranker is
    needed only when RAG_RETRIEVAL_MODE=rerank. No database or LLM calls occur.
    """
    # Lazy imports keep this module lightweight and make unit tests independent
    # of torch, PostgreSQL and Hugging Face dependencies.
    from app.embeddings import embed_many

    mode = os.getenv("RAG_RETRIEVAL_MODE", "vector").strip().lower()
    if mode not in ("vector", "hybrid", "rerank"):
        raise ValueError(f"Invalid RAG_RETRIEVAL_MODE: {mode!r}")

    logger.info("Preloading embedding model and warming up inference...")
    embed_many(["RAG application model startup warm-up"])
    logger.info("Embedding model ready")

    if mode == "rerank":
        from app.services import _get_reranker

        logger.info("Preloading reranker model and warming up inference...")
        _get_reranker().predict(
            [("What is RAG?", "Retrieval-augmented generation uses retrieved documents.")],
            show_progress_bar=False,
        )
        logger.info("Reranker model ready")

    logger.info("Local models ready; retrieval mode: %s", mode)
