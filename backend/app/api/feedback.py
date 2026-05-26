from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.deps import require_any_role
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.skill_feedback import SkillFeedback
from app.models.user import User
from app.services.continuous_learning import get_feedback_stats, process_feedback_batch
from app.services.skill_catalog import normalize_skill_name

router = APIRouter()


class MatchFeedbackRequest(BaseModel):
    job_id: str
    candidate_id: str
    skill: str = Field(min_length=1, max_length=120)
    was_matched: bool = False
    recruiter_action: str = Field(default="added", pattern="^(added|removed)$")
    correct_match: bool = True
    notes: str | None = Field(default=None, max_length=1000)


@router.post("/matching/feedback")
async def submit_matching_feedback(
    payload: MatchFeedbackRequest,
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Stores recruiter feedback and updates dynamic learning suggestions.
    """
    job = await session.get(Job, payload.job_id)
    candidate = await session.get(Candidate, payload.candidate_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")

    feedback = SkillFeedback(
        id=str(uuid.uuid4()),
        job_id=payload.job_id,
        candidate_id=payload.candidate_id,
        skill_name=normalize_skill_name(payload.skill),
        was_matched=payload.was_matched,
        recruiter_action=payload.recruiter_action,
        correct_match=payload.correct_match,
        notes=payload.notes,
    )
    session.add(feedback)
    await session.commit()
    stats = await process_feedback_batch(session)
    return {"status": "ok", "feedback_id": feedback.id, "stats": stats}


@router.get("/matching/feedback/stats")
async def matching_feedback_stats(
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Returns continuous-learning feedback statistics.
    """
    return await get_feedback_stats(session)
