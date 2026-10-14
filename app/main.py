"""Local FastAPI application. For learning only; no authentication is installed."""
import psycopg
from fastapi import FastAPI, HTTPException

from app.db import db_connection
from app.schemas import (
    AskResponse, IngestRequest, IngestResponse, SearchRequest, SearchResponse
)
from app.services import ingest_document, search_documents, answer_question

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
