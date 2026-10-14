"""Local FastAPI application. For learning only; no authentication is installed."""
import psycopg
from fastapi import FastAPI, HTTPException, File, UploadFile

from app.db import db_connection
from app.file_ingestion import MAX_FILE_BYTES, extract_document, extract_pdf_pages
from app.schemas import (
    AskResponse, IngestRequest, IngestResponse, SearchRequest, SearchResponse
)
from app.services import ingest_document, ingest_pdf_pages, search_documents, answer_question

app = FastAPI(
    title="Enterprise RAG Knowledge Assistant — Local MVP",
    version="0.1.0",
    description=(
        "Learning prototype. Do not deploy publicly or upload sensitive company "
        "documents: this version has no authentication or access control."
    ),
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
def add_document(body: IngestRequest):
    try:
        doc_id, count, exists = ingest_document(body.title, body.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return IngestResponse(document_id=doc_id, chunk_count=count, already_exists=exists)


@app.post("/search", response_model=SearchResponse)
def search(body: SearchRequest):
    hits = search_documents(body.question, body.top_k)
    return SearchResponse(question=body.question, hits=hits)


@app.post("/ask", response_model=AskResponse)
def ask(body: SearchRequest):
    hits = search_documents(body.question, body.top_k)
    try:
        answer = answer_question(body.question, hits)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return AskResponse(question=body.question, answer=answer, sources=hits)


@app.post("/documents/upload", response_model=IngestResponse)
def upload_document(file: UploadFile = File(...)):
    """Upload a document into the existing RAG pipeline (local MVP only)."""
    try:
        # Read at most limit + 1 so oversized files can be rejected.
        data = file.file.read(MAX_FILE_BYTES + 1)
        title, text = extract_document(file.filename or "", data)
        if title.lower().endswith(".pdf"):
            pages = extract_pdf_pages(title, data)
            doc_id, count, exists = ingest_pdf_pages(title, pages)
        else:
            doc_id, count, exists = ingest_document(title, text)
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
def reindex_pdf(document_id: int, file: UploadFile = File(...)):
    """Replace PDF chunks in one DB transaction, preserving document ID.

    Development-only: authenticate before public deployment.
    """
    try:
        data = file.file.read(MAX_FILE_BYTES + 1)
        title = file.filename or ""
        pages = extract_pdf_pages(title, data)
        doc_id, count, exists = ingest_pdf_pages(title, pages, replace_document_id=document_id)
        return IngestResponse(document_id=doc_id, chunk_count=count, already_exists=exists)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        file.file.close()
