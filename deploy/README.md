# Milestone 9.5 — Local deployment rehearsal

**Purpose:** Containerize the API, ingestion worker and React frontend while **reusing** the existing `enterprise-rag-postgres` container. This is a **localhost-only rehearsal**, not a security-reviewed public production deployment. It intentionally does not restart, replace or create PostgreSQL volumes.

## Prerequisites

- Docker Desktop, with the existing `enterprise-rag-postgres` container running
- Working Milestone 9.4 code and root `.env` containing provider credentials
- Your existing PostgreSQL schema is already migrated
- Enough disk space for Python, PyTorch and model weights (the **first build is large**)

**Stop the local FastAPI and Python ingestion worker processes first** to avoid competing consumers. You may keep the existing PostgreSQL container running; leave `docker-compose.yml` at the repository root untouched.

## Configure shared Docker network (once per container creation)

```sh
docker start enterprise-rag-postgres
docker network inspect rag_shared >/dev/null 2>&1 || docker network create rag_shared
docker network connect rag_shared enterprise-rag-postgres
```

If the last command reports that the endpoint is already connected, that's fine. This network attachment is lost if you **recreate** the database container; attach it again in that case. The Postgres port exposed at `127.0.0.1:5432` on the Mac is **not** accessible as `host.docker.internal:5432` from another container; the shared Docker network is why this approach works.

## Configure environment without committing secrets

```sh
cp deploy/.env.deploy.example deploy/.env.deploy
id -u    # put this number in RAG_UID
id -g    # put this number in RAG_GID
```

Edit `deploy/.env.deploy`: set `RAG_DEPLOY_DATABASE_URL` to the actual credentials of your existing `ragdb` database. Hostname is `enterprise-rag-postgres`, **not** `localhost`. Special characters in the password must be URL-encoded. This is distinct from the `DATABASE_URL` in the existing root `.env` used by macOS Python.

The Compose stack also reads the existing root `.env` for `OPENROUTER_API_KEY`, `RAG_RETRIEVAL_MODE`, etc. Avoid placing keys in source code. Do not upload `.env` files to chat or commit them.

```sh
mkdir -p .original_pdfs .ingestion_spool .model_cache
docker compose --env-file deploy/.env.deploy -f deploy/compose.yaml config --quiet
```

Existing original PDFs and staged uploads are bind-mounted to the SAME paths used by local Python. Containers run with `RAG_UID:RAG_GID` matching the host user to keep 0700/0600 files accessible. This is **not intended for multi-user or remotely exposed hosts**. Model cache lives under `.model_cache/` and can be large.

## Build and start (first build may be slow)

```sh
docker compose --env-file deploy/.env.deploy -f deploy/compose.yaml build
docker compose --env-file deploy/.env.deploy -f deploy/compose.yaml up -d
docker compose --env-file deploy/.env.deploy -f deploy/compose.yaml ps
docker compose --env-file deploy/.env.deploy -f deploy/compose.yaml logs -f api worker
```

Open **http://127.0.0.1:8080** and sign in with your existing API key. The browser contacts Nginx on port 8080; Nginx proxies `/api/` to the private API service. Neither the API nor PostgreSQL gets a new public port. `GET /api/health` should return 200 only after the warmed-up API can reach the existing database.

Run the no-secret smoke test **on your Mac**:

```sh
python3 scripts/smoke_deployment.py
python3 -m pytest tests/test_deployment_smoke.py -q
```

Verify an authorized account can see its documents, a different-tenant user cannot, a fresh PDF upload finishes via the worker, and an existing original PDF opens at a citation. The smoke test only checks connectivity and missing-key rejection; it **does not prove tenant isolation**.

## Diagnostics

```sh
docker compose --env-file deploy/.env.deploy -f deploy/compose.yaml ps
docker compose --env-file deploy/.env.deploy -f deploy/compose.yaml logs --tail=80 api
docker compose --env-file deploy/.env.deploy -f deploy/compose.yaml logs --tail=80 worker
docker inspect enterprise-rag-postgres --format '{{json .NetworkSettings.Networks}}'
```

- `could not translate host name enterprise-rag-postgres`: attach the Postgres container to `rag_shared`.
- `password authentication failed`: confirm the **container-specific** database URL in `deploy/.env.deploy`.
- Healthcheck stays `starting`: embedding/reranker weights may still be downloading; inspect API logs, disk space and HF cache permissions.
- File access errors: ensure `RAG_UID` / `RAG_GID` match `id -u` / `id -g`, and directories are writable by that user.
- `address already in use` for 8080: change `RAG_WEB_PORT`, then rerun the smoke test with `--url`.
- `worker` unhealthy jobs: use the existing `/ingestion-health` endpoint and **stop all workers** before invoking manual recovery scripts. Compose restart does not automatically reclaim `processing` jobs.

## Stop safely and rollback

```sh
docker compose --env-file deploy/.env.deploy -f deploy/compose.yaml down
```

This stops/removes only the **new** API/worker/web containers and private network. It **does not stop PostgreSQL** or remove its data volume. **Never run `down -v`** on the existing database Compose stack. After stopping the new stack, restart the original macOS FastAPI, worker and Vite services normally; their original `.env` is unchanged.

## Security and operational gaps before any public deployment

- Put an HTTPS reverse proxy or managed TLS in front of the application; do not expose port 8080 publicly as-is.
- Replace API-key-only user sign-in with an appropriate identity provider, add request rate limiting and secrets management.
- Configure PostgreSQL least-privilege accounts and row-level security, stronger upload/file protections, and monitoring across processes.
- Pin base image digests, Python dependency versions and frontend lockfile; set up image scanning and SBOMs.
- Manage migration/release processes, backup **both** PostgreSQL and `.original_pdfs`, and test restoring them together.
- Design object storage and durable queue recovery before running replicas: the current spool uses host-local files, and in-process metrics reset on restart.
