# Milestone 8 — Local React Chat UI

A new **frontend/** React + TypeScript + Tailwind application is added. All existing
Python endpoints, document IDs, security policies, and vector stores are preserved.
The only backend change is `GET /me` for displaying the authenticated username,
role, and tenant ID; this endpoint never returns the API key.

## Requirements

- Python FastAPI running on `http://127.0.0.1:8000`
- Existing PostgreSQL container and Milestone 7 migration
- Node.js **20.19+** or **22.12+** and npm (check `node -v`)
- Your previously generated `rag_...` API key; **never put it in `.env` for Vite**

## Run on your Mac

```bash
cd ~/work/enterprise-rag-openrouter
source .venv/bin/activate
python -m pytest tests/test_me.py -v
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In a **second terminal**:

```bash
cd ~/work/enterprise-rag-openrouter/frontend
npm install
npm test
npm run build
npm run dev
```

Open **http://127.0.0.1:5173**. Enter the same API key you used in Swagger.
Vite proxies only `/api/*` to FastAPI at localhost port 8000; there is no CORS
change, and all backend authorization checks continue to run.

## Manual verification

1. No key / invalid key: sign-in fails; no documents are displayed.
2. Admin: sign in, ask about NIST phases, expand the PDF source page 31.
3. Admin/editor: select Documents, upload a `.txt` or `.md` file, see the indexed document.
4. Admin/editor: share a document with a same-tenant username; verify the reader gains access.
5. Reader: view only shared docs, ask a question, no upload/share/delete controls.
6. Cross-tenant reader: cannot see another tenant's private docs.
7. Admin/editor: reindex an owned PDF **using the identical filename**; verify new source pages.
8. Delete a **disposable test file only**; confirm it disappears and is no longer retrievable.
9. Sign out and refresh: you must enter your key again. The app does not persist keys or chat transcripts.

## Security and constraints

- **Local developer UI only**. Do not expose ports 5173 or 8000 to the internet.
- The API key lives only in React component memory. Do not copy it into frontend
  source, Vite env vars, local/session storage, log statements, or URL query params.
- The bearer key is sent to a **same-origin `/api` path**. Vite's local dev server
  forwards those requests to FastAPI. This is a development proxy, not a
  production authentication architecture.
- Frontend role-based hiding is for usability; **the backend remains authoritative**.
- There is **no server-side conversation storage**. Chat resets on refresh/signout.
- Sources link to the **retrieved excerpt inside the page**, not the original PDF.
  The backend does not yet retain or serve original PDF bytes, so there is no PDF viewer.
- Upload stays limited by existing backend file/page/text settings. Large ingestion
  runs synchronously and may make the request slow.
- API keys are sensitive. Browser extensions and compromised pages may be able to
  access in-memory secrets. For production use HTTPS + SSO/OIDC, proper session
  management, RLS, rate limiting, malware scanning, and secure file storage.

## Frontend tests

```bash
cd frontend
npm test      # Vitest API client and UI tests
npm run build # TypeScript + Vite production compilation smoke check
```

Python tests: `python -m pytest tests/ -q` from project root.
