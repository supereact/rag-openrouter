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
