# Milestone 7: Tenant-scoped API keys & private documents

> **Local security MVP, not production-certified.** Do not publish this service or load
> confidential company files until HTTPS, SSO/OIDC, database least-privilege/RLS,
> rate limiting, monitoring, upload malware scanning, and operational key rotation
> are configured. The local PostgreSQL account is currently the development superuser.

## Changes

- `Authorization: Bearer rag_...` required for all knowledge API endpoints
  (`/health` stays public). API key hashes are stored; raw keys are printed only once.
- Users have a tenant and one of three roles: `admin`, `editor`, `reader`.
- New documents are private to their owner; tenant admins can read/write tenant docs.
- Explicit read grants let the owner or tenant admin share with a same-tenant user.
- Both vector and keyword SQL filter on tenant + owner/grants **before** candidate
  retrieval. Cross-encoder and OpenRouter only receive filtered context.
- Upload, PDF reindex, delete, and sharing enforce write/ownership privileges.
- Audit events record actions and IDs, not question contents or API keys.
- Existing document IDs, chunks, embeddings, page numbers, and OpenRouter config stay unchanged.

## Before you apply

1. Stop FastAPI and any ingestion scripts; back up `ragdb`:

   ```bash
   mkdir -p backups
   docker exec enterprise-rag-postgres pg_dump -U raguser -d ragdb -Fc \
     > backups/ragdb-pre-m7.dump
   docker exec -i enterprise-rag-postgres pg_restore --list < backups/ragdb-pre-m7.dump
   ```

2. Check your patch from the project directory: `git apply --check enterprise-rag-m7-security.patch`.
3. Apply it: `git apply enterprise-rag-m7-security.patch`.
4. Run `python -m scripts.migrate_security` **once before restarting FastAPI**.
   Re-running is safe. Existing documents become owned by user `local/admin`.
5. Create an admin key (printed once; don't paste it in chat):

   ```bash
   python -m scripts.create_api_key --tenant local --user admin --role admin
   ```

6. Add the printed key to your untracked `.env`:

   ```ini
   RAG_ADMIN_API_KEY=rag_your_generated_key_here
   RAG_RETRIEVAL_MODE=rerank
   ```

   Retain your existing `DATABASE_URL`, OpenRouter key, embeddings, etc.
7. Run tests: `python -m pytest tests/ -q`.
8. Start FastAPI: `python -m uvicorn app.main:app --reload --host 127.0.0.1`.

## Swagger tests

Open `http://127.0.0.1:8000/docs`, click **Authorize**, and paste your admin
API key. Swagger's HTTP bearer scheme sends `Authorization: Bearer <key>`.

- `GET /documents`: view local tenant documents, including the NIST PDF (`id=11`
  in your current database). No existing data should disappear.
- `POST /search` (NIST question): expect only accessible sources.
- `POST /ask`: your existing OpenRouter generation should work.
- `POST /documents/upload`: index your sample Markdown file.
- `POST /documents/{id}/reindex-pdf`: use an owned PDF and its exact filename.

## Test permissions with a separate user

```bash
python -m scripts.create_api_key --tenant local --user analyst --role reader
python -m scripts.create_api_key --tenant exampleco --user analyst --role reader
```

Save those two keys separately. For each account, use Swagger **Authorize**:

- `local/analyst` initially sees **no documents** (they're owned by `local/admin`).
- `exampleco/analyst` sees no documents and cannot access `local` sources.
- Neither reader can upload, reindex, share, or delete (HTTP 403).

As admin, share the NIST PDF with the `local/analyst` user:

```http
POST /documents/11/share
Authorization: Bearer <admin-key>
Content-Type: application/json

{"username": "analyst"}
```

Now the local analyst may retrieve the PDF but **cannot** reindex or delete it.
The other tenant's analyst must still get zero private hits. The `11` in the
example is the document ID from your database; replace if necessary.

## Tenant and write rules

| Action | Admin | Editor | Reader |
|---|---|---|---|
| Search/ask visible docs | Yes | Yes | Yes |
| Create/upload docs | Yes | Yes | No |
| Share own docs | Yes | Yes | No |
| Reindex/delete own docs | Yes | Yes | No |
| Read other private docs | Yes (same tenant) | Only with grant | Only with grant |
| Read other tenant docs | No | No | No |

API keys are server-generated with `secrets.token_urlsafe(32)`. The database
stores SHA-256 digests, not the raw API keys. To revoke a key in this learning
setup, identify the user with your trusted local operator CLI or database admin;
for example, to revoke **all keys** of the disposable test reader:

```sql
UPDATE api_keys SET revoked_at=now()
WHERE user_id=(SELECT u.id FROM app_users u JOIN tenants t ON t.id=u.tenant_id
               WHERE t.slug='exampleco' AND u.username='analyst')
  AND revoked_at IS NULL;
```

Never revoke the admin key until another admin key has been confirmed working.

## Developer scripts and regression evaluation

`python -m scripts.evaluate_rag --retriever rerank --warmup --top-k 5`
uses the key from `RAG_ADMIN_API_KEY` in your local `.env`. It runs under the
`local/admin` identity, preserving access to the pre-existing evaluation corpus.
`python -m scripts.seed` and `python -m scripts.reindex_samples --confirm`
require the same admin key. New documents created by those scripts are owned
by that admin. Do not run reindex scripts against production documents.

## Current limitations

- **No browser session login, user passwords or OIDC**: keys are a learning-friendly
  gateway authentication mechanism, not a complete enterprise identity solution.
- **Application authorization, not PostgreSQL RLS**: the current development DB
  user can bypass tenant filters. Production should use least privilege and RLS.
- **No request rate limiting, virus scanning, sandboxing, or reverse-proxy upload cap**.
- **No encryption-at-rest or managed secrets lifecycle** configured here.
- **No cryptographic binding of OpenRouter to tenant**. Documents sent to the LLM
  are authorized by the application but subject to provider privacy terms.
- **No page-aware ACL**: permission is currently assigned per document.
- **No ACL revoke endpoint yet**: a local DB admin can remove a grant from
  `document_acl`; self-service ACL management is a later improvement.
- **Not safe for internet exposure**. Bind Uvicorn to `127.0.0.1` for testing.
