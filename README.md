# Enterprise RAG Knowledge Assistant

A working document knowledge assistant with a FastAPI backend, PostgreSQL 17 +
pgvector, local Sentence Transformers models, OpenRouter answer generation, and a
React/TypeScript/Tailwind interface. An optional direct OpenAI provider is also
supported.

Upload PDF, Markdown, or TXT files; search authorized content; ask questions with
numbered, page-aware citations; and manage sharing, collections, saved
conversations, accounts, usage, budgets, and feedback.

This README consolidates the former `docs/*.md` milestone guides and describes
the checked-out implementation. Historical patch instructions are superseded:
use the current files and migration scripts. Neon database/private-storage setup
is described below, alongside the optional VPS configuration. The Vercel release
uses `rag.weichen.space` for the frontend and `api-rag.weichen.space` for the API.
Deployment checks do not constitute an independent security assessment.

## Contents

- [Architecture](#architecture)
- [Daily startup](#daily-startup)
- [Fresh installation and upgrades](#fresh-installation-and-upgrades)
- [Configuration](#configuration)
- [Using the application](#using-the-application)
- [Authentication and authorization](#authentication-and-authorization)
- [Document ingestion and PDF storage](#document-ingestion-and-pdf-storage)
- [Retrieval and multilingual support](#retrieval-and-multilingual-support)
- [Usage and credit budgets](#usage-and-credit-budgets)
- [Personal credits and USDT payments](#personal-credits-and-usdt-payments)
- [Saved conversations](#saved-conversations)
- [Live support](#live-support)
- [Knowledge bases](#knowledge-bases)
- [Answer feedback](#answer-feedback)
- [Audit log and observability](#audit-log-and-observability)
- [API reference](#api-reference)
- [Worker operations and recovery](#worker-operations-and-recovery)
- [Testing and evaluation](#testing-and-evaluation)
- [Optional Docker deployment rehearsal](#optional-docker-deployment-rehearsal)
- [Neon database and object storage](#neon-database-and-object-storage)
- [Production release](#production-release)
- [Backups and rollback](#backups-and-rollback)
- [Troubleshooting](#troubleshooting)
- [Current limitations and improvement areas](#current-limitations-and-improvement-areas)
- [Former milestone guides](#former-milestone-guides)

## Architecture

| Component | Responsibility | Main files |
| --- | --- | --- |
| FastAPI API | Authentication, ingestion endpoints, authorized retrieval, generation, administration | `app/main.py`, `app/schemas.py` |
| Retrieval and generation | Chunking, embeddings, vector/keyword search, fusion, reranking, provider calls | `app/chunking.py`, `app/embeddings.py`, `app/services.py`, `app/llm.py` |
| Security and accounts | Tenant principals, document ACLs, passwords, invitations, sessions, browser transport | `app/security.py`, `app/account_auth.py`, `app/browser_auth.py`, `app/document_access.py` |
| Ingestion worker | Claim queued files, revalidate uploader authorization, index, retry, finalize jobs | `scripts/ingestion_worker.py`, `app/ingestion_jobs.py` |
| Administration and history | Usage ledger, credit reservations, conversations, collections, feedback, audit and metrics | Modules under `app/` with matching names |
| PostgreSQL | Documents, chunks and 384-dimensional vectors, users, ACLs, jobs, sessions, accounting and history | `app/db.py`, `scripts/migrate_*.py` |
| Private filesystem | Original PDFs, staged uploads, downloaded model weights | `.original_pdfs/`, `.ingestion_spool/`, model cache |
| Optional private object storage | Neon originals and staged uploads, selected explicitly for cloud processes | `app/object_storage.py`, `neon.ts` |
| React frontend | URL navigation, assistant, PDF viewer, management tables and dashboards | `frontend/src/` |

An upload goes through validation, staging, a PostgreSQL-backed job, extraction,
page-aware chunking, local embedding, and database storage. The API and worker
are **separate processes**; neither Redis nor Celery is required.

A question passes authentication and, for OpenRouter, configured budget checks.
Retrieval applies tenant, document ACL, and optional collection filters in SQL
before reranking or sending excerpts to the provider. The provider generates an
answer with source numbers; the original PDF is fetched through an authorized
endpoint when requested.

Embeddings and reranking run locally. Generation sends the question and retrieved
excerpts to the configured remote provider. Review provider terms and your data
policy before using confidential material.

## Daily startup

For an existing installation, use the existing database, environment, model
configuration, and private storage. Do not repeat bootstrap, migrations, seeding,
or re-embedding simply to start the application.

From the project root, activate the virtual environment in **each Python
terminal**:

```bash
source .venv/bin/activate
```

Ensure your existing PostgreSQL instance is running. Inspect `docker compose ps`
or `docker ps` if it is containerized; do not create a replacement database or
reset volumes.

Start the API:

```bash
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Start the worker in a second terminal:

```bash
python -m scripts.ingestion_worker
```

Start React in a third terminal:

```bash
cd frontend
npm run dev
```

Open [the application](http://127.0.0.1:5173) and
[the API documentation](http://127.0.0.1:8000/docs).
The frontend development server uses port 5173 and proxies `/api` to port 8000.

FastAPI preloads the embedding model, and the reranker when rerank mode is
selected. The worker preloads its own embedding model. Wait for startup readiness
before uploading. Uvicorn's `--reload` restarts the API only; restart the worker
separately after backend, model, or ingestion configuration changes.

## Fresh installation and upgrades

### Requirements

- Python 3.12 is the project target; the existing setup also documents Python 3.11.
- PostgreSQL 17 with pgvector, either an existing installation or Docker Compose.
- Node.js 20.19+ or 22.12+ for the current Vite frontend.
- Enough RAM and disk for PostgreSQL, model weights, API, worker, and document
  processing. Four GB is a starting point for small experiments, not capacity
  guidance for large PDFs or concurrent workloads.
- Hugging Face access for uncached model downloads. Search does not require a
  paid embedding API or an LLM key.
- A configured OpenRouter or OpenAI key, supported model, and provider allowance
  for nonempty-source answer generation.

Commands below assume macOS/Linux and the project root
`enterprise-rag-openrouter`. On Windows, activate with
`.venv\Scripts\Activate.ps1`; use your installed Python 3.12 command.

### Environment and dependencies

Create a virtual environment only if needed:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

**Only when `.env` does not already exist**, copy `.env.example` to `.env`
and edit it locally. Preserve existing credentials, paths, and model choices.
The example database credentials are for local development only. Never commit
the real file or put provider secrets in frontend `VITE_*` variables.

For a **new local database**, review `docker-compose.yml`, confirm that its
ports and volume will not conflict with an existing installation, then run:

```bash
docker compose up -d
docker compose ps
```

For an existing database, use its actual connection settings in `DATABASE_URL`.
Do not assume a container name or replace an existing volume.

Install frontend dependencies separately:

```bash
cd frontend
npm ci
```

Return to the project root before Python commands.

### Schema initialization and migration order

These commands change the database. On an existing installation, review the
scripts and already-applied schema, obtain approval for the maintenance, take a
backup, and stop the API and **all** workers first. Migrations are designed to
be repeatable; they are not automatically run at API startup.

Use the single schema entrypoint. Its default is an offline preview with no
database connection. Applying changes requires owner/migration credentials:

```bash
python -m scripts.setup_database
# Approved fresh, empty database only:
python -m scripts.setup_database --apply
# Approved existing database, after backup and stopping API/workers:
python -m scripts.setup_database --apply --upgrade
```

The runner acquires a PostgreSQL advisory lock to prevent concurrent runners,
refuses a nonempty database without `--upgrade`, and runs the existing modules
in the table order below. Each module commits separately: a later failure does
not roll back earlier modules. Fix the cause and rerun the approved command;
never reset data to recover. Legacy ownership backfills still require review.
It does not seed demo data or start services. Add `--fts-index` to include the
existing optional keyword index. This is a migration runner, not a new schema.

| Script | Schema purpose and upgrade considerations |
| --- | --- |
| `init_db` | pgvector extension, documents, chunks, physical PDF page metadata and basic indexes. Requires sufficient database privileges. |
| `migrate_security` | Tenants, users, hashed API keys, document ownership/ACLs and audit events. Backfills legacy unowned documents to `local/admin`; replaces global content deduplication with tenant/owner-scoped deduplication. Review legacy ownership before upgrading. |
| `migrate_accounts` | Email/password/activation fields, expiring login sessions and invitation records. Existing API-key users need a password set separately. |
| `migrate_ingestion_jobs` | Upload jobs, attempts, retry availability, heartbeats and queue indexes; older rows receive default attempt/availability values. |
| `migrate_usage_ledger` | Persistent OpenRouter usage events with nullable provider costs. |
| `migrate_credit_budgets` | Tenant/user monthly policies and request reservations. |
| `migrate_starter_allowances` | One-time signup allowance policies. Creates an empty table; existing users, usage and reservations are unchanged. Required before starting this release. |
| `migrate_credits` | Empty individual wallets, USDT orders, credit ledger, holds and callback receipts; sandbox/live balances are separate. No existing account is funded or historical usage changed. |
| `migrate_conversations` | Private conversations and saved message/source snapshots. |
| `migrate_knowledge_bases` | Collections and memberships, with composite foreign keys enforcing tenant consistency. |
| `migrate_answer_feedback` | One current rating per saved assistant message, linked to its conversation. |
| `migrate_support` | Private support threads/messages with owner constraints and idempotency keys. Optional feature; no staff account is enabled by the migration. |

Do not apply old milestone patch files over the current code. A database upgrade
does not automatically reindex existing documents, reconstruct missing original
PDFs, or backfill historical provider usage.

### Bootstrap an administrator

After the security and account migrations, create the initial local admin API
key if you do not already have one:

```bash
python -m scripts.create_api_key --tenant local --user admin --role admin
```

The command creates missing tenant/user records, refuses a conflicting existing
role, and prints the raw key **once**. Store it privately. The database stores a
digest rather than the raw key. Never paste the key into source code, URLs, logs,
screenshots, or chat.

For email/password browser sign-in, set the account's email and password using
the interactive local operator command. Replace the example email:

```bash
python -m scripts.set_user_password --tenant local --user admin --email admin@example.com
```

The password is entered through a hidden prompt, not a command-line argument.
This updates the password and revokes existing password sessions; API keys remain
separate. Do not use it to overwrite an existing account casually.

Optionally store the operator API key as `RAG_ADMIN_API_KEY` in your private
environment for the seed, sample-reindex, and evaluation CLIs. It is not an
anonymous API authentication bypass and is never needed in the frontend.

For a fresh demo installation only, `python -m scripts.seed` ingests the four
sample TXT documents using that admin principal. It writes to the database,
loads/downloads the selected embedding model, and deduplicates repeated content
for that owner. It is not a required startup step. Follow [Daily startup](#daily-startup)
after setup.

## Configuration

Application settings are loaded from the process environment and `.env`.
Environment variables already exported by the shell can take precedence; use
consistent settings in API, worker, and maintenance terminals.

| Setting | Meaning |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection URL; required for database operations. URL-encode special characters in credentials. |
| `RAG_ENV_FILE` | Optional explicit settings file. An unavailable selected file fails rather than loading local `.env`. Use `scripts.run_neon` for isolated cloud configuration. |
| `RAG_STORAGE_BACKEND` | `local` by default; `s3` enables private Neon object storage. API and worker must use the same mode/database/buckets. |
| `RAG_DOCUMENTS_BUCKET`, `RAG_UPLOADS_BUCKET` | Separate private buckets, default `rag-documents` and `rag-uploads`. |
| `AWS_ENDPOINT_URL_S3`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Server-only Neon storage variables; required in S3 mode. Explicit HTTPS endpoint, SigV4 and path-style addressing. Never expose credentials in frontend variables. |
| `RAG_ALLOWED_ORIGINS` | Comma-separated exact frontend origins for credentialed CORS. Empty by default; production requires HTTPS, e.g. `https://app.example.com`. No wildcards. Local direct requests may use `http://localhost:5173`. |
| `VITE_API_BASE_URL` | Public frontend **build-time** backend URL, e.g. `https://api.example.com`. HTTPS required except HTTP loopback. Blank retains the existing local `/api` proxy. Set in Vercel and rebuild after changes; never put credentials here. |
| `VITE_CREDITS_ENABLED` | Frontend build switch; keep `false` for this release, alongside disabled backend payments. |
| `EMBEDDING_MODEL` | Default in code: `sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions. Must match every stored embedding. |
| `RERANKER_MODEL` | Default in code: `cross-encoder/ms-marco-MiniLM-L-6-v2`. Used in rerank mode. |
| `RAG_RETRIEVAL_MODE` | `vector`, `hybrid`, or `rerank`. Code fallback is `vector`; `.env.example` selects `rerank`. |
| `LLM_PROVIDER` | `openrouter` by default, or `openai`. |
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` | Private provider key and an available OpenRouter text model ID. |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Used only for the direct OpenAI provider. |
| `RAG_ADMIN_API_KEY` | Optional private operator credential for local maintenance/evaluation scripts. |
| `RAG_INGEST_SPOOL` | Private staged-upload directory; defaults to project `.ingestion_spool`. Must agree between API and worker. |
| `RAG_PDF_STORAGE_DIR` | Private original-PDF directory; defaults to project `.original_pdfs`. Must agree between API and worker. |
| `HF_HOME` | Hugging Face cache root. Set a stable path, such as `.model_cache` when starting from the project root. Otherwise library defaults apply. |
| `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE` | A true value prevents download fallback; the complete selected models must already be cached. |
| `RAG_OBSERVABILITY_ENABLED` | Defaults to enabled. False stops new in-process measurements; restarting clears previous process-local metrics. |
| `RAG_PAYMENTS_MODE` | `disabled` (default), `sandbox`, or `live`. |
| `RAG_WALLET_ENFORCEMENT` | `false` by default. `true` requires live payment mode and OpenRouter, and adds individual prepaid checks to existing monthly limits. |
| `RAG_PAYMENTS_CALLBACK_BASE_URL` | Public HTTPS base URL, including `/api` when callbacks pass through the web proxy. Never inferred from a client-supplied Host header. |
| `NOWPAYMENTS_SANDBOX_API_KEY`, `NOWPAYMENTS_SANDBOX_IPN_SECRET` | Private sandbox provider credentials. |
| `NOWPAYMENTS_API_KEY`, `NOWPAYMENTS_IPN_SECRET` | Separate live credentials; configure after merchant eligibility is confirmed. |
| `RAG_SUPPORT_STAFF_USER_IDS` | Empty by default. Comma-separated global user IDs of designated central support administrators; only active admin accounts qualify. Restart the API after changing it. |

Choose model IDs and provider permissions appropriate to your account; example
IDs are configuration examples, not guarantees of availability or pricing.
Restart processes after configuration changes.

OpenRouter uses the OpenAI-compatible Chat Completions API. The direct OpenAI
branch uses the Responses API with `store=False`. Local retrieval is unchanged
by the generation provider. OpenRouter usage accounting and credit budgets do
not apply to the direct OpenAI branch.

### Cached models and startup messages

Normal API and worker commands first try `local_files_only=True`. A complete
cache is loaded without online update checks. A missing cache can trigger a
download when offline flags are not enabled. Keep the cache across restarts and
make sure both processes use the same model/cache configuration.

Each process must still load cached weights into RAM/GPU on every start.
`Loading weights` progress and `using mps` on Apple Silicon describe loading and
device selection; they do not by themselves indicate a download. The
`Loaded model from local cache` log confirms a successful local load. Reloading
the API or starting a second worker adds another model load and memory cost.

## Using the application

The sidebar/mobile navigation uses real links and browser History APIs. Direct
URLs, refresh, and Back/Forward work. Internal return destinations survive
sign-in and are checked against application routes. Admin-only destinations are
checked in navigation and route handling, with backend authorization remaining
authoritative. Unknown paths show a not-found view. `/` serves the existing
public landing page.

The application is constrained to the viewport: navigation and page headers
remain stationary while each page's content scrolls. Navigating between pages
preserves the mounted chat state; browser refresh restores the login session and
allows saved conversations to be reopened, but does not preserve all unsaved UI
state.

| Route | Purpose |
| --- | --- |
| `/login` | Password sign-in, public/private-workspace registration, invitation registration, or API-key connection. |
| `/assistant` | Ask questions, inspect numbered citations, view PDFs, manage saved conversations, choose collection scope and rate answers. |
| `/documents` | Searchable library of indexed documents and queued, processing, or failed uploads; upload files and manage permitted documents. |
| `/knowledge-bases` | Browse/manage collections of existing authorized documents. |
| `/credits` | Currently disabled: hidden from navigation, direct links show an unavailable message, no payment reads are started. |
| `/support` | Private user support chats; explicitly designated staff receive a central inbox across tenants. |
| `/account` | Change your password, review your active password sessions, and revoke individual or other sessions. Available to every signed-in role. |
| `/dashboard` | Admin overview, OpenRouter usage, monthly budgets, and feedback analytics. |
| `/users` | Admin user table and invitations. |
| `/audit-log` | Admin searchable/filterable tenant audit history. |

Documents has **Title, Date, Status, Assigned, Remove** columns, title/filename
search, status and file-type filters, and 20/50/100-row server-side pagination.
Filters and pagination are stored in URL query parameters. Newest items appear
first with deterministic tie-breaking. Completed jobs resolve to indexed
documents without duplicate rows; completed-job history cannot resurrect a
deleted document. Admins see tenant-wide jobs; others see their own jobs plus
documents they are authorized to read.

The library polls in the background every 3.5 seconds while mounted, visible,
and online. It retains current content and sharing drafts, prevents overlapping
requests, and ignores obsolete responses. Ordinary refresh failures retain
content with a stale/error indication. A reporting/filter selection change
clears incompatible data; 401 signs out and 403 clears protected content.

**Assigned** means sharing recipients. Owners with writer privileges and tenant
admins can open the searchable multiselect access editor, grant/revoke multiple
users, save, or cancel. Owner/admin automatic access cannot be removed through
an ACL. Inactive accounts cannot receive new grants; existing grants can be
reviewed/removed. Other document viewers receive a neutral label rather than
recipient identities. Upload rows become assignable after indexing.

User Management has **Username, Email, Role, Status, Created, Actions**, with
username/email search, role/status filters and client-side pagination. It
preserves invitation creation, role updates, activation controls and session
revocation.

Dashboard overview, usage, budgets and feedback load independently. Refresh
actions are section-scoped and disabled while pending. Same-selection failures
retain stale content; reporting-period changes do not show previous-period
figures. Budget saves use the returned dashboard data directly, preserve other
unsaved edits, and avoid overlapping reads/saves.

## Authentication and authorization

### Sign-in, sessions and invitations

Password and invitation sign-ins use revocable, **12-hour** database sessions.
Browser sessions use a host-only `rag_browser_session` cookie with HttpOnly,
SameSite=Strict, and Secure outside loopback development. F5 restores the current
account and role without exposing a token in browser storage or URLs. Refresh
does not extend the expiry.

API-key connection remains memory-only in the browser, so reconnect after F5.
Bearer API-key and bearer password-session authentication remain supported for
API clients. User activation and current role are checked against the database.
Expiry, sign-out, deactivation, role changes, and administrator session revocation
invalidate password sessions. Session revocation is distinct from API-key
revocation; deactivation blocks both authentication forms.

Passwords use salted PBKDF2-HMAC-SHA256 with 600,000 iterations. New passwords
must contain 12–128 characters and at most 512 UTF-8 bytes. Public registration
without an invitation creates a new, isolated tenant with an **editor** account,
which can upload/search its documents but has no administrator privileges.
Clients cannot choose the tenant or role. Set `RAG_PUBLIC_REGISTRATION_ENABLED=false`
to disable this path; invitations still work. A supplied invalid invitation
never falls back to public signup. An admin can create a reader/editor invitation
bound to an email; it expires after 48 hours and can be used once. Codes are shown once and must
be delivered securely by the administrator; no email delivery service is built
in. Initial admin setup uses the operator CLI.

Every account registered after the starter-allowance migration receives a
**one-time $0.001 OpenRouter provider-cost allowance**, including invited accounts.
It is stored atomically with account creation and never renewed on sign-in or
month rollover. Existing users retain their current policies. All-time reported
usage and active/unknown reservations consume this allowance. New requests hold
up to the remaining allowance, allowing a trial smaller than the usual $0.01
reservation. Retrieval failures and empty-source answers release unused holds;
unknown provider costs retain them. Tenant/user monthly limits still apply.
This is a soft application guardrail: actual provider cost can exceed the hold,
after which further generation is blocked. It does not deposit money into
OpenRouter or guarantee a fixed number of answers. Use a separately capped
production provider key to bound total operator exposure. With purchases disabled,
an exhausted user must contact the operator; there is no automatic refill.

Document counts are **unlimited**, as requested. Existing 50 MiB/file,
PDF-page/type validation, writer roles and document permissions remain in force.
Signup attempts (successful or failed) share an atomic, per-process IP throttle
across both registration transports: eight attempts per 15 minutes. Production
also applies shared Nginx IP limits. Email verification, password recovery and
CAPTCHA are not implemented; public signup does not prove ownership of an email.

Cookie requests use `X-RAG-CSRF: 1`; cookie-authenticated writes and browser
session endpoints accept the backend's own origin or exact configured frontend
origins. Credentialed CORS permits only `RAG_ALLOWED_ORIGINS`, specified methods
and headers. Cross-site browser session requests remain blocked. Production
must use HTTPS custom domains under the **same registrable parent**, such as
`app.example.com` on Vercel and `api.example.com` on the VPS. These are different
origins but the same site, preserving the existing SameSite=Strict cookie.
An unrelated `project.vercel.app` hostname cannot support this cookie flow with
`api.example.com`; use the custom frontend domain for sign-in. Do not wildcard
preview origins or weaken cookies. The existing local Vite proxy preserves Host,
including port. HTTPS proxies must preserve Host and scheme through the trusted
proxy chain. All frontend fetches include credentials; session secrets remain
HttpOnly and never enter JavaScript storage.

Admin safeguards prevent self-deactivation/self-demotion and removal of the
last active admin. Deactivation preserves owned documents and history; it is
not account deletion or ownership transfer.

### Account security and session self-service

Open **Account** (`/account`) to manage your own credentials and sessions. This
uses the existing `app_users` and `login_sessions` tables: no migration or new
configuration is required. Ordinary users, tenant administrators, and designated
central support staff can only manage their own sessions through these endpoints.
Existing administrator controls remain separate.

The password form requires your current password, a different new password, and
matching confirmation in the UI. The existing 12–128-character / 512-UTF-8-byte
policy and salted password hashing apply. Initial passwords for API-key-only
accounts still require the operator setup described above; this is not a
forgotten-password reset flow. Incorrect current-password attempts return a form
error without signing out the current session, and a per-account, process-local
throttle limits repeated failures. Distributed throttling remains future work.

A successful password change atomically updates the hash, revokes **all password
sessions including the current one**, and records a metadata-only audit event.
Password-authenticated users then sign in again using the new password. API keys
are not revoked; an API-key connection remains active after the change. Login
locks the account before checking its password and issuing a session, so a
concurrent old-password login cannot create a valid session after revocation.
Personal mutations also recheck activation and the authenticating credential
inside their transaction, using tenant/account lock order compatible with admin
updates. An audit failure rolls back the credential/revocation changes.

Active-session reporting excludes expired/revoked rows, supports 20/50/100-row
pagination, and identifies the authenticating password session when applicable.
Only numeric session IDs, creation/expiry timestamps, and a current-session flag
are returned. Tokens, token hashes, password hashes, device names, IP addresses,
and user agents are not exposed. Device/location tracking is not implemented.
Session reporting uses a consistent read-only snapshot.

You can sign out a single session, including your own with confirmation. **Sign
out other sessions** preserves the current password session. When connected with
an API key, the action instead signs out all active password sessions while
keeping the API key valid. Revoking a current cookie session clears that cookie;
an explicitly authenticated bearer request never clears an unrelated browser
cookie. Ownership is enforced before any target session is changed; there is no
tenant-admin or central-support override in these self-service routes.

The page refreshes every 15 seconds while visible and online and on return from
hidden/offline states. Refreshes retain password drafts in component memory;
passwords are never placed in URLs, persistent browser storage, or validation
responses. Invalid security payloads receive generic validation errors to avoid
echoing secrets. Successful changes clear the form, obsolete account responses
are ignored, and mutation controls prevent duplicate submissions. An interrupted
password-change response can be uncertain: try signing in with the new password
before submitting again. Cookie writes retain the existing CSRF protections.

Implementation: `app/account_security.py` (ownership, transactions and audit),
`app/account_security_api.py` (typed routes and private validation),
`app/account_auth.py` (serialized login), and `frontend/src/AccountPanel.tsx`
(forms and session table), with navigation/client types wired through the
existing app. Regression coverage is in `tests/test_account_security.py` and
`frontend/src/AccountPanel.test.tsx`, plus existing authentication and app/API tests.
Automated checks use temporary database fixtures and provider-free tests; they
do not change a real user's password or revoke live sessions.

### Permission model

| Operation | Reader | Editor | Tenant admin |
| --- | --- | --- | --- |
| Read/search/ask/view original PDF | Owned or explicitly shared documents | Owned or explicitly shared documents | All documents in own tenant |
| Upload/create documents | No | Yes, owned by uploader | Yes |
| Reindex/share/revoke/delete document | No | Own documents only | Any document in own tenant |
| See sharing recipients | No | Own documents only | Any document in own tenant |
| Create/manage collections | Browse accessible collections | Create; manage own collections | Manage own tenant's collections |
| Add/remove collection documents | No | Must manage collection and own document | Own tenant only |
| Read saved conversations or rate answers | Own conversations only | Own conversations only | Own conversations only |
| Dashboard/users/audit/usage/budgets/metrics | No | No | Own tenant only |

New documents are private to their owner except for automatic same-tenant admin
access. An ACL grants read access, not management rights. Tenant boundaries
apply to vector and keyword candidate queries **before** reranking/provider
calls. Knowledge-base membership never grants access. Source downloads and
saved excerpts recheck authorization. Missing/unauthorized resources generally
return 404 to avoid leaking their existence; missing credentials return 401.

API keys are stored as digests. To revoke keys, a trusted database operator must
identify the exact tenant/user/key record and revoke the intended active keys;
there is no browser API-key management screen. Review the effect and preserve
an authorized admin access path. Never print raw tokens for debugging.

## Document ingestion and PDF storage

### Upload limits and multiple files

Writers can select multiple `.pdf`, `.md`, and `.txt` files. Each must be
nonempty and at most **50 MiB (50 × 1024 × 1024 bytes)**. Markdown/TXT must decode
as UTF-8 (a UTF-8 BOM is supported). PDFs must be readable, unencrypted, contain
extractable text, and have at most **1,000 physical pages**. Extracted content
must meet the minimum text validation; scanned/image-only files need external
OCR. There is no OCR pipeline here.

The asynchronous queue validates extension/size before staging; full extraction
and PDF page/text checks happen in the worker. A queued response is acceptance,
not successful indexing. The 1,000-page cap also applies to synchronous uploads
and PDF reindexing. Physical page numbering includes blank pages and is kept
for citations. Restart API and worker after ingestion code changes; previously
failed files require a new upload rather than automatic history modification.

The UI uploads one selected file per request, sequentially. A per-file error
does not stop later files; **Retry failed uploads** retries failed submissions.
Keep Documents open until submissions finish. Navigation stops remaining
submissions; already accepted jobs continue. File selections live in memory
and clear on refresh/sign-out. A submission retry does not itself requeue an
already accepted job that later failed processing.

Synchronous JSON ingestion accepts a title of 2–200 characters and text of
20–200,000 characters. File ingestion uses its own byte/page/text validation;
the JSON body text limit is not a separate total extracted-PDF character cap.

Content deduplication is tenant/owner-scoped. A repeat can return
`already_exists=true` with the existing document. Confirm destructive document
deletion and failed-upload removal separately. Queued/processing jobs cannot
be removed. Failed-job deletion locks/rechecks the row, requires its writer
owner or a same-tenant admin, and retains the record if staged-file cleanup
fails.

### Original PDFs and citations

Original bytes live privately under `RAG_PDF_STORAGE_DIR`, normally
`.original_pdfs/{document_id}.pdf`. API and worker must use the same location.
Never expose this directory through static hosting, Vite public assets, or
unauthenticated file URLs.

`GET /documents/{document_id}/original-pdf` requires authorized document access.
The browser fetches bytes with authentication, creates a temporary blob URL,
and opens the requested physical page in the viewer. No API key is embedded
in the PDF URL; the blob URL is revoked when the viewer closes.

Documents indexed before original-byte storage may be searchable without an
available original PDF. An authorized owner/admin can replace/reindex the PDF
using the matching filename while retaining its document ID; a duplicate PDF
upload can also repair missing stored bytes. Reindexing changes chunks/vectors
and must be treated as an intentional data change.

PostgreSQL transactions and filesystem writes are not one atomic transaction.
A crash can leave indexed text without original bytes. A database-only backup
does not back up original PDFs; see [Backups and rollback](#backups-and-rollback).

## Retrieval and multilingual support

### Retrieval modes

- **vector:** pgvector cosine similarity over authorized embeddings.
- **hybrid:** authorized vector candidates plus PostgreSQL full-text candidates,
  fused by reciprocal rank fusion.
- **rerank:** hybrid candidates followed by a local cross-encoder.

Hybrid/rerank candidate pools use `max(40, top_k × 5)` per branch; vector-only
retrieval requests `top_k` candidates. RRF uses `k=60`. Public search
inputs accept 3–2,000-character questions and `top_k` from 1 to 10 (default 3).
Returned similarity remains a cosine-similarity value; it is not a calibrated
answer-confidence score. Keyword matching uses PostgreSQL full-text search,
not a claim of BM25 scoring.

An optional full-text GIN index is supplied in
`scripts/sql/create_fts_index.sql`. Review database size, locking and maintenance
approval before applying it. The current local exact vector path does not imply
a production ANN index or tested large-corpus throughput.

### Chinese documents and questions

Han-containing text is chunked without requiring spaces, targeting 256
characters; long Latin words retain the caller's original character bound.
English-only chunking is unchanged. PDF page metadata and permissions remain
intact; Chinese image-only PDFs still need OCR.

For Chinese questions, the implicit default vector path adds literal keyword
candidates using bounded overlapping Han bigrams and Latin words. Explicit
`mode="vector"` calls stay vector-only. Terms are bounded to 64 and passed as SQL
parameters. Both candidate branches retain tenant, ACL and collection filters.
The literal branch scans authorized content without a new index; profile large
libraries. It does not provide synonym translation or conversion between
Simplified and Traditional scripts.

Generation instructions request the question's language/script and grounded
numbered citations. Empty-source Han questions receive a local Chinese response.
Actual multilingual quality depends on the models and corpus; test your own
authorized examples.

The English embedding/reranker **code defaults** remain for compatibility.
The supported multilingual configuration is:

```dotenv
EMBEDDING_MODEL=intfloat/multilingual-e5-small
RERANKER_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
RAG_RETRIEVAL_MODE=rerank
HF_HOME=.model_cache
```

E5 receives required `query: ` and `passage: ` prefixes automatically, including
for non-English text. Both the original and multilingual embedding choices use
384 dimensions. **Equal dimensions do not make their vector spaces compatible.**
Never change an existing corpus's embedding model without rebuilding all stored
vectors. The application does not automatically verify a database model version.

### Changing embedding models safely

For a fresh empty database, choose a compatible 384-dimensional model before
ingestion. For an existing corpus, obtain approval for a full embedding
replacement and use a maintenance window:

1. Evaluate the proposed model. The local synthetic commands below load public
   model weights and use six toy Chinese/English/cross-language queries; they
   access neither the database nor a generation provider.
2. Run the read-only re-embedding plan. It counts documents/chunks across all
   tenants without loading weights or printing document content.
3. Take an approved database backup and stop **both API and all workers**.
   Re-run the plan and review its current counts.
4. Apply using the reviewed chunk count as `N`. The command validates the
   target model before locking, rechecks the count under table locks, and
   updates all batches in one transaction. Failure rolls back the updates.
5. Configure both services with the same new embedding model, set the desired
   compatible reranker/mode, then restart. Do not run concurrent ingestion,
   reindexing, deletion, or old-model queries during the transition.

```bash
python -m scripts.evaluate_chinese
python -m scripts.evaluate_chinese --reranker-model cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
python -m scripts.reembed_chunks
# Only after approval, backup and stopping services; replace N with reviewed count:
python -m scripts.reembed_chunks --apply --expected-chunks N --confirm-services-stopped
```

The migration command defaults to multilingual E5 and supports an explicit
`--model`. It changes only `chunks.embedding`, across all tenants; document and
chunk IDs, text, physical pages, ACLs and conversation references remain.
It does not rechunk older Chinese documents. The services-stopped flag is an
operator assertion, not automatic process detection.

To roll back, stop services, re-embed with the previous `--model` and restore
the old configuration after approval, or restore a reviewed compatible backup.
Do not simply switch `.env` back while new-model vectors remain.

After a successful migration, the normal startup commands use the configuration
above. An optional launcher forces multilingual E5, the multilingual reranker,
rerank mode, the absolute project `.model_cache`, and offline loading:

```bash
.venv/bin/python -m scripts.run_multilingual api --host 127.0.0.1 --port 8000 --reload
.venv/bin/python -m scripts.run_multilingual worker
```

It preserves provider/authentication settings and forwards service arguments,
signals and exit codes without editing `.env`. It requires cached weights and
matching migrated vectors; it does not inspect the database model version.

## Usage and credit budgets

### Persistent OpenRouter usage

The admin dashboard reports this application's recorded OpenRouter usage by
tenant/user: tracked all-time totals, current UTC calendar week (Monday start),
and daily 7/30-day charts including today's partial UTC day. It records model,
input/output tokens and provider-reported cost when present, without prompts,
excerpts or raw provider payloads.

Unreported cost is stored as NULL and shown as **unreported**, never free usage.
Cost coverage helps explain incomplete totals. Decimal credit amounts are JSON
strings to preserve precision; graph rendering is approximate. This is neither
the full OpenRouter account balance nor authoritative provider billing. It has
no historical backfill, excludes other applications and direct OpenAI requests,
and can underreport if a ledger write fails.

### Monthly credit guardrails

Tenant admins set optional tenant/user monthly limits, pause policies, and a
per-request reservation (default `0.01` credits). A blank limit means unlimited;
zero blocks new budgeted generation. Windows start at 00:00 UTC on the first day
of the month.

Configured OpenRouter policies reserve allowance **before retrieval and
generation** using a per-tenant PostgreSQL transaction advisory lock. Concurrent
requests see pending reservations. Policy changes use the same locking model.
A blocked request returns 429 without contacting the provider; `/search`
remains available.

- Retrieval failure or empty sources: no provider generation occurs, the unused
  reservation is released, and no generation usage event is recorded.
- Attempted generation with a reported cost: usage settlement and reservation
  release are atomic.
- Attempted generation without reliable cost, including possible provider
  failure: retain an unknown-cost hold for review.
- Settlement failure: keep the hold rather than silently releasing allowance.

Before any budget policy is configured, the existing usage-ledger path operates
without reservations. Direct OpenAI generation bypasses these OpenRouter-only
policies. Reservations count against their creation month.

The reservation is an estimate: actual cost can exceed it and push spending
over the configured limit. Use appropriate provider-key limits and generation
output bounds as additional controls. Application limits are not a hard
provider billing cap.

A trusted operator can inspect uncertain holds using read-only SQL:

```sql
SELECT id, tenant_id, user_id, status, reserved_credits, created_at
FROM credit_reservations
WHERE status IN ('reserved', 'unknown')
ORDER BY created_at DESC
LIMIT 30;
```

Reconcile uncertain charges against provider billing before any approved manual
adjustment. Do not casually delete historical holds or reinterpret missing costs
as zero. To disable budget enforcement intentionally, review pending activity,
clear tenant/user limits and unpause policies; preserve the accounting history.

## Personal credits and USDT payments

**Disabled for the current release.** `VITE_CREDITS_ENABLED` defaults to false.
Only the literal `true` enables the page at frontend build time; rebuild after
changing it. Production also pins `RAG_PAYMENTS_MODE=disabled` and
`RAG_WALLET_ENFORCEMENT=false`, so a hidden page is not the purchase safeguard.
Existing payment data/code is retained. These payment instructions describe
the separately enabled feature, not the current production rollout.

Every user has an individual tenant-scoped wallet. Monthly admin budgets remain
separate controls; purchasing credit does not raise or unpause them. Credit cards
are not implemented. Payments and prepaid enforcement are disabled by default.

### Pricing and confirmation

One usable credit covers US$1 of reported OpenRouter provider cost. Purchases add
a **5.5% service fee**, rounded half-up to the nearest cent: $10 credit costs
$10.55; $25 costs $26.38; $100 costs $105.50. No further application markup is
added when answers consume credit. Gateway processing/merchant settlement fees
come out of that surcharge; the sender's wallet/exchange may charge its own
network fee. Top-ups support $10–$1,000 with at most two decimal places; the
provider can impose higher network-specific minimums.

The Credits page requests a fixed-rate USDT payment through NOWPayments and
shows the exact amount, network, address and quote expiry. Supported network
choices are Tron (TRC-20), BNB Smart Chain (BEP-20), and Ethereum (ERC-20), subject
to provider availability. Do not assume USDT is always exactly US$1. Do not send
funds to another network, an expired quote, or a sandbox address. Once payment
is detected, the UI tells you to wait rather than send again.

Creating an order grants no credit. Callbacks require the mode-specific
HMAC-SHA512 signature. Completed/refunded events are also checked against the
provider API. Order/payment identity, USD price, network and quoted crypto amount
must match. Only fully paid `finished` payments credit the purchased usable
amount. Partial/inconsistent payments require review. Duplicate/concurrent
callbacks and manual checks cannot credit an order twice; delayed events cannot
downgrade credited/refunded orders. Verified full refunds reverse the original
credit once. Partial refunds require operator reconciliation; the application
does not initiate crypto refunds/payouts. Refunding spent credit can create a
negative balance that blocks new reservations.

Checkout request keys are bound to user, amount and network. Retries with the
same key reuse the existing order. Provider POSTs are not retried automatically:
a timeout may already have created a payment. Such orders require review in the
provider dashboard using the app's order UUID. Five creation attempts per
user/mode in 15 minutes limit accidental repeats. General distributed rate
limiting is separate work.

Payment and credit histories are independently paginated (20/50/100 rows).
Pending orders refresh from application storage every five seconds while visible
and online. **Check status** retrieves the provider state and can recover missed
callbacks. Creation failures without a stored provider payment ID need operator
review; after locating the matching payment, request an IPN resend from the
provider dashboard to reconcile it without manually editing balances. No
prompt/document content is sent to the payment provider.

### Setup and rollout

After a backup and stopping API/workers for approved maintenance, run the
repeatable migration (requires security, accounts and credit-budget migrations):

```bash
python -m scripts.migrate_credits
```

This creates five tables/indexes without funding accounts or rewriting existing
usage, reservations, documents or sessions. The API never runs it automatically.

Start in sandbox using private configuration; do not share credentials or commit
them. Existing `.env` files are never edited automatically:

```dotenv
RAG_PAYMENTS_MODE=sandbox
RAG_WALLET_ENFORCEMENT=false
RAG_PAYMENTS_CALLBACK_BASE_URL=https://your-test-host.example/api
NOWPAYMENTS_SANDBOX_API_KEY=
NOWPAYMENTS_SANDBOX_IPN_SECRET=
```

Use a NOWPayments sandbox account/key and IPN secret. The adapter uses
`https://api-sandbox.nowpayments.io/v1/payment` and the sandbox `success` case,
never the live host. Callbacks go to `/payments/nowpayments/sandbox/ipn`, with
`/api` prepended when using the frontend proxy. External callbacks require a
reachable public HTTPS endpoint; loopback alone is insufficient. Restart the API,
create a test payment at `/credits`, and verify exactly one test credit/ledger
entry. **Never send real crypto in sandbox.** Test balances are isolated and
cannot fund actual provider calls. Mocked tests are not proof of live sandbox or
network compatibility; verify the provider flow before activation.

Live activation is a separate operator step after merchant eligibility, fees,
callbacks and reconciliation are verified. Configure the separate live key and
IPN secret, set `RAG_PAYMENTS_MODE=live`, and set `RAG_WALLET_ENFORCEMENT=true`
when paid balances should become mandatory. New users start at zero; historical
usage is not charged retroactively. User payments fund the app wallet, not the
OpenRouter account itself; the operator must maintain provider funding.

With enforcement enabled, wallet and monthly holds share the same database
transaction before retrieval. Retrieval failures/empty sources release unused
holds. Reported costs debit the wallet, record usage and release holds atomically;
missing costs retain holds. Wallet holds do not expire at a month boundary.
Actual cost can exceed the reservation: the full cost is recorded, a negative
balance is allowed, and further reservations are blocked. Enforcing prepaid
usage with direct OpenAI or sandbox mode fails closed.

For rollback, review pending/unknown holds and settle in-flight work before
switching modes/code. Do not delete wallets, receipts or ledger history. Set
`RAG_PAYMENTS_MODE=disabled` and `RAG_WALLET_ENFORCEMENT=false` to stop new
purchases/deductions. Preserve credentials and callback processing for outstanding
payments: existing signed callbacks can still settle their original mode's orders.

Provider references: [API](https://documenter.getpostman.com/view/7907941/S1a32n38),
[callback verification](https://nowpayments.zendesk.com/hc/en-us/articles/21395546303389-IPN-and-how-to-setup),
and [fees](https://nowpayments.io/help/about-nowpayments/about/what-are-your-fees).

## Saved conversations

Assistant supports new, reopen, rename and delete. Conversations and messages
belong to one user in one tenant; administrators do not gain access to other
users' private chats. `/ask` remains stateless; saved questions use
`/conversations/{id}/ask` through the same retrieval, budget and generation path.

Saved messages include answer/source snapshots and physical PDF pages.
Authorization is rechecked when history is read. When a referenced document is
no longer accessible, the affected answer and excerpts are redacted; the
question can remain visible. This prevents revoked sources leaking through old
history. Deleting a conversation cascades its messages and feedback.

Saved questions use up to four recent authorized exchanges as conversational
context: at most 500 question characters and 1,000 answer characters per exchange.
Retrieval combines the current question with up to 1,000 characters from the
latest authorized exchange; the single generation request receives the bounded
window. There is no extra paid question-rewriting call. Previous answers are
untrusted reference context, not factual evidence; only newly retrieved sources
may support the new answer, and old citation numbers are removed from context.
Ambiguous references should prompt clarification. Language/script follow the
current question. This contextual retrieval is a bounded heuristic, not a
guarantee of resolving every follow-up correctly.
Context increases prompt size and can increase provider cost; existing wallet
and monthly-budget reservation/settlement rules still apply.

Ownership, source access, and selected knowledge-base membership are checked
before history enters retrieval/generation. A revoked, malformed, sourceless, or
out-of-scope exchange stops the context window from reaching older topics.
New saved sourced answers retain private JSON metadata identifying their context
document dependencies, including transitive dependencies. Revoking any of those
documents redacts the derived answer/sources and hides its feedback. That metadata
is omitted from API source objects. Existing rows remain readable without a
schema migration; `/ask` remains stateless.

The listing is capped at 100 recent conversations, and details load the latest
100 messages; history pagination is not implemented.

History is not application-encrypted at rest. Apply database backup/access and
retention policies. A provider call can incur cost before a subsequent message
save fails; blind retries may cause another paid call. End-to-end generation
idempotency is not implemented.

## Live support

Every signed-in role can use `/support` to start a private chat or open a direct
link such as `/support?chat=12`. Ordinary users and tenant admins see only their
own support conversations. The central support team sees threads across tenants
only through explicit operator configuration; tenant admin status alone grants
no such access. Support staff can reply and close/reopen threads. Support access
does not grant document, wallet, saved RAG conversation, or general tenant access.

Before enabling, back up the database and arrange approved maintenance. After
the existing security/accounts migrations, apply the optional additive migration:

```bash
python -m scripts.migrate_support
```

It creates `support_chats`, `support_messages`, and their indexes without changing
existing application records. This migration is prepared in the repository; the
API does not run it automatically. Set `RAG_SUPPORT_STAFF_USER_IDS` privately to
the global user IDs of designated active administrator accounts, separated by
commas, then restart FastAPI. Use dedicated operator-controlled accounts for
central support. No real account IDs are preconfigured. Empty configuration
disables new chats/replies but preserves users' access to their existing history.
Invalid configuration fails closed; demotion/deactivation or removal from the
allowlist removes global support access on subsequent requests.

The inbox has status filters and 20/50/100 pagination. Thread messages arrive in
incremental pages of at most 100. Mounted views poll every three seconds, pause
while hidden/offline, and refresh on return without replacing content or edits.
Only one read/write per resource runs at a time; obsolete responses are ignored.
Message rendering is plain text, and per-request UUIDs prevent duplicate threads
or messages after uncertain retries. Creation is limited to five open chats per
user. Subjects have a 120-character limit; messages have a 4,000-character limit.

This is staff messaging, separate from the RAG assistant and provider billing.
Users explicitly submit support text; documents, prompts, and other chat history
are not attached automatically. Support transcripts are persistent database data
covered by backup/access/retention policies. There are no attachments, email/push
notifications, typing/read receipts, presence guarantees, or dedicated staff roles
in this first version. Staff must keep the page open to receive updates; users
are told that replies may not be immediate. Shared throttling and broader support
operations remain separate improvements.

To disable new support activity, clear the staff setting and restart the API.
Preserve the tables and transcripts; do not drop them for rollback. Revoked
document access also depends on the new context-provenance checks, so retain those
checks when rolling back other UI/support changes.

## Knowledge bases

Knowledge bases organize existing documents in tenant-scoped collections. They
are a retrieval filter, never a permission grant. `knowledge_base_id=null`
means all accessible documents.

Admins/editors create collections. Their creator and tenant admins can manage
them. Adding/removing a document also requires document ownership or tenant
admin authority; having read access to someone else's document is insufficient.
Readers can browse/select collections containing documents accessible to them.

Select a collection in Assistant to scope new questions, including new questions
inside existing conversations. Historical snapshots are unchanged and still
recheck document access. The selection is not persisted as a browser preference
across refreshes. Foreign-tenant/nonexistent collection IDs are rejected before
embedding/provider work. Composite database foreign keys also prevent
cross-tenant memberships.

Deleting a collection removes memberships, not the documents. Document deletion
cascades its memberships.

## Answer feedback

Users can thumbs-up/down their own saved assistant answers, optionally giving a
downvote reason: `incorrect`, `incomplete`, `irrelevant`, `outdated`, or
`other`. They can update or remove the rating. One current vote is stored per
message, with an updated timestamp; it is not an append-only event ledger.

Feedback requires conversation ownership and continued source access. Revoked
sources hide/block affected feedback. Conversation deletion cascades ratings.
Admin analytics expose tenant aggregate counts, daily trends, reasons and
limited recent downvote metadata, not private question/answer text or excerpts.

Reports cover all recorded history plus a selected 7/30 UTC-day window including
today. Sentiment is a quality signal, not a factual correctness score or
automatic retrieval evaluation.

## Audit log and observability

### Persistent audit log

Admins can browse `/audit-log` with user, action and inclusive UTC date filters,
20/50/100-row pagination and URL query state. The dashboard also shows its latest
10 events. The API is `GET /admin/audit-log` with `page`, `page_size`,
`user_id`, `action`, `date_from` and `date_to`.

Audit records are tenant-scoped and contain action/identity/document identifiers,
timestamps and applicable result counts. Deleted documents retain recorded IDs.
Audit logging avoids raw keys, passwords, prompts and document excerpts.
This browsing endpoint is read-only; searches themselves can create audit rows.

### Process-local performance metrics

`GET /observability` is admin-only and tenant-scoped. It reports search/ask
retrieval and generation calls, errors/error rates, latency mean/p50/p95, and
observed provider tokens/costs. Latency percentiles use at most the latest 256
samples per phase; the process tracks at most 1,000 tenants.

These metrics reset on API restart/reload, are not shared between API processes,
and do not include the separate worker's process. They are not durable billing
records. `RAG_OBSERVABILITY_ENABLED=false` stops new measurements without
erasing already collected values until restart.

HTTP middleware returns `X-Request-ID` and logs a generated request ID, method,
route template, status and elapsed time. It does not intentionally log request
bodies, authorization headers, prompts, excerpts or raw query strings. Keep
custom proxy/server logging equally restrictive.

`GET /ingestion-health` gives admins tenant job counts and processing jobs
whose heartbeat is older than ten minutes. It exposes no document contents or
filenames and does not prove that a worker is alive when the queue is idle.

## API reference

Backend paths below have **no `/api` prefix** at port 8000. Browser requests use
`/api` through Vite/Nginx. FastAPI's `/docs` and `/openapi.json` describe the
exact request/response schemas. Except for health, authentication entry points,
API documentation and provider-signed payment callbacks, application routes
require a valid principal.

API clients send `Authorization: Bearer <API-key-or-session-token>`. Browser
cookie clients use same-origin credentials and `X-RAG-CSRF: 1` as described
above. Do not put credentials in URLs.

| Methods and paths | Purpose / access |
| --- | --- |
| `GET /health` | Public database readiness; 503 if unavailable. Not a full worker/provider test. |
| `GET /me` | Current public identity; no key material. |
| `GET /credits` | Own selected-mode balance, held/available credits and non-secret payment settings. |
| `GET /credits/orders`, `GET /credits/transactions` | Own paginated payments/ledger; page/page_size (20/50/100). Admins cannot browse another user's wallet. |
| `POST /credits/orders` | Create a USDT payment using credits (decimal string), network and request_key (UUID); server determines identity and price. |
| `POST /credits/orders/{order_id}/check` | Owner retrieves provider status and reconciles missed callbacks. |
| `POST /payments/nowpayments/{mode}/ipn` | Provider-signed public callback, not user-session authentication; sandbox/live modes, bounded body and transactional replay protection. |
| `GET /support/chats` | Own paginated chats; designated central staff get the global inbox. Query: page/page_size (20/50/100), status (all/open/closed). |
| `POST /support/chats` | Create own chat with subject, body, request_key (UUID); identity is server-derived. |
| `GET /support/chats/{id}/messages` | Owner or designated staff; after_id cursor, at most 100 messages and has_more. |
| `POST /support/chats/{id}/messages` | Owner or designated staff sends body/request_key; closed chats reject new replies. |
| `PATCH /support/chats/{id}` | Designated central staff only; status open/closed, locked and rechecked. |
| `POST /auth/login`, `POST /auth/register` | Bearer-session login or registration. Login: email/password; registration also needs username, with optional invitation_code. Without a code, creates an isolated editor workspace. |
| `POST /auth/logout` | Revoke the supplied session. |
| `POST /auth/browser/login`, `POST /auth/browser/register` | Same account flows with HttpOnly cookie, no session secret in response JSON. |
| `GET /auth/session`, `POST /auth/browser/logout` | Restore/revoke browser session with browser request checks. |
| `GET /auth/sessions` | Own active password sessions; page/page_size (20/50/100), current-session marker, password availability. No tokens or hashes. |
| `POST /auth/password` | Own password change with current_password/new_password; revokes all password sessions atomically. API keys remain valid. |
| `DELETE /auth/sessions/{session_id}` | Revoke an own active session; returns sign_in_required and revoked_count. Other users' sessions return 404. |
| `POST /auth/sessions/revoke-others` | Revoke own active password sessions except the authenticating password session; API-key callers revoke all own password sessions. |
| `POST /documents` | Writer JSON ingestion: title/text; creates private owned document. |
| `GET /documents` | Existing visible indexed-document list contract. |
| `GET /documents/library` | Combined authorized library; page/page_size/q/status/file_type. Status: indexed/queued/processing/failed; file type: pdf/md/txt; page size: 20/50/100. Returns items, total, page, page_size, pages. |
| `POST /documents/upload` | Writer synchronous multipart upload using field `file`. |
| `POST /documents/upload-async` | Writer multipart queue submission; 202 with job identity/status. |
| `POST /documents/{document_id}/reindex-pdf` | Authorized writer owner/admin replaces/reindexes matching PDF via multipart `file`. |
| `GET /documents/{document_id}/original-pdf` | Authorized reader fetches private PDF bytes. |
| `GET /documents/{document_id}/access` | Writer owner/admin gets same-tenant candidate/recipient states. |
| `PATCH /documents/{document_id}/access` | Writer owner/admin updates `grant_user_ids` and `revoke_user_ids` arrays. |
| `POST /documents/{document_id}/share` | Existing single-username grant contract. |
| `DELETE /documents/{document_id}` | Writer owner/admin deletes document, chunks/memberships and stored PDF. |
| `GET /ingestion-jobs`, `GET /ingestion-jobs/{job_id}` | Job visibility: owner, or same-tenant admin. |
| `DELETE /ingestion-jobs/{job_id}` | Failed jobs only, writer owner/admin; 409 if status is not failed, 503 on staged cleanup failure with record retained. |
| `POST /search`, `POST /ask` | Authorized search or grounded generation. Body: question, top_k, optional knowledge_base_id. |
| `GET /conversations`, `POST /conversations` | List/create current user's conversations; creation accepts a title. |
| `GET /conversations/{id}`, `PATCH /conversations/{id}`, `DELETE /conversations/{id}` | Own conversation detail, title change, deletion. |
| `POST /conversations/{id}/ask` | Save question/answer/sources in own conversation. Same body as ask. |
| `GET /conversations/{id}/feedback` | Own accessible answer ratings. |
| `PUT /conversations/{id}/messages/{message_id}/feedback`, `DELETE /conversations/{id}/messages/{message_id}/feedback` | Set rating to `"up"` or `"down"` with optional downvote reason, or remove vote. |
| `GET /knowledge-bases`, `POST /knowledge-bases` | List visible collections; writer creates with name/description. |
| `PATCH /knowledge-bases/{id}`, `DELETE /knowledge-bases/{id}` | Collection creator/admin updates name/description or deletes collection. |
| `GET /knowledge-bases/{id}/documents` | Accessible member documents. |
| `PUT /knowledge-bases/{id}/documents/{document_id}`, `DELETE /knowledge-bases/{id}/documents/{document_id}` | Manage membership with collection and document authority. |
| `GET /admin/dashboard` | Tenant admin overview/latest audit events. |
| `GET /admin/users`, `PATCH /admin/users/{user_id}` | Admin user list and role/is_active update. |
| `POST /admin/users/{user_id}/revoke-sessions` | Admin revokes target user's password sessions. |
| `GET /admin/invitations`, `POST /admin/invitations` | Admin lists/creates invitations with email and reader/editor role; new code shown once. |
| `GET /admin/usage?days=30` | Tenant OpenRouter usage; days accepts 7 or 30. |
| `GET /admin/budgets` | Tenant/user policies and current monthly accounting. |
| `PUT /admin/budgets/tenant` | monthly_limit_credits (decimal string/null), paused, reservation_credits (decimal string). |
| `PUT /admin/budgets/users/{user_id}` | monthly_limit_credits (decimal string/null), paused; returns updated budget dashboard. |
| `GET /admin/feedback?days=30` | Tenant aggregate feedback quality signals; days accepts 7 or 30. |
| `GET /admin/audit-log` | Filtered/paginated tenant audit records. |
| `GET /ingestion-health`, `GET /observability` | Tenant admin queue health / process-local performance metrics. |

Example JSON for authenticated `POST /search`, `POST /ask`, or saved ask:

```json
{
  "question": "My VPN login is failing. What should I check?",
  "top_k": 3,
  "knowledge_base_id": null
}
```

Example JSON for a writer's `POST /documents`:

```json
{
  "title": "New laptop onboarding",
  "text": "All new company laptops must enroll in device management before accessing internal services. The help desk verifies device identity and installs approved security updates."
}
```

A source includes its source_number, document_id, title, chunk_index, content,
cosine similarity and optional physical page_number. Numbered citations connect
answers to these authorized excerpts; citation presence is not machine-verified
factual correctness.

Use Swagger's **Authorize** control with your bearer credential for protected
examples. The frontend's `/documents` page and FastAPI's `/docs` API explorer
are different URLs.

## Worker operations and recovery

The normal worker command polls every two seconds. `--poll-seconds` accepts
0.2–60. `--once` processes at most one eligible job and exits: it can change
documents/jobs and is not a read-only health probe.

Before processing, the worker checks that the uploader still exists, is active,
has an editor/admin role, and belongs to the job's tenant. A no-longer-authorized
job is finalized as failed rather than indexed. If finalization fails, staged
input is retained for safe investigation/recovery.

Temporary connection/timeout failures receive at most **three total attempts**,
with 15-second then 30-second retry delays. Retry status is queued, with next
availability recorded and staged input retained. Permanent validation failures
become failed; successful and finalized permanent jobs normally remove staged
input. Database failure during finalization retains input.

Active jobs heartbeat every 15 seconds. A stale heartbeat can indicate a crash
or a database outage; age alone does not prove the process is dead. After
investigation, preview stale-job recovery without database writes:

```bash
python -m scripts.recover_ingestion_jobs --older-than-minutes 10
```

For approved recovery, stop **all ingestion workers**, confirm no process can
continue indexing, and then apply:

```bash
python -m scripts.recover_ingestion_jobs --older-than-minutes 10 --confirm --workers-stopped
```

Present staged input with fewer than three attempts is requeued. Missing input
or exhausted attempts becomes failed. Exhausted staged files remain for reviewed
operator cleanup. The threshold must be at least five minutes; prefer the
default ten rather than reclaiming recently active work.

The spool directory is private (0700) with staged files 0600. Monitor disk space
and filesystem access. Do not delete staged files belonging to active jobs.
Processing is not exactly-once: deduplication mitigates a crash between document
commit and job completion, but recovery can repeat work. Never reclaim a job
while an old worker may still be running.

## Testing and evaluation

### Automated checks

From the project root with the virtual environment active:

```bash
python -m pytest tests/ -q
git diff --check
```

From `frontend/`:

```bash
npm test
npm run build
```

Python tests mock database/provider/model operations where appropriate and use
temporary files for ingestion. Frontend tests use Vitest/Testing Library with
jsdom. They cover authorization, tenant boundaries, budgets/settlement,
conversations, collections, feedback, sharing, navigation, polling and management
UI. Passing these suites does not establish live PostgreSQL, provider billing,
model download, browser rendering, or deployment correctness.

For production-build verification without updating existing TypeScript build
state/output, copy the frontend without local environment files or generated
files. Run from `frontend/` on macOS/Linux:

```bash
build_dir=$(mktemp -d)
tar --exclude=node_modules --exclude=dist --exclude=coverage --exclude='.env*' --exclude='*.tsbuildinfo' -cf - . | tar -xf - -C "$build_dir"
ln -s "$PWD/node_modules" "$build_dir/node_modules"
(cd "$build_dir" && VERCEL=1 VITE_API_BASE_URL=https://api.example.com VITE_CREDITS_ENABLED=false npm run build)
```

The output stays in a separate temporary directory for review; remove it only
when no longer needed. No runtime data needs to be changed for automated tests.
Manual upload/share/delete tests should use approved disposable documents and
accounts, never live private records.

### Retrieval evaluation

`scripts.evaluate_rag` compares authorized retrieval against
`evaluation/questions.json`, using the operator `RAG_ADMIN_API_KEY`.
The bundled eight cases refer to the four sample TXT files and
`incident-response.pdf`; upload that fixture separately if using the PDF cases.
Do not assume a particular document ID or physical page number in another
database. Use a dataset matching your authorized corpus.

```bash
python -m scripts.evaluate_rag --retriever vector --warmup --top-k 5 --output evaluation/results-vector.json
python -m scripts.evaluate_rag --retriever hybrid --warmup --top-k 5 --output evaluation/results-hybrid.json
python -m scripts.evaluate_rag --retriever rerank --warmup --top-k 5 --output evaluation/results-rerank.json
```

`--dataset` accepts a JSON case list. Each case has nonempty string fields `id`,
`question`, `expected_title`, and `evidence_contains`, plus an optional
`expected_answer_terms` string array. Retrieval-only runs
make no generation calls and do not alter documents/schema, but searches can
write audit events. Model downloads/cache writes may occur. Warmup runs one
untimed retrieval for comparable steady-state measurements.

Reported metrics include document Recall@k against the expected title, exact
case-insensitive evidence matching within a chunk, reciprocal rank of the first
evidence hit, and retrieval wall-clock p50/p95. These are small-dataset proxies,
not broad quality guarantees.

`--answers` additionally calls the configured provider, sends retrieved
excerpts, incurs possible charges and writes generated answers into reports.
This operator CLI calls generation directly rather than the HTTP
reservation/settlement wrapper; do not use it to test API budget enforcement
or expect dashboard accounting for these calls. Answer metrics check numeric
citation references, evidence-citation proxies and expected-term coverage;
they do not prove semantic correctness.

Reports can contain sensitive generated content; keep them private and out of
Git. Existing results/answers/baseline report patterns under `evaluation/` are
ignored, but use care with custom output names. The local Chinese smoke commands
in [Changing embedding models safely](#changing-embedding-models-safely) avoid
both database access and paid generation.

## Optional Docker deployment rehearsal

`deploy/compose.yaml` is an optional single-machine rehearsal, not an assumed
existing deployment or an Internet-facing production stack. It runs API, worker
and Nginx/React containers while reusing an existing PostgreSQL container and
its preserved volume.

1. Inspect your running database with `docker ps` / `docker inspect`. The
   checked-in rehearsal configuration expects the database to be reachable as
   `enterprise-rag-postgres` on the external `rag_shared` network. If your
   setup differs, configure the connection hostname/alias to match reality;
   do not create a replacement database.
2. Inspect `docker network inspect rag_shared`. If absent, create it with
   `docker network create rag_shared`; attach the **verified** database
   container with `docker network connect rag_shared <database-container>`
   if not already attached. Recreated database containers need reattachment.
3. Stop host API processes and all host ingestion workers before starting the
   container equivalents. Migrate the database separately under the approved
   procedure; container startup does not run migrations.
4. Only if absent, copy `deploy/.env.deploy.example` to
   `deploy/.env.deploy`. Set `RAG_UID` / `RAG_GID` using `id -u` /
   `id -g`, and `RAG_DEPLOY_DATABASE_URL` with the real database credentials
   and reachable container hostname, not host loopback. Root `.env` still
   provides model/provider settings.
5. Ensure `.original_pdfs`, `.ingestion_spool` and `.model_cache` exist
   with appropriate ownership; do not loosen existing private permissions.
   Compose mounts them as `/data/pdfs`, `/data/spool` and
   `/data/model-cache` and explicitly sets the matching service paths.

Then validate without printing interpolated secrets, build, and start:

```bash
docker compose --env-file deploy/.env.deploy -f deploy/compose.yaml config --quiet
docker compose --env-file deploy/.env.deploy -f deploy/compose.yaml build
docker compose --env-file deploy/.env.deploy -f deploy/compose.yaml up -d
docker compose --env-file deploy/.env.deploy -f deploy/compose.yaml ps
python -m scripts.smoke_deployment
```

Open [the rehearsal UI](http://127.0.0.1:8080). Set `RAG_WEB_PORT` in the
deployment environment to use another port. Nginx supports SPA deep links,
proxies `/api`, preserves Host/port and returns private API responses with
no-store. The supplied stack is loopback HTTP; external HTTPS termination
requires an explicitly trusted forwarded-scheme configuration.

The smoke script checks the web page, database health and unauthenticated
document rejection. It does not test tenant isolation, authenticated PDF
viewing, worker completion, model quality, cookie flows or provider generation.

To stop the rehearsal:

```bash
docker compose --env-file deploy/.env.deploy -f deploy/compose.yaml down
```

Do not add volume-removal flags. This stack's database network is external;
preserve the separate PostgreSQL container, data volume and private bind mounts.
Restart the host API/worker only after container equivalents have stopped.

## Neon database and object storage

Neon is a separate, fresh production environment. No local database, users,
documents, conversations, original PDFs or staged uploads are imported. Ordinary
local API/worker commands continue to use local `.env` and filesystem storage.
The existing psycopg driver, schema, authentication and tenant/document ACLs remain.

The configured project is `snowy-morning-04430062`, production branch
`br-spring-forest-azpdlnyv`, in AWS Singapore. It already uses PostgreSQL 17;
setup preserves that version. `neon.ts` declares two **private** buckets:
`rag-documents` (original PDFs) and `rag-uploads` (staged PDF/TXT/MD uploads).
The schema runner applies the existing migrations; this adapter adds no tables.

### Provisioning without replacing local configuration

Use these commands from the repository root after Neon browser sign-in:

```bash
neon link --org-id org-misty-darkness-64606156 --project-id snowy-morning-04430062 --branch production --no-env-pull --no-config -y
neon config plan
neon deploy --no-env-pull
neon env pull --service postgres,object-storage --file .env.neon
chmod 600 .env.neon
```

Review the plan before applying. Do not use a bare `neon init`, `neon link`,
`neon deploy`, `neon checkout` or `neon env pull` in this repository: automatic
environment pulls can replace the local `DATABASE_URL`. Even `init --no-link`
can pull variables when the directory is already linked. Use the explicit
opt-outs and output filename above. The generated `.neon`, `.env.neon*`, agent
skills and node_modules are ignored; the example file and service config are
reviewable. `.vercelignore` excludes credentials, private data and local caches.

`.env.neon.example` documents the required values. The real `.env.neon` contains
pooled and direct URLs plus the four AWS storage variables. It is never loaded
by normal local startup. Keep it private: the direct URL retains owner privileges.
Database credentials and object-storage credentials are separate.

For a **new, empty** Neon database only, preview and initialize:

```bash
python -m scripts.check_neon --before-schema
python -m scripts.run_neon --direct -- python -m scripts.setup_database
python -m scripts.run_neon --direct -- python -m scripts.setup_database --apply
python -m scripts.neon_runtime_role --apply
python -m scripts.check_neon
```

The schema was tested on an expiring validation branch before production setup.
Do not repeat fresh initialization against an existing application database;
use approved maintenance with backups and the schema runner's `--upgrade` flag.
Never use an import, restore or local dump unless explicitly requested.

`scripts.neon_runtime_role` previews unless `--apply` is supplied. It creates
`rag_app` using SQL with only table DML and sequence access, refuses elevated or
unknown existing runtime credentials, and changes only `DATABASE_URL` in the
selected Neon file. It preserves `DATABASE_URL_UNPOOLED` for maintenance. Use the
same owner for future migrations so its default grants apply.

### Running against Neon deliberately

In separate terminals, with the virtual environment active:

```bash
python -m scripts.run_neon -- python -m uvicorn app.main:app --host 127.0.0.1 --port 8011
python -m scripts.run_neon -- python -m scripts.ingestion_worker
```

The launcher requires a TLS Neon database URL, selects the separate settings
file, uses its cloud credentials, and enables S3 mode. `--direct` selects the
owner URL for approved operator commands; normal API/worker traffic uses pooling
and the restricted role. It never falls back to a local database connection.
Both processes must use the same embedding model and 384-dimensional vectors.
Set `HF_HOME` explicitly if reusing a model cache outside the library's default
location. Model weights remain local to each process; they are not stored in
PostgreSQL or the document buckets.

For browser use, configure the backend's exact `RAG_ALLOWED_ORIGINS` and start
the frontend with the matching public `VITE_API_BASE_URL`. For generation, add a
production OpenRouter key to the private cloud configuration; local provider
credentials are not copied automatically. Existing operator commands, such as
`scripts.set_user_password`, can be run through `scripts.run_neon --direct` to
configure the newly created admin. Never expose the owner URL, S3 credentials or
provider keys to the browser.

### Storage behavior and remaining deployment work

The existing upload APIs and responses are preserved. Uploaded filenames remain
metadata: staged keys use server-generated UUIDs and original-PDF keys use
document IDs. The API/worker access storage with server credentials. Every PDF
request checks the existing SQL authorization policy **before** probing storage;
responses stream privately with `no-store` and single-byte-range support. No
public PDF URLs or long-lived browser storage credentials are introduced.

Workers retain staged objects during transient retries and failed finalization;
successful/terminal finalization removes staged contents. Failed-job removal
retains its database record if object cleanup fails. Stale-job recovery checks
the selected storage backend. Object storage and PostgreSQL are separate systems;
an object cleanup failure can leave an orphan requiring operator review.

This setup proves Neon connectivity and storage through the current API. See
the Vercel compute section below for deployment verification. The direct upload flow below
bypasses the function-request body limit for new library uploads. Existing
synchronous uploads and PDF replacement/reindex still send multipart bodies to
FastAPI and remain subject to the hosting platform's request-size limit.
Platform quotas, concurrent model memory and large-document shutdown behavior
still need monitoring under production traffic. The VPS
preflight below remains specific to the optional VPS deployment; use
`scripts.check_neon` for Neon database/storage checks.

### Direct browser uploads for hosted deployments

Local uploads remain unchanged by default. To opt in for new library uploads,
the browser requests an authenticated upload policy, posts file bytes directly
to the private upload bucket, then confirms the upload with FastAPI. Only small
JSON requests cross the API host. The existing multi-file queue and job polling
continue to work. The existing 50 MiB/file and PDF page limits still apply.

New authenticated writer endpoints (no schema migration):

- `POST /documents/uploads/prepare`: `{filename, size, sha256}` returns
  `{ticket, url, fields, expires_at}`. The signed POST permits exactly the
  declared byte length at one server-generated `incoming/` key for ten minutes.
- `POST /documents/uploads/complete`: `{ticket}` verifies current writer
  permission, user/tenant, expiry, environment, byte count, SHA-256 and PDF magic.
  It freezes verified input under a separate server-only `staged/` key and
  returns the existing queued-job response with HTTP 202. Extraction and full
  PDF validation stay in the worker. Advisory locking makes concurrent/repeated
  completion safe; a browser policy cannot overwrite accepted worker input.

Tickets and signed POST fields are temporary capabilities: keep them out of
logs, analytics, source control and screenshots. Storage requests omit API
bearers, session cookies and CSRF headers. Missing signing configuration fails
closed. A storage authorization error does not sign the user out of the app.
The client retries an ambiguous completion acknowledgement once using the same
ticket, without uploading again or creating a second job.

Production activation, after selecting a frontend domain:

1. Generate a unique random server-only `RAG_UPLOAD_SIGNING_KEY` of at least
   32 bytes using your secret manager. Set it in the API environment, alongside
   the existing Neon/S3 configuration. Never prefix this secret with `VITE_`.
   A key rotation invalidates uncompleted tickets. Do not edit the local `.env`.
2. Configure the API's exact `RAG_ALLOWED_ORIGINS` for the frontend URL and check
   bucket CORS. The helper preserves unrelated rules and previews by default:

   ```bash
   python -m scripts.configure_upload_cors --env-file .env.neon --origin https://app.example.com
   python -m scripts.configure_upload_cors --env-file .env.neon --origin https://app.example.com --apply
   ```

   **Observed provider limitation, October 24, 2026:** the validation bucket's
   `GetBucketCors` returns wildcard origins. `PutBucketCors` returns
   `NoSuchBucket`, although bucket reads/writes succeed. The alternate standard
   Content-MD5 format gives the same result. Exact-origin restrictions could not
   be applied or verified; no production CORS change was made. The helper checks
   readback before claiming success and warns about retained wildcard rules.
   Resolve this with Neon before claiming an origin allowlist. CORS is separate
   from object authorization: private objects still require valid credentials;
   signed uploads are limited to their temporary key and byte count.
3. Set frontend `VITE_DIRECT_UPLOADS=true` and the existing public
   `VITE_API_BASE_URL`, then rebuild/redeploy. The switch defaults to `false`.
   The current frontend uses `https://api-rag.weichen.space` with direct uploads
   enabled. A real upload above 4.5 MiB passed through the deployed preview API
   and private storage. Production storage preflight permits the app origin
   through the provider's existing wildcard rule; it is not an exact-origin rule.
4. Test sign-in, multiple uploads, processing status, citation/PDF access and
   forbidden-user behavior in the deployed browser. Large replacement/reindex
   needs a separate direct-upload change before it can bypass function limits.

Abandoned policies and interrupted uploads can leave `incoming/` objects.
Preview cleanup through the explicit Neon launcher; schedule only after review:

```bash
python -m scripts.run_neon -- python -m scripts.cleanup_direct_uploads
python -m scripts.run_neon -- python -m scripts.cleanup_direct_uploads --older-than-hours 24 --apply
```

Only expired UUID-named `incoming/` objects are selected. Accepted `staged/`
input, original PDFs and database records are never removed by this command.
Neon lifecycle configuration is not an enforced cleanup mechanism; this command
is not scheduled automatically. Frozen orphans after an uncertain database
commit require separate operator review; accepted input is retained safely.

Direct-upload regression coverage lives in `tests/test_direct_uploads.py`,
`tests/test_direct_upload_operations.py` and `frontend/src/api.test.ts`.
The opt-in live check uses only synthetic files on an expiring validation branch:

```bash
python -m scripts.smoke_neon --env-file .env.neon-validation --direct-uploads --run
```

It checks a PDF larger than 4.5 MiB, storage size-policy enforcement, CORS
responses, foreign-tenant denial, concurrent completion and immutable staging,
then runs the existing real-worker/retrieval/PDF checks. Wildcard CORS is reported
explicitly; a successful smoke run does not prove an exact-origin allowlist or
a Vercel deployment. No paid generation or local-data import is involved.

Verified October 24, 2026: **587 Python tests** and **220 frontend tests**
passed. Root `npm run build` passed with `VERCEL=1`, a synthetic HTTPS backend
URL and `VITE_DIRECT_UPLOADS=true` in an isolated temporary copy. The direct
live smoke passed all checks above, including real worker processing, PDF
round-trip/ranges, physical-page citations, tenant isolation, empty-source
budget handling, staging cleanup and denial of unsigned original-PDF reads.
CORS used the provider's existing wildcard response. These were the initial
local checks; subsequent Vercel runtime checks are recorded below. A deployed
browser remains unverified. Local `.env` and tracked TypeScript build-state
checksums remained unchanged; `git diff --check` passed.

| Direct-upload changed files | Purpose |
| --- | --- |
| `app/direct_uploads.py`, `app/direct_uploads_api.py` | Signed preparation, verified/idempotent completion and writer-protected routes. |
| `app/main.py`, `app/schemas.py`, `app/settings.py` | Router registration, typed metadata contracts and server signing configuration. |
| `app/object_storage.py` | Separate browser incoming keys, bounded reads and incoming cleanup. |
| `frontend/src/api.ts`, `frontend/src/api.test.ts` | Opt-in direct transport, credential separation, safe errors and completion retry coverage. |
| `.env.example`, `.env.neon.example`, `frontend/.env.example` | Server secret and disabled-by-default frontend switch documentation. |
| `scripts/configure_upload_cors.py`, `scripts/cleanup_direct_uploads.py` | Explicit CORS configuration and dry-run-first abandoned upload cleanup. |
| `scripts/smoke_neon.py` | Synthetic large direct-upload and completion-race verification. |
| `tests/test_direct_uploads.py`, `tests/test_direct_upload_operations.py` | Authorization, ticket, byte-integrity, uncertain-commit and operator-tool regressions. |
| `README.md` | Activation, verification, provider limitation and rollback instructions. |

To roll back the opt-in transport, set `VITE_DIRECT_UPLOADS=false` and redeploy
the frontend. Keep the completion endpoint available until outstanding tickets
expire. Existing accepted jobs remain valid for the worker. This requires no
database rollback, data deletion or change to the local `.env`.

### Verification and changed files

`scripts.smoke_neon --run` starts actual API/worker processes and creates only
synthetic fixtures on a `codex-neon-validation-*` branch. It refuses production
fixture runs, uses cached real embeddings, and disables the provider key. To
repeat on a separately provisioned validation branch:

```bash
python -m scripts.smoke_neon --env-file .env.neon-validation --run
```

The validation branch created October 24, 2026 expires October 26, 2026 at
00:00 UTC. Synthetic accounts/documents remain only on that branch. Temporary
API/worker processes are stopped after verification.

Verified October 24, 2026: **554 Python tests passed**, **215 frontend tests
passed**, and root `npm run build` passed in an isolated temporary copy. The
live smoke run passed using real Neon PostgreSQL/pgvector, S3 uploads, a separate
worker, actual cached embeddings, PDF round-trip/ranges, physical page citations,
cross-tenant denial, empty-source budget settlement and staged-object cleanup.
Unsigned PDF access was denied. No provider call was made. Final read-only
production checks confirmed the schema, pgvector, restricted `rag_app` role and
both private buckets. Local `.env` and tracked TypeScript build-state checksums
match the originals. Existing AnyIO/pytest warnings remain nonblocking.

Selected live command output:

```text
PASS: real FastAPI process started; Neon-backed /health returns 200
PASS: separate worker completed both jobs using real local embeddings and Neon pgvector
PASS: original PDF round-trip, byte ranges, no-store and cross-tenant denial
PASS: real retrieval with physical page citations and tenant isolation
PASS: all live Neon smoke checks; no local data imported or paid generation used
```

| Changed files | Purpose |
| --- | --- |
| `neon.ts`, `package.json`, `package-lock.json` | Two private buckets, Neon configuration dependencies and root build/test commands delegating to the existing frontend. |
| `.gitignore`, `.vercelignore`, `.env.neon.example`, `.env.example` | Separate cloud configuration, secret/data exclusions and documented storage settings. |
| `app/settings.py`, `scripts/run_neon.py` | Explicit cloud environment selection without replacing local startup. |
| `app/object_storage.py`, `requirements.txt` | Boto3 transport with HTTPS, SigV4/path-style access, bounded reads, sanitized errors and streaming cleanup. |
| `app/ingestion_jobs.py`, `scripts/recover_ingestion_jobs.py` | Remote staging, worker retries/finalization, failed-job cleanup and recovery. |
| `app/original_pdfs.py`, `app/main.py` | Authorized private original storage, PDF streaming/ranges and generic storage-outage responses. |
| `scripts/neon_runtime_role.py`, `scripts/check_neon.py` | Restricted database role setup and read-only schema/bucket readiness checks. |
| `scripts/smoke_neon.py` | Opt-in end-to-end verification using real cloud services and synthetic fixtures. |
| `tests/test_object_storage.py`, `tests/test_run_neon.py`, `tests/test_neon_runtime_role.py` | Storage failure/authorization, environment isolation and runtime-role regression coverage. |
| `README.md` | Setup, startup, validation, limitations and rollback instructions. |

Rollback: use the prior code and ordinary local startup with the original local
`.env`. Keep cloud credentials separate; do not point the local database at S3
without an explicit file migration. No local data was moved. Do not delete Neon
databases/buckets or reset volumes as a code rollback shortcut.

## Vercel API and worker deployment

The frontend remains the existing Vite app in a separate Vercel project. A
second Vercel project at the **repository root** can build the FastAPI backend
and the ingestion Daemon. There are no frontend-to-backend rewrites. Neon holds
the existing schema and private objects; no local database is imported.

The API and frontend have passed Vercel preview builds and cloud runtime checks.
As of October
24, 2026, Vercel documents [large Python Functions](https://vercel.com/docs/functions/limitations)
up to 5 GB with Fluid compute, and [Daemons](https://vercel.com/docs/daemons) for
container-based continuous workers. These are beta features. The
[Daemon limits](https://vercel.com/docs/daemons/limits) currently allow 1/2 GiB
instances on Hobby with five Active CPU-hours/month; reaching the quota stops
workers until the quota resets or the plan changes. This is a deployment path
to evaluate, not a promise of unlimited free production hosting.

### What the configuration does

- Root `vercel.json` selects FastAPI in Singapore, a 2 GiB/300-second API
  function, CPU-only PyTorch installation and build-time model packaging.
  `pyproject.toml` explicitly selects `server:app`; `.python-version` selects
  Python 3.12. The frontend keeps its own `frontend/vercel.json`.
- `server.py` exports the existing application after selecting the bundled
  models and requiring remote storage. Local `uvicorn app.main:app` is unchanged.
- `Dockerfile.vercel-worker` builds a Linux CPU worker with the same model IDs
  and immutable revisions. It copies only approved source, installs models at
  build time and runs as an unprivileged user. Runtime credentials are never
  image build arguments. Only public model IDs/revisions are consumed there.
- The release configures **one Singapore ingestion instance**, enabled after
  Linux validation against the isolated Neon branch. It polls every 15 seconds and receives up to 600
  seconds to drain on termination. `SIGTERM` and `SIGINT` stop the existing
  worker loop after current work finishes; idle/error waits stop promptly.
- `scripts.prepare_model_bundle` serializes selected models into a new
  `model_bundle/` directory and writes its manifest last. Release builds require
  full Hugging Face commit revisions and reject CUDA dependencies or embedding
  dimensions other than 384. Existing output is never overwritten.
- Hosted entrypoints require that bundle, force offline loading and keep the
  configured model IDs intact, including multilingual E5 query/passage behavior.
  A missing model or revision mismatch fails instead of downloading a substitute.
  Normal local cache/download behavior remains unchanged without the bundle flag.

### Setup sequence

1. Choose same-site HTTPS addresses, for example `app.example.com` for the
   frontend and `api.example.com` for FastAPI. Two separate default
   `*.vercel.app` project domains do not satisfy this app's strict same-site
   browser-session policy. Keep the existing secure cookie/CSRF rules; set the
   API's `RAG_ALLOWED_ORIGINS` to the exact frontend origin. This release uses
   `https://rag.weichen.space` and `https://api-rag.weichen.space` respectively.
2. Import the repository as a **backend** Vercel project, Root Directory `.`.
   Select FastAPI and use the checked-in install/build commands. Enable Fluid
   compute and `VERCEL_SUPPORT_LARGE_FUNCTIONS=1`. Add the backend variables
   listed in `deploy/.env.vercel.example` through Vercel's environment settings.
   Use `UV_TORCH_BACKEND=cpu` as well as the CPU installation command. A CUDA
   installation fails packaging rather than silently shipping a huge GPU stack.
3. Copy only required runtime values from your private Neon configuration:
   pooled restricted `rag_app` URL, S3 endpoint/region/credentials and bucket
   names. **Do not import the whole `.env.neon` file**: it also contains the
   owner maintenance URL. Add a production OpenRouter key privately. Keep
   payments disabled, wallet enforcement off and public registration enabled.
   The documented one-time $0.001 starter allowance remains unchanged.
4. Set identical model IDs and full revisions for API and worker builds. The
   example records the public revisions tested for the current MiniLM models;
   they are not suitable substitutes if you intentionally use other models.
   Verify the database's existing vector/model compatibility before changing
   these settings. Re-embedding remains a separate operation requiring approval.
5. Confirm the existing Neon schema/storage with
   `python -m scripts.check_neon --env-file .env.neon`. Do not reinitialize an
   existing database. Give preview deployments only isolated validation-branch
   credentials, not production credentials.
6. Rehearse the worker on Linux before enabling it. Start Docker Desktop
   yourself if stopped, then build from the repository root (all arguments below
   are public model identifiers, not secrets):

   ```bash
   docker build --platform linux/amd64 -f Dockerfile.vercel-worker -t rag-worker:validation \
     --build-arg EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
     --build-arg RAG_EMBEDDING_REVISION=1110a243fdf4706b3f48f1d95db1a4f5529b4d41 \
     --build-arg RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2 \
     --build-arg RAG_RERANKER_REVISION=233902d25c440f23af6f7d6e94d2946bac0bee0a \
     --build-arg RAG_RETRIEVAL_MODE=rerank .
   ```

   Prepare ignored `deploy/.env.vercel-validation` from the example using only
   restricted runtime credentials for an isolated validation branch. Queue a
   synthetic file there, then run the image once:

   ```bash
   docker run --rm --env-file deploy/.env.vercel-validation rag-worker:validation python -m scripts.hosted_worker --once
   ```

   Confirm its job, indexed chunks, original bytes and permissions on that same
   branch. No local PostgreSQL container or data volume is needed. A Mac model
   smoke alone does not verify the Linux image, memory budget or startup time.
7. For a new environment, set the worker to zero instances before the first
   API deployment (the validated release now defaults to one). Check HTTPS `/health`
   and model startup. Daemons run only in production during the beta; preview
   deployments and `vercel dev` cannot rehearse the Daemon. Once the image and
   environment are verified, change `daemons.ingestion.instances.sin1` from `0`
   to `1` and redeploy the reviewed backend configuration. Inspect worker logs
   and job status. Never run a validation worker against production accidentally.
8. Import the frontend as its own Vercel project, Root Directory `frontend`.
   Set `VITE_API_BASE_URL=https://api.example.com` and
   `VITE_CREDITS_ENABLED=false`, using your actual API URL. Keep
   `VITE_DIRECT_UPLOADS=false` until the direct-upload activation checks above
   pass. This release enables direct uploads after the cloud upload/storage
   checks, with the provider CORS limitation documented above. Set the custom
   domains, redeploy and verify sign-in, F5 restoration,
   sign-out, multiple uploads, processing, citations and forbidden-user access
   in a browser. No backend rewrite is configured.

A forced kill after the shutdown grace period can still interrupt a job. Staged
input and processing records are retained for existing stale-job recovery;
recovery requires stopped workers and explicit operator approval. A 600-second
grace is not a guarantee every large PDF can finish in time. API request
durations, concurrent model memory, public-signup abuse controls and real
Vercel execution still need validation before public launch. Large multipart
replacement/reindex remains limited as described above.

To stop the Daemon, set its instance count to zero and redeploy; do not delete
jobs, storage objects or tables. Review any dashboard scaling override because
it can override the checked-in instance count. Roll back application code and
its matching model bundle together. The database schema is unchanged.

### Compute verification and changed files

Production release verified October 24, 2026:

| Service | Address / project | Verified state |
| --- | --- | --- |
| Frontend | `https://rag.weichen.space` / `weichen-rag` | Vercel production deployment READY; public HTTPS and static page links. |
| API | `https://api-rag.weichen.space` / `weichen-rag-api` | Production READY; `/health` confirms Neon connectivity. |
| Worker | Backend project's `ingestion` Daemon | One ready/live `sin1` instance, 2 GiB; no scaling override. |

The release was uploaded directly from isolated local source snapshots using
the authenticated Vercel CLI. A connected Git repository is not required;
future local edits are not automatically deployed. Backend and frontend remain
separate projects. Only selected runtime secrets were transferred through
private environment-variable input; owner database credentials, real `.env`,
local documents and caches were excluded from the deployment sources.

Production frontend variables are `VITE_API_BASE_URL=https://api-rag.weichen.space`,
`VITE_DIRECT_UPLOADS=true`, and `VITE_CREDITS_ENABLED=false`. Backend registration
is public, purchases are disabled and new accounts retain the one-time $0.001
starter allowance. No file-count limit was introduced. Sign up at
`https://rag.weichen.space/login?mode=register`.

Read-only public checks confirm protected document/admin/session endpoints deny
unauthenticated requests, credentialed API CORS permits the exact app origin
and rejects an unrelated origin, and unknown frontend paths return 404. No
runtime error clusters appeared in the selected monitoring window. Instance
resource metrics and daemon runtime logs were unavailable through the queried
tools; readiness alone is not a production ingestion or load test. Complete
browser sign-in/F5 restoration and a small real upload manually before inviting
users. No browser was connected for this release's visual checks. Paid answer
generation was not tested.

The prepared root configuration passed Vercel's official JSON Schema. Local
offline packaging produced **174.7 MiB** of selected embedding/reranker models;
both successfully ran real inference from the bundle with database access
blocked and the provider disabled. Tests also send real process termination
signals while synthetic jobs run. No live application records were changed.

The complete Python suite passed **605 tests**, the frontend suite passed
**220 tests**, and `npm run build` passed in an isolated Vercel-mode frontend
build. Existing pytest/AnyIO warnings remain nonblocking. `git diff --check`
passed, and local `.env`/tracked TypeScript build-state checksums are unchanged.

The cloud-built Linux `amd64` worker exposed two release issues: the builder
omitted revision arguments, and serialized weights were readable only by root.
The image now defaults to the selected immutable revisions and assigns its
model bundle to runtime UID 10001. Packaging errors show safe configuration
messages while withholding arbitrary dependency exception details.

The corrected non-root worker completed synthetic PDF and Markdown jobs at
1 CPU / 2 GiB against the isolated validation branch. Deployed preview checks
passed secure-cookie registration/session restoration/sign-out, unauthenticated
and editor/admin denial, a PDF above 4.5 MiB through signed storage upload,
original-PDF byte/range retrieval, physical-page citations, tenant isolation,
and an empty-source answer without paid generation. No production fixtures,
local database imports or paid provider calls were used. Browser visual and
cross-origin cookie checks remain outstanding because no browser was connected.
The bundle size above excludes Python dependencies and is not the final Linux
function/image size.

| Changed files | Purpose |
| --- | --- |
| `vercel.json`, `pyproject.toml`, `.python-version` | Separate root FastAPI project, explicit entrypoint/Python version, CPU build and one ingestion Daemon instance. |
| `Dockerfile.vercel-worker`, `.dockerignore` | CPU-only, non-root worker image with immutable model artifacts and restricted build context. |
| `scripts/prepare_model_bundle.py` | Build selected models, verify dimensions/CPU/revisions and create a completed manifest. |
| `app/model_loading.py`, `app/hosted_runtime.py` | Optional bundle lookup, revision checks, offline hosted startup and fail-closed storage selection. |
| `server.py`, `scripts/hosted_worker.py` | Thin hosted entrypoints reusing the existing API and worker. |
| `scripts/ingestion_worker.py` | Graceful signal handling and interruptible idle/error waits, preserving job processing/retry behavior. |
| `deploy/.env.vercel.example`, `.gitignore`, `.vercelignore` | Required public/secret variable references and protection for generated artifacts/private deployment files. |
| `tests/test_hosted_models.py`, `tests/test_worker_shutdown.py` | Bundle integrity/revision behavior, packaging constraints and real process shutdown regressions. |
| `README.md` | Vercel setup sequence, verification, limitations and rollback instructions. |

## Production release

This section describes the **optional VPS deployment**. The Neon setup above is
the current managed database/storage path; no VPS has been provisioned.

### Selected hosting and topology

Use **Vercel for the React/Vite frontend** and an **Ubuntu 24.04 LTS VPS for the
backend**. No Next.js migration is included. A starting VPS size for a low-traffic
launch is 4 vCPU, 8 GiB RAM and adequate SSD capacity for documents, vectors and
models; this is not a measured throughput guarantee. API and worker each load
models, so monitor RAM and increase capacity if needed. The VPS provider and
actual domains remain operator choices; no server or paid service is provisioned
by this patch.

`deploy/production.compose.yaml` is separate from the Mac rehearsal and root
database Compose files. **Run it only on the new remote host.** It runs:

- Caddy on public TCP 80/443, with automatic HTTPS and persistent certificate state.
- Nginx forwarding backend paths unchanged to FastAPI; the frontend is on Vercel.
- One FastAPI process and one ingestion worker, both running as UID/GID 10001.
- PostgreSQL 17/pgvector on a private Docker network, with a named data volume.
- Separate database owner/migration credentials and a restricted `rag_app` runtime role.

Only Caddy publishes ports. Nginx trusts forwarding headers only from Caddy;
Uvicorn trusts only Nginx's fixed private IP, preserving HTTPS cookie and Origin
checks. Networks use `172.30.72.0/24` and `172.30.73.0/24`; check for conflicts
before launch. If changing them, update Compose, Nginx trust addresses and
Uvicorn's allowlist together. Do not put another CDN/proxy in front without
reviewing its trusted-proxy configuration.

Nginx limits auth requests to 5/minute/IP with burst 5, and API traffic to
120/minute/IP with burst 30. It returns 429 on excess; shared-office users can
share this allowance. Registration additionally counts eight attempts/15 minutes
in the API. All application request access logs are disabled at the proxies;
container log rotation is configured. TLS behavior follows
[Caddy's HTTPS documentation](https://caddyserver.com/docs/automatic-https), and
forwarded identities follow [Caddy's proxy rules](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)
and [Uvicorn's trusted-proxy settings](https://uvicorn.dev/settings/).

The browser calls `https://api.example.com` directly using the public build-time
`VITE_API_BASE_URL`; there is no Vercel/API rewrite. The existing local development
proxy is unchanged. This backend remains one server without high availability.

### Remote preparation

1. Provision the VPS using an SSH key. Configure its provider/host firewall:
   allow TCP 22 only from your administration IP and TCP 80/443 publicly. Do not
   open PostgreSQL, FastAPI or rehearsal ports. Install Docker Engine and its
   Compose plugin using the [official Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/).
2. Point an `A` record for the API hostname (e.g. `api.example.com`) to the VPS. Add `AAAA` only
   if IPv6 is configured. Use direct DNS initially. Caddy needs public DNS and
   access to ports 80/443 for certificates. No domain/server has been provisioned
   by the code changes.
3. Check out the reviewed release on the remote server. Keep a matching Git
   commit and built image tags for rollback. Create persistent private directories:

   ```bash
   sudo install -d -m 700 -o 10001 -g 10001 /srv/rag-data/spool /srv/rag-data/pdfs /srv/rag-data/model-cache
   cp deploy/.env.production.example deploy/.env.production
   chmod 600 deploy/.env.production
   ```

4. Edit that **remote, ignored** environment file privately. Set `RAG_PUBLIC_HOST`
   to the API hostname without scheme/path, and `RAG_ALLOWED_ORIGINS` to the
   exact frontend origin, e.g. `https://app.example.com`. Also set the
   ACME email, release tag, independent owner/runtime DB passwords and their
   URL-encoded connection URLs, and a dedicated OpenRouter key with an operator
   spending limit. Copy the actual embedding/reranker configuration used for
   existing vectors. Never change embedding models merely to deploy.
   Configure support staff IDs only after checking the imported user identities.
   Root/local `.env` is neither uploaded nor changed by this configuration.
5. Define a local shell helper **on the remote host** and validate/build:

   ```bash
   rag_compose() { docker compose --env-file deploy/.env.production -f deploy/production.compose.yaml "$@"; }
   rag_compose config --quiet
   rag_compose build
   rag_compose up -d postgres
   ```

   Do not omit `--quiet` when validating configuration: rendered Compose output
   contains secrets. Builds need network access for dependencies and CPU model
   libraries. Initial model downloads occur when API/worker start and persist in
   `/srv/rag-data/model-cache`. Record the resolved image digests/dependency versions
   and scan the built images before opening traffic; base tags and Python version
   ranges currently resolve at build time, not from a Python lockfile.

### Database and private-file cutover — requires approved maintenance

Do not run these operations against the Mac's existing database or overwrite a
remote database containing data. Back up the existing database **and private PDF
directory** first. Pause uploads/writes, let processing finish, and stop existing
API/workers during the consistent snapshot/cutover. Keep the Mac stack and its
volume as rollback sources.

For an existing installation, restore the reviewed PostgreSQL custom-format dump
into the **fresh remote** database as `rag_owner`, with `pg_restore --no-owner
--no-privileges --exit-on-error`. Review any schema/extension conflict rather
than adding destructive cleanup flags. Copy private PDFs and pending spool files
to their corresponding `/srv/rag-data/` directories over an encrypted channel;
preserve UUID/document filenames and set ownership 10001:10001, directories
0700 and private files 0600. Do not make uploads web-accessible. Inspect recovered
processing jobs using the existing dry-run recovery workflow; do not blindly
requeue claims or run both the Mac and production worker on one database.

Preview the migration plan using the maintenance image with owner credentials:

```bash
rag_compose --profile maintenance run --rm -T migrate
# Approved empty installation only:
rag_compose --profile maintenance run --rm -T migrate python -m scripts.setup_database --apply
# Approved imported/existing installation, after backup:
rag_compose --profile maintenance run --rm -T migrate python -m scripts.setup_database --apply --upgrade
```

The single runner uses the existing migration order and separate transactions
documented above. It never seeds or resets data, and no new schema is introduced
by this deployment update. The earlier starter-allowance migration must be present
before startup: missing accounting storage fails closed. These commands have
been prepared, not run against your database. The database
initialization script installs pgvector, a non-owner runtime role and default
grants for tables/sequences created by `rag_owner`. After restoring, confirm
runtime grants before traffic; foreign ownership/ACLs from an old dump must not
be carried into the new runtime role. Existing default-privilege setups are not
retroactively changed by mounting the initialization script on an existing volume.

### Verification and opening traffic

```bash
rag_compose run --rm -T api python -m scripts.check_production
rag_compose up -d api worker gateway caddy
rag_compose ps
python3 -m scripts.smoke_deployment --url https://api.example.com --api-only
```

The preflight performs read-only schema/role/storage/configuration checks and
never prints credentials. Production API/worker startup runs it automatically
and refuses to start on failure. It does not download models or verify provider billing.
Allow model warmup to finish and inspect sanitized service logs. Validate with
approved disposable accounts/documents: public signup without a code, invited
signup, F5 cookie restoration, another tenant's access denial, multiple PDF/TXT/MD
uploads through the worker, a citation PDF, support, and Credits unavailability.
Verify the starter allowance against reported usage and unknown-cost holds; no
live paid calls are made by automated tests. Public signup has no email proof,
password-recovery delivery or CAPTCHA, and unlimited uploads require disk/queue
monitoring. Resolve those operational limits before widening access.

### Vercel frontend setup

1. Import the reviewed Git repository into Vercel. Set **Root Directory** to
   `frontend`, framework to **Vite**, install command to `npm ci`, build command
   to `npm run build`, output directory to `dist`, and Node.js to 22.x.
2. Set the following **public build variables** in the production environment:

   ```dotenv
   VITE_API_BASE_URL=https://api.example.com
   VITE_CREDITS_ENABLED=false
   ```

   Never add OpenRouter keys, database URLs, API keys or session secrets to
   Vercel frontend variables. These values are bundled into browser JavaScript.
   Redeploy after changing them. A Vercel build refuses a missing/non-HTTPS
   backend URL instead of silently shipping the local proxy fallback.
3. Add `app.example.com` as the frontend custom domain using the DNS records
   shown in the Vercel dashboard. The API remains `api.example.com` on the VPS.
   Match the backend's `RAG_ALLOWED_ORIGINS` exactly, including the scheme.
4. Deploy. `frontend/vercel.json` enables `cleanUrls`; the build generates public
   HTML shells for each application path and a 404 page from one shared route
   list. `/documents`, `/login` and other direct links therefore work without
   rewrite rules. These shells contain no protected data; backend authorization
   and existing frontend route guards still apply. See
   [Vercel's cleanUrls configuration](https://vercel.com/docs/project-configuration/vercel-json#cleanurls).
5. On the **custom domain**, test direct links and F5 on `/documents`, password
   sign-in/session restore/sign-out, Back/Forward, uploads and PDF viewing.
   Check desktop/mobile layouts and the browser Network panel for direct HTTPS
   API calls, successful preflights, and no requests to Vercel's `/api` path.
   Default preview domains are not configured for password sessions; do not
   add a wildcard allowlist to enable them.

### Backups, monitoring and rollback

Enable host backups and schedule encrypted **off-server** copies of PostgreSQL
dumps plus private PDFs and necessary spool files; a disk snapshot alone does
not establish a consistent application restore. Restrict backups to operators,
define retention and test recovery on a separate disposable server before launch.
After draining processing and pausing writes, an operator can take a backup:

```bash
umask 077
archive_dir=/secure-backups/RELEASE_TIMESTAMP
mkdir -p "$archive_dir"
rag_compose exec -T postgres pg_dump -U rag_owner -d ragdb --format=custom --no-owner --no-privileges > "$archive_dir/database.dump"
sudo tar -C /srv/rag-data -czf "$archive_dir/private-files.tgz" pdfs spool
```

Encrypt and transfer these archives to separate storage; verify restore, then
resume writes. Monitor disk, RAM, CPU, TLS expiry, health, failed/stale ingestion,
provider spend and unknown-cost reservations. Configure external uptime checks
and real alert recipients before launch. No backup schedule or alerts are created
by this patch.

Rollback uses the prior matching API/worker image tag and prior Vercel deployment
after pausing writes. Restore matching origin settings when rolling back domains.
Keep the additive allowance table; never drop ledgers or reset volumes. Before
rolling back to a version that lacks starter enforcement, turn off public
registration and generation at the gateway, since that version can bypass trial
limits. Restore data only through a reviewed recovery operation. Never use
`docker compose down -v` as a release or rollback command.

### Deployment update inventory and validation

| Changed files | Purpose |
| --- | --- |
| `frontend/src/apiConfig.ts`, `frontend/src/api.ts` | Validated public backend URL for every JSON, upload and PDF request; credentials included for direct cookie transport. |
| `frontend/.env.example` | Documents the public backend URL and disabled Credits switch. |
| `frontend/src/page-routes.json`, `frontend/src/navigation.ts` | Shared application URL list for navigation and generated static pages. |
| `frontend/scripts/prepare-static-routes.mjs`, `frontend/package.json`, `frontend/vercel.json` | Build public route shells and a 404 page; enable Vercel clean URLs without rewrite rules; reject unsafe/missing Vercel backend URL. |
| `frontend/src/api.test.ts`, `frontend/scripts/prepare-static-routes.test.mjs` | Direct JSON/upload/PDF transport, invalid URL rejection, static deep links and path validation. |
| `app/browser_auth.py`, `app/main.py`, `app/settings.py`, `.env.example` | Exact-origin credentialed CORS and trusted same-site browser checks; retain CSRF headers and Secure/HttpOnly/SameSite=Strict cookies. |
| `scripts/setup_database.py`, `tests/test_setup_database.py` | One offline-preview-first schema runner with explicit apply/upgrade flags, concurrency lock, ordered existing migrations and mocked failure coverage. |
| `deploy/production.compose.yaml`, `deploy/nginx.production.conf`, `deploy/Caddyfile`, `deploy/.env.production.example` | Backend-only VPS stack, unchanged API paths, HTTPS API host and explicit frontend origin; maintenance defaults to preview. |
| `deploy/Dockerfile.web` | Keeps the optional existing frontend rehearsal image compatible with the new build and public backend variable. |
| `scripts/check_production.py`, `tests/test_production_preflight.py` | Require valid HTTPS frontend origins alongside existing read-only runtime checks. |
| `scripts/smoke_deployment.py`, `tests/test_deployment_smoke.py` | Add direct-API smoke mode while retaining the localhost rehearsal checks. |
| `tests/test_browser_auth.py` | Preflight, direct login/restore/logout, cookie protection, unauthorized origins, CSRF, tenant identity and bearer precedence. |
| `README.md` | Vercel/VPS setup, one schema command, DNS/origin requirements, validation and rollback. |

Deployment preparation verified on October 22, 2026: **529 Python tests passed**
with live DB access blocked and startup model loading disabled; **215 frontend
tests passed**. The full `npm run build` passed in Vercel mode in an isolated
temporary copy. Generated route files match the public shell and the bundle uses
the configured direct backend URL; missing/unsafe Vercel configuration fails.
Production Compose validates using synthetic credentials, and `git diff --check`
passes. No dependencies were added and tracked TypeScript build-state files are
unchanged. Docker is stopped, so container builds/startup, live migration/grants,
DNS/TLS, browser CORS/cookie behavior and restore remain unverified. No deployment,
live database mutation, real `.env` edit or application-data changes were made.

### Earlier application release changes

| Files | Purpose |
| --- | --- |
| `app/account_auth.py` | Isolated public editor workspaces, preserved invitation rules, atomic signup provisioning and attempt throttling. |
| `app/main.py` | Optional invitation contract, rejected tenant/role injection and shared throttling for browser/bearer signup. |
| `app/settings.py`, `.env.example` | Public-registration configuration. The real `.env` is unchanged. |
| `app/starter_allowances.py`, `app/credit_budgets.py` | One-time $0.001 policies, all-time usage/hold accounting and appropriately sized atomic reservations. |
| `scripts/migrate_starter_allowances.py` | Additive, repeatable empty policy table; not applied to a live database. |
| `frontend/src/App.tsx`, `frontend/src/navigation.ts`, `frontend/src/features.ts` | Public signup, disabled Credits navigation/direct rendering and safe post-login destinations. |
| `frontend/src/LandingPage.tsx` | Public-signup FAQ and CTA copy. |
| `frontend/src/vite-env.d.ts`, `frontend/.env.example` | Public build-switch types and disabled-by-default configuration. |
| `frontend/src/App.test.tsx` | Public/signup invitation compatibility and Credits disabled-route/navigation regressions. |
| `deploy/Dockerfile.web` | Explicit Credits build switch and bundled public assets/notices. |
| `deploy/Dockerfile.production-api` | Separate CPU-inference production image and non-root runtime. |
| `deploy/production.compose.yaml`, `deploy/.env.production.example` | Remote-only services, private networks/storage, explicit secrets and disabled purchases. |
| `deploy/Caddyfile`, `deploy/nginx.production.conf` | Automatic HTTPS, trusted forwarding, shared rate limits and private response headers. |
| `deploy/init-production-db.sh` | Fresh-remote initialization of pgvector, restricted runtime role and owner default grants. |
| `scripts/check_production.py`, `scripts/production_entrypoint.py` | Read-only preflight and mandatory API/worker startup checks. |
| `tests/test_starter_allowances.py` | Transaction rollback, tenant/role isolation, one-time/concurrent accounting, proxy transport and uploads beyond three files. |
| `tests/test_production_preflight.py` | Read-only behavior, migration presence, runtime permissions, redacted failures and startup gating. |
| `tests/test_browser_auth.py`, `tests/test_credit_budgets.py`, `tests/test_credits.py` | Updated mock fixtures for the shared throttle and existing users without signup policies. |
| `.gitignore`, `README.md` | Ignore remote secrets; document configuration, migration, cutover, backups and rollback. |

The earlier application release was validated on October 22, 2026: **501 Python tests passed**, with live DB access
blocked and startup model loading disabled; **205 frontend tests passed**;
`npm run build` passed in an isolated copy under `/private/tmp`, preserving
tracked TypeScript build-state files. Production Compose parsed with synthetic
values, the initialization shell passed syntax validation, and `git diff --check`
passed. Existing AnyIO/pytest warnings are nonblocking. Docker was not running,
so container builds/startup, live PostgreSQL grants/migration, TLS issuance,
provider billing, actual backup/restore and desktop/mobile browser checks remain
unverified. No application data or historical reservations were altered. The
pre-existing deleted PDF patch file was left untouched.

## Backups and rollback

Before approved schema/data/model maintenance, stop conflicting API/worker
activity and take a PostgreSQL backup using a trusted local operator connection,
for example a custom-format `pg_dump`. Do not put credentials in command-line
history or print a resolved connection URL.

Back up the corresponding private original-PDF directory and, when preserving
pending jobs, staged input with a consistent stopped queue. Preserve private
configuration securely outside Git. Model caches can be downloaded again, but
keeping the correct weights helps offline startup/rollback. A database backup
alone does not preserve original files.

Test restores in an isolated database/storage location before relying on the
backup. Restoring over live data needs separate approval. Verify documents,
vector-model compatibility, tenant/ACL isolation, PDFs, conversations and queue
state before resuming.

Migrations are generally additive and can remain during an application rollback;
review actual constraints/backfills and code compatibility. Do not drop usage,
budget, conversation or feedback history as a rollback shortcut. Do not revert
to an older worker that ignores retry scheduling while retries remain pending.

`scripts.reindex_samples --confirm` is a destructive demo maintenance tool,
not normal ingestion or upgrade: it checks the four demo TXT identities, deletes
their owned records and recreates them. It can change IDs and cascade references.
Use only on approved disposable samples with a backup, never a real corpus.

Code rollback should use the matching reviewed Git change without overwriting
other uncommitted work. Embedding-model rollback additionally requires compatible
stored vectors; see [Changing embedding models safely](#changing-embedding-models-safely).
Never reset Docker volumes, bulk-delete reservations, or erase live files to
resolve an application error.

## Troubleshooting

| Symptom | Checks / action |
| --- | --- |
| API says address already in use / errno 48 | Inspect `lsof -nP -iTCP:8000 -sTCP:LISTEN`. Reuse the existing API or stop its owning terminal with Ctrl-C before restarting. Do not kill an unidentified process. A different API port also needs matching frontend proxy configuration. |
| Frontend port 5173 occupied | Vite uses a strict port; stop/reuse the existing frontend or explicitly configure a matching development origin. |
| Database unavailable / connection refused | Verify the existing PostgreSQL process/container, host port, network and private DATABASE_URL. Container loopback is not the database container. |
| Missing table/column or vector extension | Review schema and the migration order; schedule approved maintenance rather than dropping/recreating the database. |
| F5 returns to sign-in | Password cookie sessions should restore until expiry/revocation; API-key sign-in is deliberately memory-only. Check hostname consistency, cookie blocking, session expiry and same-origin/HTTPS proxy configuration. |
| 401 / 403 | Check active credentials, current role and tenant. Do not bypass authorization or expose private files. |
| 429 on ask | Review tenant/user pause/limits, current-month spending and reservations. Missing-cost holds require billing reconciliation. Search can still work. |
| Ask returns 503 | Check generation provider/key/model settings, network and application error. A possible paid attempt can retain a hold; avoid blind retries. |
| Upload stays queued | Start the separate worker with the same database/model/spool/PDF paths; inspect safe worker logs and admin ingestion health. |
| Processing heartbeat is stale | Investigate worker/database availability. Use dry-run recovery, and stop all workers before approved recovery. |
| PDF over 300 pages fails | Current cap is 1,000 physical pages and 50 MiB. Restart API and worker after updating code; check text extraction, encryption, size and the actual failed-job reason. |
| Original PDF unavailable | Check current access and stored bytes. Older indexed PDFs can lack originals; authorized replace/reindex can repair them. Do not use a public filesystem bypass. |
| Chinese search weak or no useful results | Confirm a text layer, model/vector compatibility, multilingual configuration, current chunking and retrieval mode. Evaluate real authorized examples; literal matching is not translation. |
| Models appear to reload every start | Loading cached weights into RAM/MPS is expected per process. Confirm the local-cache log, stable HF_HOME and same OS user. |
| Model download/cache error | Check selected model, cache permissions, network/proxy and offline flags. Offline mode requires complete cached files. Do not change embedding models as a cache workaround. |
| Dashboard shows stale data | Retry the affected section. Ordinary errors preserve marked stale content; authorization failures clear protected data. |
| Failed-upload removal returns 503 | Staged-file cleanup failed; the job is retained. Repair storage access before retrying; do not delete unrelated spool files. |

## Current limitations and improvement areas

Implemented features include authentication/ACLs, PDFs/citations, hybrid search,
reranking, background processing, accounts/admin, persistent history,
collections, feedback, usage and budgets. They are not future milestones.

Remaining work includes:

- Verified email, password reset, MFA/SSO, multi-host rate limiting,
  device/session metadata, and richer API-key lifecycle controls.
- Independent database row-level security (the remote release supplies runtime roles);
  current tenant enforcement is application SQL plus selected tenant constraints.
- Malware scanning, OCR, document classification/retention, encrypted storage
  policy, object storage and tested backup/disaster recovery.
- Representative multilingual/retrieval evaluation, large-corpus query
  profiling, database indexes as justified by measurements, and load testing.
- Durable shared telemetry, automated provider-billing reconciliation and
  generation idempotency.
- Representative follow-up quality evaluation and paginated long RAG chat history.
- Next.js migration, public-signup abuse protection, and payment re-enablement
  are separate follow-ups; the existing public landing page is implemented.

Answer citations are references to retrieved excerpts, not machine-verified
truth. Feedback is sentiment, not accuracy. Account deactivation does not remove
stored data. No feature should be interpreted as a guarantee of production
security or a hard provider spending cap.

## Former milestone guides

The former `docs/*.md` files now point to these canonical sections. Their
historical patch names and install order should not be used as current setup
instructions.

| Former guide | Current README sections |
| --- | --- |
| M7 — Security | [Authentication and authorization](#authentication-and-authorization), [Fresh installation and upgrades](#fresh-installation-and-upgrades) |
| M8 — React UI | [Using the application](#using-the-application), [Daily startup](#daily-startup) |
| M9 — Background ingestion | [Document ingestion and PDF storage](#document-ingestion-and-pdf-storage), [Worker operations and recovery](#worker-operations-and-recovery) |
| M9.2 — Original PDFs | [Original PDFs and citations](#original-pdfs-and-citations) |
| M9.3 — Worker reliability | [Worker operations and recovery](#worker-operations-and-recovery) |
| M9.4 — Observability | [Audit log and observability](#audit-log-and-observability) |
| M10 — Accounts/admin | [Authentication and authorization](#authentication-and-authorization), [Using the application](#using-the-application) |
| M10 usage | [Usage and credit budgets](#usage-and-credit-budgets) |
| M10.2 — Budgets | [Monthly credit guardrails](#monthly-credit-guardrails) |
| M10.3 — Conversations | [Saved conversations](#saved-conversations) |
| M10.4 — Knowledge bases | [Knowledge bases](#knowledge-bases) |
| M10.5 — Feedback | [Answer feedback](#answer-feedback) |

`AGENTS.md` remains the contributor/agent instruction file.
`CODEX_HANDOFF.md` supplies historical context; the checked-out code and tests
take precedence over older milestone claims.

Project references:
[pgvector](https://github.com/pgvector/pgvector),
[pgvector Python](https://github.com/pgvector/pgvector-python),
[Sentence Transformers](https://www.sbert.net/),
[FastAPI](https://fastapi.tiangolo.com/),
[multilingual E5](https://huggingface.co/intfloat/multilingual-e5-small), and
[the multilingual reranker](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1).
