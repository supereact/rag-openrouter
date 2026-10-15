"""Local FastAPI application with tenant-scoped API key security."""
import asyncio
import logging
from time import perf_counter
from uuid import uuid4
from uuid import UUID
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException, File, UploadFile, Depends, Response, Request
from fastapi.responses import FileResponse

from app.db import db_connection
from app.ingestion_jobs import queue_upload, list_jobs, get_job, job_health
from app.model_warmup import warmup_local_models
from app.observability import measure, reset_llm_usage, save_request_usage, snapshot
from app.original_pdfs import store_pdf, remove_pdf, authorized_pdf
from app.security import Principal, require_principal, require_editor
from app.file_ingestion import MAX_FILE_BYTES, extract_document, extract_pdf_pages
from app.schemas import (
    AskResponse, IngestRequest, IngestResponse, SearchRequest, SearchResponse,
    ShareRequest, IngestionJob, EnqueuedJob,
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
    with measure(principal.tenant_id, "search", "retrieval"):
        hits = search_documents(body.question, body.top_k, principal=principal)
    return SearchResponse(question=body.question, hits=hits)


@app.post("/ask", response_model=AskResponse)
def ask(body: SearchRequest, principal: Principal = Depends(require_principal)):
    with measure(principal.tenant_id, "ask", "retrieval"):
        hits = search_documents(body.question, body.top_k, principal=principal)
    reset_llm_usage()
    try:
        with measure(principal.tenant_id, "ask", "generation"):
            answer = answer_question(body.question, hits)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
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
