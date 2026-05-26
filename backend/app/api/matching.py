from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.deps import require_any_role
from app.core.config import settings
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.match_result import MatchResult
from app.models.user import User
from app.schemas.match import MatchItem, MatchResponse
from app.services.ai_metadata import current_ai_provider_metadata, scoring_version_from_reasoning
from app.services.embedding import get_embedding_service
from app.services.hybrid_matcher import (
    HybridMatchingEngine,
    is_current_scoring_reasoning,
    is_interview_blended_reasoning,
    semantic_score_from_reasoning,
)
from app.services.matching import rank_candidates
from app.services.skill_catalog import normalize_skill_name

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
    cross_encoder_top_k: int = Query(default=0, ge=0, le=50, description="Number of candidates sent to LLM cross-encoder for bounded advisory reranking (0 to disable)"),
    use_hybrid: bool = Query(default=True, description="Use hybrid matching engine with ESCO integration"),
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
    session: AsyncSession = Depends(get_db_session),
) -> MatchResponse:
    """
    Runs matching for one job against filtered candidates.
    """
    if skill_logic not in {"and", "or"}:
        raise HTTPException(status_code=400, detail="skill_logic must be 'and' or 'or'")

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
            job_embedding = [0.0] * settings.embedding_dimension
    else:
        job_embedding = [0.0] * settings.embedding_dimension  # unused placeholder

    matches = await rank_candidates(
        session,
        job,
        job_embedding,
        top_k=top_k,
        candidates=candidates,
        cross_encoder_top_k=cross_encoder_top_k,
        use_hybrid=use_hybrid,
    )
    results = await _serialize_matches(session, matches)

    return MatchResponse(job_id=job_id, results=results)


@router.get("/jobs/{job_id}/matches", response_model=MatchResponse)
async def saved_matches(
    job_id: str,
    top_k: int = Query(default=100, ge=1, le=100, description="Number of saved candidates to return"),
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
    session: AsyncSession = Depends(get_db_session),
) -> MatchResponse:
    """
    Returns saved matches for a job and refreshes stale score traces.
    """
    job = await _get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    result = await session.execute(
        select(MatchResult)
        .where(MatchResult.job_id == job_id)
        .order_by(MatchResult.score.desc(), MatchResult.candidate_id.asc())
        .limit(top_k)
    )
    matches = list(result.scalars().all())
    matches = await _refresh_stale_saved_matches(session, job, matches)
    return MatchResponse(job_id=job_id, results=await _serialize_matches(session, matches))


async def _get_job(session: AsyncSession, job_id: str) -> Job | None:
    """
    Loads one job by ID from the database.
    """
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
    """
    Applies candidate search and filter options before matching.
    """
    if min_skills is not None and min_skills < 0:
        raise HTTPException(status_code=400, detail="min_skills must be >= 0")
    if min_years is not None and min_years < 0:
        raise HTTPException(status_code=400, detail="min_years must be >= 0")
    if max_years is not None and max_years < 0:
        raise HTTPException(status_code=400, detail="max_years must be >= 0")
    if min_years is not None and max_years is not None and min_years > max_years:
        raise HTTPException(status_code=400, detail="min_years cannot exceed max_years")

    stmt = select(Candidate)

    if search:
        search_lower = search.lower()
        stmt = stmt.where(
            Candidate.full_name.ilike(f"%{search_lower}%")
            | Candidate.email.ilike(f"%{search_lower}%")
        )
    if min_years is not None:
        stmt = stmt.where(
            Candidate.total_years_experience.is_not(None),
            Candidate.total_years_experience >= min_years,
        )
    if max_years is not None:
        stmt = stmt.where(
            Candidate.total_years_experience.is_not(None),
            Candidate.total_years_experience <= max_years,
        )

    result = await session.execute(stmt)
    candidates = list(result.scalars().all())

    if skills:
        skill_list = [normalize_skill_name(s) for s in skills.split(",") if s.strip()]
        if skill_logic == "or":
            candidates = [
                c for c in candidates
                if any(skill_lower in set(_candidate_display_skills(c)) for skill_lower in skill_list)
            ]
        else:
            candidates = [
                c for c in candidates
                if all(skill_lower in set(_candidate_display_skills(c)) for skill_lower in skill_list)
            ]

    if min_skills is not None:
        candidates = [c for c in candidates if len(_candidate_display_skills(c)) >= min_skills]

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


