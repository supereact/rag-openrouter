"""Local FastAPI application with tenant-scoped API key security."""
import asyncio
import logging
from time import perf_counter
from uuid import uuid4
from uuid import UUID
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date
from typing import Literal

import psycopg
from fastapi import FastAPI, HTTPException, File, UploadFile, Depends, Response, Request, Query
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, JSONResponse

from app.db import db_connection
from app import browser_auth
from app import audit_log
from app.ingestion_jobs import queue_upload, list_jobs, get_job, job_health, remove_failed_job
from app.document_library import list_library
from app.model_warmup import warmup_local_models
from app.observability import measure, reset_llm_usage, save_request_usage, snapshot, peek_llm_usage
from app.original_pdfs import store_pdf, remove_pdf, authorized_pdf
from app.security import Principal, require_principal, require_editor, bearer
from app import account_auth, settings, usage_ledger, credit_budgets, conversations, knowledge_bases, answer_feedback, document_access
from app.file_ingestion import MAX_FILE_BYTES, extract_document, extract_pdf_pages
from app.schemas import (
    AskResponse, IngestRequest, IngestResponse, SearchRequest, SearchResponse,
    ShareRequest, IngestionJob, EnqueuedJob, DocumentAccessResponse, DocumentAccessUpdate, DocumentLibrary, AuditLog,
)
from app.services import (
    ingest_document, ingest_pdf_pages, search_documents, answer_question,
    share_document, delete_document, visible_documents, assert_document_writable,
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Runs once in each Uvicorn worker before the API begins serving requests.
    # The model loaders are cached, so later requests reuse these instances.
    await asyncio.to_thread(warmup_local_models)
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Enterprise RAG Knowledge Assistant — Security MVP",
    version="0.7.0",
    description=(
        "API keys, tenant-scoped retrieval and per-document sharing. "
        "Local security MVP; TLS, external identity, rate limiting, and "
        "production-ready deployment controls are still required."
    ),
)


_http_logger = logging.getLogger("rag.http")


@app.middleware("http")
async def request_id_log(request: Request, call_next):
    """Correlate local access logs; never log URLs, query strings, or content."""
    request_id = uuid4().hex
    start = perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        route = request.scope.get("route")
        template = getattr(route, "path", "<unmatched>")
        _http_logger.info(
            "request_id=%s method=%s route=%s status=%s duration_ms=%.2f",
            request_id, request.method, template, status,
            (perf_counter() - start) * 1000,
        )


