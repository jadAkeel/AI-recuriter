from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.deps import require_any_role
from app.models.user import User
from app.schemas.rag import IngestRequest, IngestResponse, QueryRequest, QueryResponse
from app.services.rag import add_document, ingest_knowledge_base, query_knowledge

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/rag/ingest", response_model=IngestResponse)
async def ingest(
    request: IngestRequest,
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
    session: AsyncSession = Depends(get_db_session),
) -> IngestResponse:
    return await add_document(session, request.title, request.content, request.category, request.tags)


@router.post("/rag/seed")
async def seed_knowledge(
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    count = await ingest_knowledge_base(session)
    return {"seeded": count}


@router.post("/rag/query", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    _: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
    session: AsyncSession = Depends(get_db_session),
) -> QueryResponse:
    return await query_knowledge(session, request.query, request.category, request.top_k)
