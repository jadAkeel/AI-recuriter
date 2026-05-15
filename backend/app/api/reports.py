from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.deps import ensure_candidate_access, require_any_role
from app.models.user import User
from app.schemas.report import (
    CandidateReportRequest,
    CandidateReportResponse,
    ComparisonRequest,
    ComparisonResponse,
)
from app.services.explainability import (
    compare_candidates,
    generate_candidate_report,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/reports/candidate", response_model=CandidateReportResponse)
async def report_candidate(
    request: CandidateReportRequest,
    current_user: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
    session: AsyncSession = Depends(get_db_session),
) -> CandidateReportResponse:
    try:
        await ensure_candidate_access(session, current_user, request.candidate_id)
        return await generate_candidate_report(session, request.job_id, request.candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/reports/compare", response_model=ComparisonResponse)
async def report_compare(
    request: ComparisonRequest,
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
    session: AsyncSession = Depends(get_db_session),
) -> ComparisonResponse:
    try:
        return await compare_candidates(session, request.job_id, request.candidate_ids)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
