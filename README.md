# Enterprise RAG Knowledge Assistant — Local Starter

This is a **local learning prototype**, not an enterprise-ready application.
It demonstrates: document text → chunking → local embeddings → PostgreSQL/pgvector
→ cosine search → optional LLM response with numbered source excerpts.

**Do not upload confidential documents or expose the API to the public internet.**
This version has no authentication, multi-tenant isolation, document-level ACLs,
malware scanning, LLM citation validation, or production observability.

## Requirements

- Python 3.11 or 3.12 (64-bit recommended), Docker Desktop or Docker Engine + Compose
- Internet access on the first embedding run to download the pretrained model
- 4+ GB RAM recommended for a smooth local experiment
- Optional: an OpenRouter or OpenAI API key, a supported model, and billing for `/ask`

## 1. Unzip and start a terminal in this folder

On macOS/Linux, `cd enterprise-rag-starter`. On Windows, open a PowerShell terminal
in that folder. All commands below run from the folder containing `docker-compose.yml`.

## 2. Configure the environment

```bash
# macOS/Linux
cp .env.example .env

# Windows PowerShell
# Copy-Item .env.example .env
```

The example credentials are **local development only**.

## 3. Start PostgreSQL with pgvector

```bash
docker compose up -d
docker compose ps
```

## 4. Create a Python environment

```bash
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows PowerShell instead:
# .venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 5. Initialize schema and insert sample documents

```bash
python -m scripts.init_db
python -m scripts.seed
```

The first seed run downloads `sentence-transformers/all-MiniLM-L6-v2`.
It can take additional time. Rerunning seed is idempotent.

## 6. Start the API

```bash
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Then visit **http://127.0.0.1:8000/docs** and use Swagger's `Try it out`
buttons on `/health`, `/documents`, `/search`, and `/ask`.

### Sample `/search` request

```json
{
  "question": "My VPN login is failing. What should I check?",
  "top_k": 3
}
```

### Sample `/documents` request

```json
{
  "title": "New laptop onboarding",
  "text": "All new company laptops must enroll in device management before accessing internal services. The help desk verifies device identity and installs approved security updates."
}
```

## 7. Enable LLM responses through `/ask` (OpenRouter default)

1. Create an OpenRouter API key at https://openrouter.ai/settings/keys.
2. In `.env`, keep `LLM_PROVIDER=openrouter` and fill `OPENROUTER_API_KEY`.
3. Start with `OPENROUTER_MODEL=google/gemini-3.1-flash-lite`, or replace it
   with any currently available text model ID from https://openrouter.ai/models.
4. Restart the API process and call `/ask` with the same JSON as `/search`.

The OpenAI Python package is used to call OpenRouter's OpenAI-compatible **Chat
Completions** endpoint. The database, embeddings, and `/search` are unchanged.

To switch to the direct OpenAI API instead, set `LLM_PROVIDER=openai`, fill
`OPENAI_API_KEY`, choose an available `OPENAI_MODEL`, and restart the API. The
direct OpenAI branch uses the **Responses API** with `store=False`.

For the initial milestone **you do not need an LLM API key**. `/search` works
with local embeddings and pgvector only. Do not paste API keys into chat, code,
or git. Monitor model rates and credit usage.

**Security limitation:** Prompts include retrieved document excerpts, which
are sent to the chosen cloud provider. This prototype has no authentication,
access control, data classification, or machine-validated citations. Use public
or synthetic sample documentation only.


## 8. Explore the SQL

```bash
docker compose exec postgres psql -U raguser -d ragdb
```

Inside `psql`:

```sql
SELECT extversion FROM pg_extension WHERE extname='vector';
SELECT id, title FROM documents ORDER BY id;
SELECT id, document_id, chunk_index, LEFT(content,80) FROM chunks;
SELECT c.id, d.title, 1 - (c.embedding <=> (SELECT embedding FROM chunks ORDER BY id LIMIT 1)) AS similarity
FROM chunks c JOIN documents d ON d.id = c.document_id
ORDER BY c.embedding <=> (SELECT embedding FROM chunks ORDER BY id LIMIT 1)
LIMIT 5;
```

## 9. Run basic tests

```bash
python -m pytest -q
```

These are isolated unit tests. They do not assert that Docker, the embedding
model download, the DB connection, or the OpenRouter/OpenAI API work end to end.

## Troubleshooting

- **Connection refused:** Run `docker compose ps` and `docker compose logs postgres`.
- **Port 5432 already in use:** Change the host port in `docker-compose.yml`
  and in the `DATABASE_URL` inside `.env`.
- **pgvector missing:** Run `python -m scripts.init_db` before starting the API.
- **Model download error:** Check network/proxy access to Hugging Face.
- **`/ask` returns 503:** Check `LLM_PROVIDER`, its matching key and model ID in `.env`, or use `/search`.
- **Windows Python command:** Depending on installation, you may need `py -3.12`.

## What comes next

1. PDF ingestion and document structure; metadata / document versioning.
2. Retrieval evaluation (Recall@k), hybrid BM25 + vector, reranking.
3. Authentication, row-level security and document access control.
4. Observability, rate limiting, async jobs, safe file handling.
5. HNSW indexing and performance/load testing on realistic corpora.

## Official references

- https://github.com/pgvector/pgvector
- https://github.com/pgvector/pgvector-python
- https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
- https://fastapi.tiangolo.com/tutorial/first-steps/
- https://developers.openai.com/api/reference/python/resources/responses/methods/create