@app.get("/health")
def health():
    try:
        with db_connection() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "database": "connected"}
    except (psycopg.Error, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@app.post("/documents", response_model=IngestResponse)
def add_document(body: IngestRequest, principal: Principal = Depends(require_editor)):
    try:
        doc_id, count, exists = ingest_document(body.title, body.text, principal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return IngestResponse(document_id=doc_id, chunk_count=count, already_exists=exists)


@app.post("/search", response_model=SearchResponse)
def search(body: SearchRequest, principal: Principal = Depends(require_principal)):
    scope = ({'knowledge_base_id': body.knowledge_base_id}
             if body.knowledge_base_id is not None else {})
    with measure(principal.tenant_id, "search", "retrieval"):
        hits = search_documents(body.question, body.top_k, principal=principal, **scope)
    return SearchResponse(question=body.question, hits=hits)


@app.post("/ask", response_model=AskResponse)
def ask(body: SearchRequest, principal: Principal = Depends(require_principal)):
    return _run_ask(body, principal)


def _run_ask(body: SearchRequest, principal: Principal) -> AskResponse:
    if body.knowledge_base_id is not None:
        # Prevent spending any budget on a non-existent or foreign collection.
        knowledge_bases.assert_tenant_collection(principal, body.knowledge_base_id)
    # Acquire the database-backed allowance BEFORE contacting OpenRouter.
    # This serializes concurrent budget checks across server processes.
    reservation = None
    if settings.LLM_PROVIDER == 'openrouter':
        reservation = credit_budgets.reserve_request(principal)
    reset_llm_usage()
    generation_attempted = False
    try:
        scope = ({'knowledge_base_id': body.knowledge_base_id}
                 if body.knowledge_base_id is not None else {})
        with measure(principal.tenant_id, "ask", "retrieval"):
            hits = search_documents(body.question, body.top_k, principal=principal, **scope)
        with measure(principal.tenant_id, "ask", "generation"):
            # Empty retrieval returns a local answer without contacting the provider.
            generation_attempted = bool(hits)
            answer = answer_question(body.question, hits)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        # Reservations also settle on failed requests. If provider cost was
        # unreported, the allowance stays held for operator review.
        try:
            usage = peek_llm_usage()
            if settings.LLM_PROVIDER == 'openrouter':
                try:
                    if reservation is not None and not generation_attempted:
                        credit_budgets.release_before_generation(reservation, principal)
                    elif reservation is not None:
                        credit_budgets.settle_request(reservation, principal, settings.OPENROUTER_MODEL, usage)
                    elif usage:
                        usage_ledger.record_openrouter_usage(principal, settings.OPENROUTER_MODEL, usage)
                except Exception:
                    # A failed settlement leaves its reservation held; do not
                    # silently release credit or leak prompts into application logs.
                    _http_logger.error('OpenRouter accounting settlement failed; check credit reservations')
        finally:
            save_request_usage(principal.tenant_id)
    return AskResponse(question=body.question, answer=answer, sources=hits)


@app.post("/documents/upload", response_model=IngestResponse)
def upload_document(file: UploadFile = File(...), principal: Principal = Depends(require_editor)):
    """Upload a document into the existing RAG pipeline (local MVP only)."""
    try:
        # Read at most limit + 1 so oversized files can be rejected.
        data = file.file.read(MAX_FILE_BYTES + 1)
        title, text = extract_document(file.filename or "", data)
        if title.lower().endswith(".pdf"):
            pages = extract_pdf_pages(title, data)
            doc_id, count, exists = ingest_pdf_pages(title, pages, principal)
            store_pdf(doc_id, data)
        else:
            doc_id, count, exists = ingest_document(title, text, principal)
        return IngestResponse(
            document_id=doc_id,
            chunk_count=count,
            already_exists=exists,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        file.file.close()


@app.post("/documents/{document_id}/reindex-pdf", response_model=IngestResponse)
def reindex_pdf(document_id: int, file: UploadFile = File(...),
                principal: Principal = Depends(require_editor)):
    """Replace PDF chunks in one DB transaction, preserving document ID.

    Development-only: authenticate before public deployment.
    """
    try:
        assert_document_writable(principal, document_id)
        data = file.file.read(MAX_FILE_BYTES + 1)
        title = file.filename or ""
        pages = extract_pdf_pages(title, data)
        doc_id, count, exists = ingest_pdf_pages(
            title, pages, principal, replace_document_id=document_id
        )
        store_pdf(doc_id, data)
        return IngestResponse(document_id=doc_id, chunk_count=count, already_exists=exists)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        file.file.close()


@app.get("/me")
def current_user(principal: Principal = Depends(require_principal)):
    """Return only public identity fields; never return API key material."""
    return {
        "user_id": principal.user_id,
        "tenant_id": principal.tenant_id,
        "username": principal.username,
        "role": principal.role,
    }


@app.get("/documents")
def list_documents(principal: Principal = Depends(require_principal)):
    return {"documents": visible_documents(principal)}


@app.get('/documents/library', response_model=DocumentLibrary)
def document_library(page: int = Query(1, ge=1), page_size: int = Query(20, ge=20, le=100),
                     q: str = Query('', max_length=200),
                     status: Literal['indexed', 'queued', 'processing', 'failed'] | None = None,
                     file_type: Literal['pdf', 'md', 'txt'] | None = None,
                     principal: Principal = Depends(require_principal)):
    if page_size not in (20, 50, 100):
        raise HTTPException(422, 'page_size must be 20, 50 or 100')
    return list_library(principal, page, page_size, q, status, file_type)


@app.get('/documents/{document_id}/access', response_model=DocumentAccessResponse)
def get_document_access(document_id: int, principal: Principal = Depends(require_editor)):
    try:
        return document_access.get_access(principal, document_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail='Document not found') from exc


@app.patch('/documents/{document_id}/access', response_model=DocumentAccessResponse)
def update_document_access(document_id: int, body: DocumentAccessUpdate,
                           principal: Principal = Depends(require_editor)):
    try:
        return document_access.update_access(principal, document_id,
                                             body.grant_user_ids, body.revoke_user_ids)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail='Document not found') from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/documents/{document_id}/share")
def grant_document_access(
    document_id: int, body: ShareRequest,
    principal: Principal = Depends(require_editor),
):
    try:
        share_document(principal, document_id, body.username)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "granted"}


@app.delete("/documents/{document_id}", status_code=204)
def remove_document(document_id: int, principal: Principal = Depends(require_editor)):
    try:
        delete_document(principal, document_id)
        remove_pdf(document_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    return Response(status_code=204)


@app.post("/documents/upload-async", response_model=EnqueuedJob, status_code=202)
def upload_document_async(file: UploadFile = File(...),
                          principal: Principal = Depends(require_editor)):
    """Queues an upload; run scripts.ingestion_worker separately to process it."""
    try:
        data = file.file.read(MAX_FILE_BYTES + 1)
        return queue_upload(file.filename or "", data, principal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        file.file.close()


@app.get("/ingestion-jobs", response_model=list[IngestionJob])
def ingestion_job_list(principal: Principal = Depends(require_principal)):
    return list_jobs(principal)


@app.get("/ingestion-jobs/{job_id}", response_model=IngestionJob)
def ingestion_job_detail(job_id: UUID, principal: Principal = Depends(require_principal)):
    result = get_job(principal, job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return result


@app.delete('/ingestion-jobs/{job_id}', status_code=204)
def delete_failed_upload(job_id: UUID, principal: Principal = Depends(require_editor)):
    try:
        remove_failed_job(principal, job_id)
    except PermissionError as exc:
        raise HTTPException(404, 'Job not found') from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(503, 'Could not remove staged upload; job retained') from exc
    return Response(status_code=204)


@app.get("/documents/{document_id}/original-pdf")
def get_original_pdf(document_id: int, principal: Principal = Depends(require_principal)):
    """Authenticated PDF bytes; no public filesystem/static route or API keys in URLs."""
    result = authorized_pdf(principal, document_id)
    if result is None:
        raise HTTPException(status_code=404, detail="PDF unavailable")
    path, title = result
    return FileResponse(
        path, media_type="application/pdf", filename=title,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store",
                 "X-Content-Type-Options": "nosniff"},
    )


@app.get("/ingestion-health")
def ingestion_health(principal: Principal = Depends(require_principal)):
    """Admin-only, tenant-scoped operational overview. No documents or keys."""
    if principal.role != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    return job_health(principal)


@app.get("/observability")
def observability(principal: Principal = Depends(require_principal)):
    """Admin-only, per-tenant in-process metrics; contains no document contents."""
    if principal.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return snapshot(principal.tenant_id)


# M10: email/password accounts and tenant-scoped administration.
# All public registration requires an email-bound invitation from an admin.
class LoginBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=512)


class RegisterBody(LoginBody):
    invitation_code: str = Field(min_length=35, max_length=256)
    username: str = Field(min_length=2, max_length=80)


class InviteBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: str = Field(pattern='^(reader|editor)$')


class UserUpdateBody(BaseModel):
    role: str | None = Field(default=None, pattern='^(reader|editor|admin)$')
    is_active: bool | None = None


@app.post('/auth/login')
def password_login(body: LoginBody, request: Request):
    ip = request.client.host if request.client else 'unknown'
    return account_auth.login(body.email, body.password, ip)


@app.post('/auth/register', status_code=201)
def password_register(body: RegisterBody):
    try:
        return account_auth.register(body.invitation_code, body.email,
                                     body.username, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post('/auth/logout', status_code=204)
def password_logout(request: Request, principal: Principal = Depends(require_principal),
                    credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    token = credentials.credentials if credentials else request.cookies.get(browser_auth.COOKIE_NAME, '')
    account_auth.logout(token)
    response = Response(status_code=204)
    if not credentials or token == request.cookies.get(browser_auth.COOKIE_NAME):
        browser_auth.clear_cookie(response, request)
    return response


@app.post('/auth/browser/login')
def browser_login(body: LoginBody, request: Request, response: Response):
    browser_auth.check_browser_transport(request)
    ip = request.client.host if request.client else 'unknown'
    result = account_auth.login(body.email, body.password, ip)
    return browser_auth.start_session(response, request, result)


@app.post('/auth/browser/register', status_code=201)
def browser_register(body: RegisterBody, request: Request, response: Response):
    browser_auth.check_browser_transport(request)
    try:
        result = account_auth.register(body.invitation_code, body.email,
                                       body.username, body.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return browser_auth.start_session(response, request, result)


@app.get('/auth/session')
def browser_session(request: Request):
    browser_auth.require_browser_request(request)
    # Restore only the HttpOnly browser session, never a token from the URL/body.
    from app.security import principal_from_api_key
    token = request.cookies.get(browser_auth.COOKIE_NAME, '')
    principal = principal_from_api_key(token) if token.startswith('rags_') else None
    if principal is None:
        # A delayed failed restore must never clear a newer login's cookie.
        return JSONResponse({'detail': 'No active browser session'}, status_code=401,
                            headers={'Cache-Control': 'no-store'})
    return JSONResponse(asdict(principal), headers={'Cache-Control': 'no-store'})


@app.post('/auth/browser/logout', status_code=204)
def browser_logout(request: Request):
    browser_auth.require_browser_request(request)
    token = request.cookies.get(browser_auth.COOKIE_NAME, '')
    if token.startswith('rags_'):
        account_auth.logout(token)
    response = Response(status_code=204)
    browser_auth.clear_cookie(response, request)
    return response


@app.get('/admin/dashboard')
def admin_dashboard(principal: Principal = Depends(require_principal)):
    return account_auth.dashboard(principal)


@app.get('/admin/audit-log', response_model=AuditLog)
def admin_audit_log(page: int = Query(1, ge=1), page_size: int = Query(20, ge=20, le=100),
                    action: str = Query('', max_length=120), user_id: int | None = Query(None, ge=1),
                    date_from: date | None = None, date_to: date | None = None,
                    principal: Principal = Depends(require_principal)):
    account_auth.admin_required(principal)
    if page_size not in (20, 50, 100):
        raise HTTPException(422, 'page_size must be 20, 50 or 100')
    try:
        return audit_log.list_events(principal, page, page_size, action, user_id, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get('/admin/users')
def admin_users(principal: Principal = Depends(require_principal)):
    return {'users': account_auth.list_users(principal)}


@app.patch('/admin/users/{user_id}')
def admin_change_user(user_id: int, body: UserUpdateBody,
                      principal: Principal = Depends(require_principal)):
    try:
        return account_auth.update_user(principal, user_id, body.role, body.is_active)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post('/admin/users/{user_id}/revoke-sessions', status_code=204)
def admin_revoke_sessions(user_id: int, principal: Principal = Depends(require_principal)):
    account_auth.revoke_sessions(principal, user_id)
    return Response(status_code=204)


@app.get('/admin/invitations')
def admin_list_invitations(principal: Principal = Depends(require_principal)):
    return {'invitations': account_auth.list_invitations(principal)}


@app.post('/admin/invitations', status_code=201)
def admin_invite(body: InviteBody, principal: Principal = Depends(require_principal)):
    try:
        return account_auth.invitation(principal, body.email, body.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get('/admin/usage')
def admin_usage(days: int = 30, principal: Principal = Depends(require_principal)):
    """Admin-only OpenRouter credits by user and date, scoped to one tenant."""
    if days not in (7, 30):
        raise HTTPException(status_code=422, detail='days must be 7 or 30')
    return usage_ledger.get_usage_dashboard(principal, days=days)


# M10.2: tenant- and user-scoped monthly OpenRouter credit guardrails.
class TenantBudgetBody(BaseModel):
    monthly_limit_credits: str | None = None
    paused: bool = False
    reservation_credits: str = '0.01'


class UserBudgetBody(BaseModel):
    monthly_limit_credits: str | None = None
    paused: bool = False


@app.get('/admin/budgets')
def admin_budgets(principal: Principal = Depends(require_principal)):
    return credit_budgets.get_budget_dashboard(principal)


@app.put('/admin/budgets/tenant')
def admin_set_tenant_budget(body: TenantBudgetBody,
                            principal: Principal = Depends(require_principal)):
    try:
        credit_budgets.update_tenant_budget(principal, body.monthly_limit_credits,
                                            body.paused, body.reservation_credits)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return credit_budgets.get_budget_dashboard(principal)


@app.put('/admin/budgets/users/{user_id}')
def admin_set_user_budget(user_id: int, body: UserBudgetBody,
                          principal: Principal = Depends(require_principal)):
    try:
        credit_budgets.update_user_budget(principal, user_id,
                                          body.monthly_limit_credits, body.paused)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return credit_budgets.get_budget_dashboard(principal)


# M10.3: persistent, private conversation history. Existing /ask remains unchanged.
class ConversationCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ConversationRenameBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)


@app.get('/conversations')
def get_saved_conversations(principal: Principal = Depends(require_principal)):
    return {'conversations': conversations.list_conversations(principal)}


@app.post('/conversations', status_code=201)
def new_conversation(body: ConversationCreateBody,
                     principal: Principal = Depends(require_principal)):
    try:
        return conversations.create_conversation(principal, body.title)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get('/conversations/{conversation_id}')
def read_conversation(conversation_id: int,
                      principal: Principal = Depends(require_principal)):
    return conversations.get_conversation(principal, conversation_id)


@app.patch('/conversations/{conversation_id}')
def rename_saved_conversation(conversation_id: int, body: ConversationRenameBody,
                              principal: Principal = Depends(require_principal)):
    try:
        return conversations.rename_conversation(principal, conversation_id, body.title)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete('/conversations/{conversation_id}', status_code=204)
def remove_saved_conversation(conversation_id: int,
                              principal: Principal = Depends(require_principal)):
    conversations.delete_conversation(principal, conversation_id)
    return Response(status_code=204)


@app.post('/conversations/{conversation_id}/ask')
def ask_in_conversation(conversation_id: int, body: SearchRequest,
                        principal: Principal = Depends(require_principal)):
    # Fail closed before any model call or paid budget reservation.
    conversations.assert_owned(principal, conversation_id)
    result = _run_ask(body, principal)
    message_id = conversations.append_exchange(
        principal, conversation_id, result.question, result.answer, result.sources)
    return {**result.model_dump(mode='json'), 'message_id': message_id}


# M10.4: tenant-scoped knowledge bases. Membership never grants document access.
class KnowledgeBaseBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=500)


@app.get('/knowledge-bases')
def list_knowledge_bases(principal: Principal = Depends(require_principal)):
    return {'knowledge_bases': knowledge_bases.list_bases(principal)}


@app.post('/knowledge-bases', status_code=201)
def create_knowledge_base(body: KnowledgeBaseBody,
                          principal: Principal = Depends(require_principal)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail='Name cannot be blank')
    return knowledge_bases.create_base(principal, name, body.description.strip())


@app.patch('/knowledge-bases/{knowledge_base_id}')
def update_knowledge_base(knowledge_base_id: int, body: KnowledgeBaseBody,
                          principal: Principal = Depends(require_principal)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail='Name cannot be blank')
    return knowledge_bases.rename_base(principal, knowledge_base_id, name, body.description.strip())


@app.delete('/knowledge-bases/{knowledge_base_id}', status_code=204)
def delete_knowledge_base(knowledge_base_id: int,
                          principal: Principal = Depends(require_principal)):
    knowledge_bases.delete_base(principal, knowledge_base_id)
    return Response(status_code=204)


@app.get('/knowledge-bases/{knowledge_base_id}/documents')
def get_knowledge_base_documents(knowledge_base_id: int,
                                 principal: Principal = Depends(require_principal)):
    return {'documents': knowledge_bases.list_base_documents(principal, knowledge_base_id)}


@app.put('/knowledge-bases/{knowledge_base_id}/documents/{document_id}', status_code=204)
def add_knowledge_base_document(knowledge_base_id: int, document_id: int,
                                principal: Principal = Depends(require_principal)):
    knowledge_bases.add_document(principal, knowledge_base_id, document_id)
    return Response(status_code=204)


@app.delete('/knowledge-bases/{knowledge_base_id}/documents/{document_id}', status_code=204)
def remove_knowledge_base_document(knowledge_base_id: int, document_id: int,
                                   principal: Principal = Depends(require_principal)):
    knowledge_bases.remove_document(principal, knowledge_base_id, document_id)
    return Response(status_code=204)


# M10.5: private answer ratings and admin-only aggregate quality signals.
class AnswerFeedbackBody(BaseModel):
    rating: str = Field(pattern='^(up|down)$')
    reason: str | None = Field(default=None,
        pattern='^(incorrect|incomplete|irrelevant|outdated|other)$')


@app.get('/conversations/{conversation_id}/feedback')
def saved_answer_feedback(conversation_id: int,
                          principal: Principal = Depends(require_principal)):
    return {'feedback': answer_feedback.list_feedback(principal,conversation_id)}


@app.put('/conversations/{conversation_id}/messages/{message_id}/feedback')
def rate_saved_answer(conversation_id: int, message_id: int, body: AnswerFeedbackBody,
                      principal: Principal = Depends(require_principal)):
    try:
        return answer_feedback.save_feedback(principal,conversation_id,message_id,
                                             body.rating,body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc


@app.delete('/conversations/{conversation_id}/messages/{message_id}/feedback',status_code=204)
def unrate_saved_answer(conversation_id: int,message_id: int,
                        principal: Principal = Depends(require_principal)):
    answer_feedback.remove_feedback(principal,conversation_id,message_id)
    return Response(status_code=204)


@app.get('/admin/feedback')
def admin_feedback_quality(days: int = 30,
                           principal: Principal = Depends(require_principal)):
    try:
        return answer_feedback.admin_quality(principal,days)
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc
