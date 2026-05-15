from __future__ import annotations

import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_any_role
from app.core.db import get_db_session
from app.models.embedding import Embedding
from app.models.interview import InterviewSession
from app.models.job import Job
from app.models.match_result import MatchResult
from app.models.report import Report
from app.models.user import User
from app.schemas.job import JobParseRequest, JobProfile, JobRecord, JobUpdateRequest
from app.services.embedding import get_embedding_service
from app.services.esco_extractor import get_esco_extractor
from app.services.job_parser import parse_job_description
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/jobs/parse", response_model=JobProfile)
async def parse_job(
    request: JobParseRequest,
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
) -> JobProfile:
    return parse_job_description(request.description)


@router.get("/jobs", response_model=list[JobRecord])
async def list_jobs(
    _: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
    session: AsyncSession = Depends(get_db_session),
) -> list[JobRecord]:
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
    try:
        profile = parse_job_description(request.description)
        job_id = str(uuid.uuid4())

        try:
            esco = await get_esco_extractor()
            esco_result = await esco.extract_skills(request.description, top_k=25)
            esco_skill_names = {m.skill.title.lower() for m in esco_result.skills}
            existing_required = set(s.lower() for s in profile.required_skills)
            existing_optional = set(s.lower() for s in profile.optional_skills)
            new_from_esco = [
                s for s in esco_skill_names
                if s not in existing_required and s not in existing_optional
            ]
            if new_from_esco:
                profile.required_skills.extend(sorted(new_from_esco))
                logger.info("ESCO enriched job with %d new skills", len(new_from_esco))
        except Exception:
            logger.warning("ESCO enrichment skipped for job (not available)")

        job = Job(
            id=job_id,
            title=profile.title,
            description=profile.description,
            required_skills=profile.required_skills,
            optional_skills=profile.optional_skills,
            seniority=profile.seniority,
        )
        session.add(job)
        await session.commit()
    except Exception as exc:
        logger.exception("Job creation failed")
        raise HTTPException(status_code=500, detail="Job creation failed") from exc

    try:
        embedder = get_embedding_service()
        embedding = (await embedder.embed([profile.description]))[0]
        store = VectorStore(session)
        await store.upsert_embedding("job", job_id, embedding)
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
    stmt = select(Job).where(Job.id == job_id)
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if request.title is not None:
        job.title = request.title
    if request.description is not None:
        job.description = request.description
    if request.required_skills is not None:
        job.required_skills = request.required_skills
    if request.optional_skills is not None:
        job.optional_skills = request.optional_skills
    if request.seniority is not None:
        job.seniority = request.seniority

    await session.commit()

    if request.description is not None:
        try:
            embedder = get_embedding_service()
            embedding = (await embedder.embed([job.description]))[0]
            store = VectorStore(session)
            await store.upsert_embedding("job", job_id, embedding)
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
    stmt = select(Job).where(Job.id == job_id)
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    await session.execute(delete(MatchResult).where(MatchResult.job_id == job_id))
    await session.execute(delete(InterviewSession).where(InterviewSession.job_id == job_id))
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
    return JobRecord(
        job_id=job.id,
        title=job.title,
        description=job.description,
        required_skills=job.required_skills,
        optional_skills=job.optional_skills,
        seniority=job.seniority,
    )
