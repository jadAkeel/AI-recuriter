from __future__ import annotations

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=50000)
    category: str = Field(default="general", min_length=1, max_length=50)
    tags: list[str] = Field(default_factory=list)


class IngestResponse(BaseModel):
    document_id: str
    title: str
    category: str


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=5000)
    category: str | None = None
    top_k: int = Field(default=5, ge=1, le=50)


class DocumentItem(BaseModel):
    document_id: str
    title: str
    content: str
    category: str
    score: float


class QueryResponse(BaseModel):
    query: str
    results: list[DocumentItem]
