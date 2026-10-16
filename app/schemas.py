from datetime import datetime
from typing import Literal
from uuid import UUID
"""Public API input/output models."""
from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    text: str = Field(min_length=20, max_length=200_000)


class IngestResponse(BaseModel):
    document_id: int
    chunk_count: int
    already_exists: bool


class SearchRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    top_k: int = Field(default=3, ge=1, le=10)
    knowledge_base_id: int | None = Field(default=None, ge=1)


class SearchHit(BaseModel):
    source_number: int
    document_id: int
    title: str
    chunk_index: int
    content: str
    similarity: float
    page_number: int | None = None


class SearchResponse(BaseModel):
    question: str
    hits: list[SearchHit]


class AskResponse(BaseModel):
    question: str
    answer: str
    sources: list[SearchHit]


class ShareRequest(BaseModel):
    username: str = Field(min_length=2, max_length=80, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]+$")


class EnqueuedJob(BaseModel):
    id: UUID
    filename: str
    status: Literal["queued"]
    created_at: datetime


class IngestionJob(BaseModel):
    id: UUID
    filename: str
    status: Literal["queued", "processing", "completed", "failed"]
    document_id: int | None = None
    chunk_count: int | None = None
    already_exists: bool | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempt_count: int = 0
    heartbeat_at: datetime | None = None
    next_attempt_at: datetime | None = None
