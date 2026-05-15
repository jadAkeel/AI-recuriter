from __future__ import annotations

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    title: str
    content: str
    category: str = "general"
    tags: list[str] = Field(default_factory=list)


class IngestResponse(BaseModel):
    document_id: str
    title: str
    category: str


class QueryRequest(BaseModel):
    query: str
    category: str | None = None
    top_k: int = 5


class DocumentItem(BaseModel):
    document_id: str
    title: str
    content: str
    category: str
    score: float


class QueryResponse(BaseModel):
    query: str
    results: list[DocumentItem]