async def _serialize_matches(session: AsyncSession, matches: list[MatchResult]) -> list[MatchItem]:
    """
    Converts saved match rows into API response items.
    """
    candidate_ids = {match.candidate_id for match in matches}
    candidate_by_id: dict[str, Candidate] = {}
    if candidate_ids:
        result = await session.execute(select(Candidate).where(Candidate.id.in_(candidate_ids)))
        candidate_by_id = {candidate.id: candidate for candidate in result.scalars().all()}

    return [
        MatchItem(
            candidate_id=match.candidate_id,
            candidate_name=candidate_by_id[match.candidate_id].full_name if match.candidate_id in candidate_by_id else None,
            candidate_email=candidate_by_id[match.candidate_id].email if match.candidate_id in candidate_by_id else None,
            candidate_skills=_candidate_display_skills(candidate_by_id[match.candidate_id]) if match.candidate_id in candidate_by_id else [],
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


async def _refresh_stale_saved_matches(
    session: AsyncSession,
    job: Job,
    matches: list[MatchResult],
) -> list[MatchResult]:
    """
    Recomputes saved matches that use outdated scoring reasoning.
    """
    stale_matches = [
        match for match in matches
        if not is_current_scoring_reasoning(match.reasoning)
        and not is_interview_blended_reasoning(match.reasoning)
    ]
    if not stale_matches:
        return matches

    candidate_ids = [match.candidate_id for match in stale_matches]
    result = await session.execute(select(Candidate).where(Candidate.id.in_(candidate_ids)))
    candidates = {candidate.id: candidate for candidate in result.scalars().all()}
    engine = HybridMatchingEngine()
    refreshed = 0

    for match in stale_matches:
        candidate = candidates.get(match.candidate_id)
        if candidate is None:
            continue
        semantic_score = semantic_score_from_reasoning(match.reasoning) or 0.0
        current = await engine._compute_match(job, candidate, semantic_score=semantic_score)
        if current is None:
            continue
        current.reasoning.score_trace["refreshed_from_stale_match"] = True
        current.reasoning.score_trace["previous_scoring_model"] = (
            match.reasoning.get("scoring_model")
            if isinstance(match.reasoning, dict)
            else None
        )
        match.score = current.final_score
        match.reasoning = current.to_dict()
        match.scoring_version = scoring_version_from_reasoning(match.reasoning)
        match.provider_metadata = current_ai_provider_metadata()
        match.is_stale = False
        refreshed += 1

    if refreshed:
        await session.commit()
        logger.info(
            "Refreshed stale saved match scores",
            extra={"job_id": job.id, "refreshed_count": refreshed},
        )
        matches = sorted(matches, key=lambda item: (-item.score, item.candidate_id))
        for rank, match in enumerate(matches, start=1):
            if isinstance(match.reasoning, dict):
                reasoning = dict(match.reasoning)
                reasoning["rank"] = rank
                match.reasoning = reasoning
        await session.commit()

    return matches


def _candidate_display_skills(candidate: Candidate) -> list[str]:
    """
    Builds the visible positive skill list for a candidate.
    """
    skills = list(candidate.skills or [])
    for detail in candidate.skills_detailed or []:
        if not isinstance(detail, dict):
            continue
        status = str(detail.get("status", "")).lower().strip()
        name = str(detail.get("name", "")).strip()
        if name and status != "no_experience":
            skills.append(name)

    result: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        normalized = normalize_skill_name(skill)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result
