from __future__ import annotations

import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_any_role
from app.core.db import get_db_session
from app.core.config import settings
from app.models.embedding import Embedding
from app.models.interview import InterviewSession
from app.models.job import Job
from app.models.match_result import MatchResult
from app.models.report import Report
from app.models.report_version import ReportVersion
from app.models.skill_feedback import SkillFeedback
from app.models.user import User
from app.schemas.job import JobParseRequest, JobProfile, JobRecord, JobUpdateRequest
from app.services.embedding import embedding_metadata_for_text, get_embedding_service
from app.services.esco_extractor import get_esco_extractor
from app.services.job_parser import parse_job_description
from app.services.skill_catalog import normalize_skill_list, normalize_skill_name, normalize_text_for_skill_matching, skill_in_text
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)

router = APIRouter()


def _esco_skill_has_text_evidence(skill: str, job_text: str) -> bool:
    """
    Checks whether an ESCO skill is explicitly present in source text.
    """
    normalized_text = normalize_text_for_skill_matching(job_text)
    return bool(normalized_text and skill_in_text(skill, normalized_text))


@router.post("/jobs/parse", response_model=JobProfile)
async def parse_job(
    request: JobParseRequest,
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
) -> JobProfile:
    """
    Parses job description text without saving it.
    """
    return parse_job_description(request.description)


@router.get("/jobs", response_model=list[JobRecord])
async def list_jobs(
    _: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
    session: AsyncSession = Depends(get_db_session),
) -> list[JobRecord]:
    """
    Lists saved jobs as API records.
    """
    stmt = select(Job).order_by(Job.id.desc())
    result = await session.execute(stmt)
    jobs = result.scalars().all()
    return [_to_job_record(job) for job in jobs]


@router.post("/jobs", response_model=JobRecord)
async def create_job(
    request: JobParseRequest,
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
    session: AsyncSession = Depends(get_db_session),
) -> JobRecord:
    """
    Creates a job, enriches skills when enabled, and stores its embedding.
    """
    try:
        profile = parse_job_description(request.description)
        job_id = str(uuid.uuid4())

        if settings.esco_api_enabled:
            try:
                esco = await get_esco_extractor()
                esco_result = await esco.extract_skills(request.description, top_k=25)
                esco_skill_names = {
                    normalize_skill_name(m.skill.title)
                    for m in esco_result.skills
                    if _esco_skill_has_text_evidence(m.skill.title, request.description)
                }
                existing_required = {normalize_skill_name(s) for s in profile.required_skills}
                existing_optional = {normalize_skill_name(s) for s in profile.optional_skills}
                new_from_esco = [
                    s for s in esco_skill_names
                    if s not in existing_required and s not in existing_optional
                ]
                if new_from_esco:
                    profile.required_skills.extend(sorted(new_from_esco))
                    logger.info("ESCO enriched job with %d new skills", len(new_from_esco))
            except Exception:
                logger.warning("ESCO enrichment skipped for job (not available)")

        required_skills = _normalize_skill_list(profile.required_skills)
        optional_skills = [
            skill for skill in _normalize_skill_list(profile.optional_skills)
            if skill not in set(required_skills)
        ]
        profile.required_skills = required_skills
        profile.optional_skills = optional_skills

        job = Job(
            id=job_id,
            title=profile.title,
            description=profile.description,
            required_skills=required_skills,
            optional_skills=optional_skills,
            seniority=profile.seniority,
        )
        session.add(job)
        await session.commit()
    except Exception as exc:
        logger.exception("Job creation failed")
        raise HTTPException(status_code=500, detail="Job creation failed") from exc

    try:
        embedder = get_embedding_service()
        job_text = f"{profile.title or ''} {profile.description}"
        embedding = (await embedder.embed([job_text]))[0]
        store = VectorStore(session)
        await store.upsert_embedding(
            "job",
            job_id,
            embedding,
            metadata=embedding_metadata_for_text(job_text),
        )
    except Exception:
        logger.warning("Embedding generation failed for job %s — job created without vector", job_id)

    return JobRecord(job_id=job_id, **profile.model_dump())


@router.patch("/jobs/{job_id}", response_model=JobRecord)
async def update_job(
    job_id: str,
    request: JobUpdateRequest,
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
    session: AsyncSession = Depends(get_db_session),
) -> JobRecord:
    """
    Updates a job and clears stale match results when matching inputs change.
    """
    stmt = select(Job).where(Job.id == job_id)
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    matching_inputs_changed = any(
        value is not None
        for value in (
            request.title,
            request.description,
            request.required_skills,
            request.optional_skills,
            request.seniority,
        )
    )

    if request.title is not None:
        job.title = request.title
    if request.description is not None:
        job.description = request.description
    if request.required_skills is not None:
        job.required_skills = _normalize_skill_list(request.required_skills)
    if request.optional_skills is not None:
        required = set(_normalize_skill_list(job.required_skills or []))
        job.optional_skills = [skill for skill in _normalize_skill_list(request.optional_skills) if skill not in required]
    if request.seniority is not None:
        job.seniority = request.seniority

    if matching_inputs_changed:
        await session.execute(delete(MatchResult).where(MatchResult.job_id == job_id))
        await session.execute(delete(ReportVersion).where(ReportVersion.job_id == job_id))
        await session.execute(delete(Report).where(Report.job_id == job_id))

    await session.commit()

    if request.description is not None or request.title is not None:
        try:
            embedder = get_embedding_service()
            job_text = f"{job.title or ''} {job.description}"
            embedding = (await embedder.embed([job_text]))[0]
            store = VectorStore(session)
            await store.upsert_embedding(
                "job",
                job_id,
                embedding,
                metadata=embedding_metadata_for_text(job_text),
            )
        except Exception:
            logger.warning("Embedding update failed for job %s — job data saved", job_id)

    await session.refresh(job)
    return _to_job_record(job)


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    """
    Deletes a job and related matches, interviews, reports, and embeddings.
    """
    stmt = select(Job).where(Job.id == job_id)
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    await session.execute(delete(MatchResult).where(MatchResult.job_id == job_id))
    await session.execute(delete(SkillFeedback).where(SkillFeedback.job_id == job_id))
    await session.execute(delete(InterviewSession).where(InterviewSession.job_id == job_id))
    await session.execute(delete(ReportVersion).where(ReportVersion.job_id == job_id))
    await session.execute(delete(Report).where(Report.job_id == job_id))
    await session.execute(
        delete(Embedding).where(
            Embedding.entity_type == "job",
            Embedding.entity_id == job_id,
        )
    )
    await session.execute(delete(Job).where(Job.id == job_id))
    await session.commit()

    return {"status": "deleted", "job_id": job_id}


def _to_job_record(job: Job) -> JobRecord:
    """
    Converts a job database row into an API record.
    """
    required_skills = _normalize_skill_list(job.required_skills or [])
    optional_skills = [
        skill for skill in _normalize_skill_list(job.optional_skills or [])
        if skill not in set(required_skills)
    ]
    return JobRecord(
        job_id=job.id,
        title=job.title,
        description=job.description,
        required_skills=required_skills,
        optional_skills=optional_skills,
        seniority=job.seniority,
    )


def _normalize_skill_list(skills: list[str]) -> list[str]:
    """
    Normalizes skill lists for API schemas or job records.
    """
    return normalize_skill_list(skills)
