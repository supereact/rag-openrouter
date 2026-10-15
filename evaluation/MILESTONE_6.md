# Milestone 6 — Hybrid retrieval and cross-encoder reranking

This update **does not modify existing documents, chunks, embedding vectors,
PDF page metadata, OpenRouter settings, or API routes**. By default `/search`
and `/ask` still use the original cosine vector-only retrieval method.

## New search modes

- `vector` (default): previous exact pgvector ranking.
- `hybrid`: vector top 40 + PostgreSQL English full-text top 40 combined
  using Reciprocal Rank Fusion (RRF, k=60), returning the final top K.
- `rerank`: hybrid top 40 re-ordered by the locally hosted
  `cross-encoder/ms-marco-MiniLM-L-6-v2` model, returning the final top K.

`SearchHit.similarity` **always remains cosine similarity**, even when hybrid
or reranker ordering differs. Do not interpret it as a reranker confidence score.
Full-text search uses PostgreSQL's `websearch_to_tsquery('english', ...)` and
`to_tsvector('english', content)`. English tokenization is not ideal for all
languages, URLs, or technical identifiers; hybrid is an option, not a guarantee
of improved ranking.

## Baseline / comparison

Run from the project root with your virtual environment active and original
PostgreSQL container running:

```bash
python -m pytest tests/test_retrieval.py tests/test_evaluation.py -v
python -m scripts.evaluate_rag --retriever vector --warmup --top-k 5 --output evaluation/vector-warm.json
python -m scripts.evaluate_rag --retriever hybrid --warmup --top-k 5 --output evaluation/hybrid-warm.json
python -m scripts.evaluate_rag --retriever rerank --warmup --top-k 5 --output evaluation/rerank-warm.json
```

**By default these commands make zero OpenRouter calls.** The reranker uses a
local cross-encoder, but downloads its weights from Hugging Face on first use
and can take significantly longer per query. `--warmup` runs an untimed query
before evaluation: use it for ALL modes when comparing latencies. It may also
trigger a model download. Run each mode multiple times if comparing tail
latency; 8 questions are inadequate for production P95 estimates.

`--answers` optionally calls your configured OpenRouter/OpenAI provider; it
can incur charges and transmit retrieved chunks.

## Enable a new mode in the running FastAPI server

Add just one line to your local `.env`:

```dotenv
RAG_RETRIEVAL_MODE=hybrid
```

Or use `RAG_RETRIEVAL_MODE=rerank` to activate cross-encoder reranking.
Restart Uvicorn after editing `.env`; endpoints and response format stay the
same. Remove the setting (or set `vector`) to roll back instantly.

For larger corpora, **optionally** create the nondestructive GIN index:

```bash
docker exec -i enterprise-rag-postgres psql -U raguser -d ragdb \
  < scripts/sql/create_fts_index.sql
```

Index creation may briefly consume resources/locks. The local dataset is
small enough that the index is unnecessary. The code runs with or without it.

## Inspect regressions

Compare `evidence_recall_at_k` and `evidence_mrr_at_k` between all modes with
the same evaluation dataset, `--top-k 5`, and warmup setting. The known NIST
incident-phases evidence was ranked 7 by vector search at Top-10; test whether
hybrid or rerank moves it into Top-5. Check the two VPN cases still retrieve
`Vpn Support` evidence. If hybrid is worse on your corpus, use `vector` mode.

## Security limitations

This remains a local development prototype with no authentication or
per-document access checks. Retrieval across sensitive documents is unsafe
until tenant/ACL filters are implemented inside both vector and keyword SQL.
