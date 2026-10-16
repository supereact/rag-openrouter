# Milestone 10 — Accounts, sign-in, and tenant administration

This is a **localhost development implementation**, not a production SSO/identity service. Continue using `127.0.0.1` until HTTPS, centralized rate limiting, CSRF/session design, a production identity provider (OIDC), stronger audit controls, and security review are in place.

## Design

- Existing `rag_...` administrator/reader/editor API keys remain compatible and are still checked in PostgreSQL per request.
- Password sign-in issues a new `rags_...` random bearer token, stored as a SHA-256 digest in PostgreSQL; sessions expire after **12 hours** and are revoked at logout, account disable, and role change.
- Passwords are salted PBKDF2-HMAC-SHA256 hashes (600,000 iterations). Plaintext passwords are not stored. Use a production IdP for public use.
- **Public, uninvited sign-up is intentionally disabled.** A tenant admin creates a single-use, email-bound reader/editor invitation valid for 48 hours. The recipient enters the code, their email and username and a password on the Sign up screen. No emails are sent automatically: securely send the code yourself. Admin invitations cannot create an admin.
- Admins may view tenant metrics, list users, update roles/active state, revoke browser sessions, and generate invitations. They cannot change their own role/status or remove the last active admin.
- API-key-only legacy accounts have no email/password until configured with the trusted operator CLI.
- No schema changes to `documents`, `chunks`, embeddings, ACLs, or PDFs.
- Tenant filters are evaluated server-side. Never use client-supplied `tenant_id` for auth.

## Installation

1. **Back up** `ragdb` using `pg_dump` before running SQL migrations:

```bash
mkdir -p backups
docker exec enterprise-rag-postgres pg_dump -U raguser -d ragdb -Fc > backups/ragdb-before-m10.dump
```

2. Apply the Git patch after `git apply --check`.
3. Stop FastAPI and the background worker. Run the additive migration:

```bash
source .venv/bin/activate
python -m scripts.migrate_accounts
```

4. Configure a password for the existing local administrator **without typing it on the command line**. This keeps your old API key usable:

```bash
python -m scripts.set_user_password --tenant local --user admin --email admin@example.com
```

Use an email you control and enter a long, unique password at the secure prompt.

5. Restart FastAPI and the worker. Run `npm test` and `npm run build` from `frontend/`, then `npm run dev`.

## Manual acceptance tests

- Visit the frontend and select **Email sign in**. Log in as `admin@example.com` with your new password. Verify the **Dashboard** and **User Management** tabs.
- From **User Management**, create an invitation for `test-reader@example.com`, role `reader`. Copy the one-time code and enter it on **Sign up** in a separate browser tab. Verify `/me` returns role `reader` and the matching tenant ID.
- Log in as the reader and confirm there is **no Dashboard or User Management navigation**, and the admin APIs return **403**.
- Verify the reader cannot upload or view unshared private documents. Share a disposable document through the existing Documents page, then verify the reader sees it.
- As admin, change the reader to editor; the reader's existing `rags_` session should return **401**, and signing in again should reflect `editor`.
- Disable that user; both password login and legacy API keys for that user should fail. Re-enable the user and sign in again.
- Test `POST /auth/logout`: an `rags_` session should be revoked. Legacy API keys remain valid on logout (the frontend forgets them).
- Try an invalid or reused invitation; registration must fail. Ensure an invitation cannot create an admin.
- Verify that two different tenant admins cannot list or alter each other's users.

## Endpoints

| Endpoint | Access |
|---|---|
| `POST /auth/login` | Public (email/password, rate-limited per process) |
| `POST /auth/register` | Public **with valid invitation** |
| `POST /auth/logout` | Authenticated; revokes password session |
| `GET /admin/dashboard` | Tenant admin |
| `GET /admin/users` | Tenant admin |
| `PATCH /admin/users/{id}` | Tenant admin |
| `POST /admin/users/{id}/revoke-sessions` | Tenant admin |
| `GET /admin/invitations` | Tenant admin (no secret invitation codes returned) |
| `POST /admin/invitations` | Tenant admin (one-time plaintext code returned) |

## Security / operational limitations

- Authentication is **local-development only**. Never expose this system to the public Internet as-is.
- No verified email delivery, password reset flow, SSO, MFA, cross-process rate limiting, external Redis session store, or CSRF-secure cookie session implementation.
- Credentials are passed over the local Vite proxy; production deployment requires HTTPS everywhere and a professional identity provider.
- Browser access tokens stay in JavaScript memory, meaning page refresh signs users out. Do not move tokens to `localStorage`.
- CLI/API-key administrator bootstrap is required and is deliberately not provided via anonymous signup.
- The login throttle is in-process and not appropriate behind multiple workers. Use a shared limiter and audit monitoring for production.
- PostgreSQL's application role has broad permissions in this MVP. Apply least privilege and Row Level Security before multi-tenant production use.
- User management doesn't delete users or transfer document ownership. Disable accounts to preserve history and existing documents.

## Rollback

1. Stop FastAPI, worker and frontend, and revert the patch with `git apply -R` if needed.
2. The additive SQL columns/tables can remain; previous code ignores them, but **do not roll back schema or migrate backward without a tested plan**.
3. Keep your `pg_dump` backup secure; backups contain password hashes, email addresses and document contents.
