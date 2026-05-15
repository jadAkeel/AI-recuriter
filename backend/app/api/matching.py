from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.deps import require_any_role
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.user import User
from app.schemas.match import MatchItem, MatchResponse
from app.services.embedding import get_embedding_service
from app.services.matching import rank_candidates
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/jobs/{job_id}/match", response_model=MatchResponse)
async def match_candidates(
    job_id: str,
    top_k: int = Query(default=10, ge=1, le=100, description="Number of top candidates to return"),
    search: str | None = Query(default=None, description="Search by name or email"),
    skills: str | None = Query(default=None, description="Comma-separated skills filter (AND logic)"),
    skill_logic: str | None = Query(default="and", description="Skill filter logic: 'and' or 'or'"),
    min_skills: int | None = Query(default=None, description="Minimum number of skills"),
    min_years: float | None = Query(default=None, description="Minimum years of experience"),
    max_years: float | None = Query(default=None, description="Maximum years of experience"),
    education_search: str | None = Query(default=None, description="Search in education text"),
    university: str | None = Query(default=None, description="Filter by university/institution name"),
    degree: str | None = Query(default=None, description="Filter by degree name"),
    cross_encoder_top_k: int = Query(default=0, ge=0, le=50, description="Number of candidates sent to LLM cross-encoder for deep scoring (0 to disable)"),
    use_hybrid: bool = Query(default=True, description="Use hybrid matching engine with ESCO integration"),
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
    session: AsyncSession = Depends(get_db_session),
) -> MatchResponse:
    job = await _get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    candidates = await _filter_candidates(
        session,
        search=search,
        skills=skills,
        skill_logic=skill_logic,
        min_skills=min_skills,
        min_years=min_years,
        max_years=max_years,
        education_search=education_search,
        university=university,
        degree=degree,
    )

    # Only compute job embedding if not using hybrid engine (hybrid computes its own)
    if not use_hybrid:
        embedder = get_embedding_service()
        try:
            job_embedding = (await embedder.embed([job.description]))[0]
        except Exception as e:
            logger.error("Job embedding failed, using zero vector", extra={"error": str(e)})
            job_embedding = [0.0] * 384
    else:
        job_embedding = [0.0] * 384  # unused placeholder

    matches = await rank_candidates(
        session,
        job,
        job_embedding,
        top_k=top_k,
        candidates=candidates,
        cross_encoder_top_k=cross_encoder_top_k,
        use_hybrid=use_hybrid,
    )
    candidate_by_id = {candidate.id: candidate for candidate in candidates}
    results = [
        MatchItem(
            candidate_id=match.candidate_id,
            candidate_name=candidate_by_id[match.candidate_id].full_name if match.candidate_id in candidate_by_id else None,
            candidate_email=candidate_by_id[match.candidate_id].email if match.candidate_id in candidate_by_id else None,
            candidate_skills=candidate_by_id[match.candidate_id].skills if match.candidate_id in candidate_by_id else [],
            candidate_total_years_experience=(
                candidate_by_id[match.candidate_id].total_years_experience
                if match.candidate_id in candidate_by_id
                else None
            ),
            score=match.score,
            reasoning=match.reasoning,
        )
        for match in matches
    ]

    return MatchResponse(job_id=job_id, results=results)


async def _get_job(session: AsyncSession, job_id: str) -> Job | None:
    stmt = select(Job).where(Job.id == job_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _filter_candidates(
    session: AsyncSession,
    search: str | None = None,
    skills: str | None = None,
    skill_logic: str | None = "and",
    min_skills: int | None = None,
    min_years: float | None = None,
    max_years: float | None = None,
    education_search: str | None = None,
    university: str | None = None,
    degree: str | None = None,
) -> list[Candidate]:
    stmt = select(Candidate)

    if search:
        search_lower = search.lower()
        stmt = stmt.where(
            Candidate.full_name.ilike(f"%{search_lower}%")
            | Candidate.email.ilike(f"%{search_lower}%")
        )

    result = await session.execute(stmt)
    candidates = list(result.scalars().all())

    if skills:
        skill_list = [s.strip().lower() for s in skills.split(",") if s.strip()]
        if skill_logic == "or":
            candidates = [
                c for c in candidates
                if any(
                    any(skill_lower in cs.lower() for cs in c.skills)
                    for skill_lower in skill_list
                )
            ]
        else:
            candidates = [
                c for c in candidates
                if all(
                    any(skill_lower in cs.lower() for cs in c.skills)
                    for skill_lower in skill_list
                )
            ]

    if min_skills is not None and min_skills < 0:
        raise HTTPException(status_code=400, detail="min_skills must be >= 0")
    if min_years is not None and min_years < 0:
        raise HTTPException(status_code=400, detail="min_years must be >= 0")
    if max_years is not None and max_years < 0:
        raise HTTPException(status_code=400, detail="max_years must be >= 0")
    if min_years is not None and max_years is not None and min_years > max_years:
        raise HTTPException(status_code=400, detail="min_years cannot exceed max_years")

    if min_skills is not None:
        candidates = [c for c in candidates if len(c.skills) >= min_skills]
    if min_years is not None:
        candidates = [c for c in candidates if c.total_years_experience is not None and c.total_years_experience >= min_years]
    if max_years is not None:
        candidates = [c for c in candidates if c.total_years_experience is not None and c.total_years_experience <= max_years]

    if education_search:
        q = education_search.lower()
        candidates = [
            c for c in candidates
            if any(q in (e or "").lower() for e in c.education)
            or any(q in (e.get("institution", "") or "").lower() for e in (c.education_entries or []))
            or any(q in (e.get("degree", "") or "").lower() for e in (c.education_entries or []))
        ]

    if university:
        q = university.lower()
        candidates = [
            c for c in candidates
            if any(q in (e.get("institution", "") or "").lower() for e in (c.education_entries or []))
            or any(q in (e or "").lower() for e in c.education)
        ]

    if degree:
        q = degree.lower()
        candidates = [
            c for c in candidates
            if any(q in (e.get("degree", "") or "").lower() for e in (c.education_entries or []))
            or any(q in (e or "").lower() for e in c.education)
        ]

    return candidates
