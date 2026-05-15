from __future__ import annotations

import logging
import json
import uuid
import os
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Query
from fastapi.responses import StreamingResponse, PlainTextResponse, FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.deps import ensure_candidate_access, get_current_user, require_any_role
from app.core.config import settings
from sqlalchemy import delete as sa_delete

from app.models.candidate import Candidate
from app.models.embedding import Embedding
from app.models.interview import InterviewSession
from app.models.match_result import MatchResult
from app.models.report import Report
from app.models.user import User
from app.schemas.candidate import CandidateRecord
from app.services.cv_parser import extract_text
from app.services.enhanced_cv_parser import get_enhanced_cv_parser
from app.services.embedding import get_embedding_service
from app.services.esco_extractor import get_esco_extractor
from app.services.skill_catalog import SKILL_KEYWORDS, get_categories
from app.services.task_queue import enqueue_cv_processing
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)

router = APIRouter()

CV_STORAGE = Path(settings.cv_storage_path)
PENDING_CV_STORAGE = CV_STORAGE.parent / "pending_cvs"
MAX_CV_UPLOAD_BYTES = 15 * 1024 * 1024


def _ensure_cv_storage():
    CV_STORAGE.mkdir(parents=True, exist_ok=True)


def _ensure_pending_cv_storage():
    PENDING_CV_STORAGE.mkdir(parents=True, exist_ok=True)


def _save_cv_file(candidate_id: str, filename: str, content: bytes) -> str:
    _ensure_cv_storage()
    ext = Path(filename).suffix.lower()
    if ext not in (".pdf", ".docx", ".doc", ".txt"):
        ext = ".pdf"
    dest = CV_STORAGE / f"{candidate_id}{ext}"
    dest.write_bytes(content)
    return str(dest)


def _save_pending_cv_file(task_id: str, filename: str, content: bytes) -> str:
    _ensure_pending_cv_storage()
    ext = Path(filename).suffix.lower()
    if ext not in (".pdf", ".docx", ".doc", ".txt"):
        ext = ".pdf"
    dest = PENDING_CV_STORAGE / f"{task_id}{ext}"
    dest.write_bytes(content)
    return str(dest)


def _get_cv_file_path(candidate_id: str) -> Path | None:
    for ext in (".pdf", ".docx", ".doc", ".txt"):
        p = CV_STORAGE / f"{candidate_id}{ext}"
        if p.exists():
            return p
    return None


async def _read_upload_content(file: UploadFile) -> bytes:
    content = await file.read(MAX_CV_UPLOAD_BYTES + 1)
    if len(content) > MAX_CV_UPLOAD_BYTES:
        raise ValueError("CV file is too large. Maximum size is 15MB.")
    return content


async def _create_candidate_from_upload(
    file: UploadFile,
    use_llm: bool,
    session: AsyncSession,
) -> CandidateRecord:
    content = await _read_upload_content(file)
    text = extract_text(file.filename or "", content)

    if use_llm:
        parser = get_enhanced_cv_parser()
        profile = await parser.parse_async(text)
        logger.info(
            "Candidate created with enhanced parser",
            extra={
                "cv_filename": file.filename,
                "skills_count": len(profile.skills),
                "negative_count": len(profile.negative_skills),
            },
        )
    else:
        from app.services.cv_parser import parse_cv_text

        profile = parse_cv_text(text)
        logger.info(
            "Candidate created with simple parser",
            extra={"cv_filename": file.filename, "skills_count": len(profile.skills)},
        )

    try:
        esco = await get_esco_extractor()
        esco_result = await esco.extract_skills(text, top_k=20)
        esco_skills = {m.skill.title.lower() for m in esco_result.skills}
        existing_skills = set(s.lower() for s in profile.skills)
        new_from_esco = [s for s in esco_skills if s not in existing_skills]
        if new_from_esco:
            profile.skills.extend(sorted(new_from_esco))
            logger.info("ESCO enriched candidate with %d new skills", len(new_from_esco))
    except Exception:
        logger.warning("ESCO enrichment skipped (not available)")

    existing_candidate = None
    if profile.email:
        stmt = select(Candidate).where(Candidate.email == profile.email)
        result = await session.execute(stmt)
        existing_candidate = result.scalar_one_or_none()

    if existing_candidate:
        logger.info(
            "Candidate already exists, returning existing",
            extra={"email": profile.email, "candidate_id": existing_candidate.id},
        )
        _save_cv_file(existing_candidate.id, file.filename or "cv.pdf", content)
        cv_url = f"/api/v1/candidates/{existing_candidate.id}/cv"
        return CandidateRecord(
            candidate_id=existing_candidate.id,
            cv_url=cv_url,
            full_name=existing_candidate.full_name,
            email=existing_candidate.email,
            phone=existing_candidate.phone,
            skills=existing_candidate.skills,
            skills_detailed=existing_candidate.skills_detailed or [],
            experience=existing_candidate.experience,
            experience_entries=existing_candidate.experience_entries or [],
            education=existing_candidate.education,
            education_entries=existing_candidate.education_entries or [],
            projects=existing_candidate.projects,
            negative_skills=existing_candidate.negative_skills or [],
            learning_skills=existing_candidate.learning_skills or [],
            total_years_experience=existing_candidate.total_years_experience,
            raw_text=existing_candidate.raw_text,
        )

    candidate_id = str(uuid.uuid4())
    candidate = Candidate(
        id=candidate_id,
        full_name=profile.full_name,
        email=profile.email,
        phone=profile.phone,
        skills=profile.skills,
        skills_detailed=[s.model_dump() for s in profile.skills_detailed] if profile.skills_detailed else None,
        experience=profile.experience,
        experience_entries=[e.model_dump() for e in profile.experience_entries] if profile.experience_entries else None,
        education=profile.education,
        education_entries=[e.model_dump() for e in profile.education_entries] if profile.education_entries else None,
        projects=profile.projects,
        negative_skills=profile.negative_skills or None,
        learning_skills=profile.learning_skills or None,
        total_years_experience=profile.total_years_experience,
        raw_text=profile.raw_text,
    )
    session.add(candidate)
    await session.commit()

    _save_cv_file(candidate_id, file.filename or "cv.pdf", content)

    parts = []
    if profile.skills:
        parts.append(f"Skills: {', '.join(profile.skills)}")
    if profile.experience:
        parts.append(f"Experience: {' '.join(profile.experience[:10])}")
    if profile.education:
        parts.append(f"Education: {' '.join(profile.education[:5])}")
    if profile.projects:
        parts.append(f"Projects: {' '.join(profile.projects[:5])}")
    embedding_text = ". ".join(parts) if parts else profile.raw_text

    try:
        embedder = get_embedding_service()
        embedding = (await embedder.embed([embedding_text]))[0]
        store = VectorStore(session)
        await store.upsert_embedding("candidate", candidate_id, embedding)
    except Exception:
        logger.warning(
            "Embedding generation failed for candidate %s — candidate created without vector",
            candidate_id,
        )

    cv_url = f"/api/v1/candidates/{candidate_id}/cv"
    return CandidateRecord(candidate_id=candidate_id, cv_url=cv_url, **profile.model_dump())


@router.get("/skills/categories")
async def list_skill_categories(
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
) -> dict[str, list[str]]:
    return get_categories()


@router.get("/skills")
async def list_all_skills(
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
) -> list[str]:
    return SKILL_KEYWORDS


@router.post("/candidates", response_model=CandidateRecord)
async def create_candidate(
    file: UploadFile = File(...),
    use_llm: bool = Query(
        default=True,
        description="Use LLM (Ollama) for enhanced CV parsing (negation detection, skill levels)",
    ),
    _: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
    session: AsyncSession = Depends(get_db_session),
) -> CandidateRecord:
    try:
        return await _create_candidate_from_upload(file=file, use_llm=use_llm, session=session)
    except ValueError as exc:
        logger.warning("Unsupported CV file", extra={"cv_filename": file.filename})
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Candidate creation failed")
        raise HTTPException(status_code=500, detail=f"Candidate creation failed: {str(exc)}") from exc


@router.post("/candidates/async")
async def create_candidate_async(
    file: UploadFile = File(...),
    use_llm: bool = Query(default=True),
    _: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    try:
        content = await _read_upload_content(file)
        task_id = str(uuid.uuid4())
        file_path = _save_pending_cv_file(task_id, file.filename or "cv.pdf", content)
        await enqueue_cv_processing(
            cv_text=None,
            file_name=file.filename or "cv.pdf",
            use_llm=use_llm,
            file_path=file_path,
            task_id=task_id,
        )
        return {"task_id": task_id, "status": "queued"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/candidates/async/{task_id}")
async def get_async_result(
    task_id: str,
    _: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
) -> dict:
    from app.services.task_queue import get_task_result
    result = await get_task_result(task_id)
    if result is None:
        return {"task_id": task_id, "status": "pending"}
    return result


@router.get("/candidates", response_model=list[CandidateRecord])
async def list_candidates(
    search: str | None = Query(default=None, description="Search by name or email"),
    skills: str | None = Query(default=None, description="Comma-separated skills filter (AND logic)"),
    skill_logic: str | None = Query(default="and", description="Skill filter logic: 'and' or 'or'"),
    min_skills: int | None = Query(default=None, description="Minimum number of skills"),
    min_years: float | None = Query(default=None, description="Minimum years of experience"),
    max_years: float | None = Query(default=None, description="Maximum years of experience"),
    education_search: str | None = Query(default=None, description="Search in education text"),
    university: str | None = Query(default=None, description="Filter by university/institution name"),
    degree: str | None = Query(default=None, description="Filter by degree name"),
    sort_by: str | None = Query(default=None, description="Sort field: name, experience, skills, education, newest"),
    sort_dir: str | None = Query(default="desc", description="Sort direction: asc or desc"),
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
    session: AsyncSession = Depends(get_db_session),
) -> list[CandidateRecord]:
    stmt = select(Candidate)
    if search:
        search_lower = search.lower()
        stmt = stmt.where(
            Candidate.full_name.ilike(f"%{search_lower}%")
            | Candidate.email.ilike(f"%{search_lower}%")
        )
    result = await session.execute(stmt)
    candidates = result.scalars().all()

    records = [
        CandidateRecord(
            candidate_id=candidate.id,
            cv_url=f"/api/v1/candidates/{candidate.id}/cv",
            full_name=candidate.full_name,
            email=candidate.email,
            phone=candidate.phone,
            skills=candidate.skills,
            experience=candidate.experience,
            education=candidate.education,
            education_entries=candidate.education_entries or [],
            projects=candidate.projects,
            total_years_experience=candidate.total_years_experience,
            raw_text=candidate.raw_text,
            skills_detailed=candidate.skills_detailed or [],
            experience_entries=candidate.experience_entries or [],
            negative_skills=candidate.negative_skills or [],
            learning_skills=candidate.learning_skills or [],
        )
        for candidate in candidates
    ]

    if search:
        search_lower = search.lower()
        records = [
            r for r in records
            if (r.full_name and search_lower in r.full_name.lower())
            or (r.email and search_lower in r.email.lower())
        ]

    if skills:
        skill_list = [s.strip().lower() for s in skills.split(",") if s.strip()]
        if skill_logic == "or":
            records = [
                r for r in records
                if any(
                    any(skill_lower in cs.lower() for cs in r.skills)
                    for skill_lower in skill_list
                )
            ]
        else:
            records = [
                r for r in records
                if all(
                    any(skill_lower in cs.lower() for cs in r.skills)
                    for skill_lower in skill_list
                )
            ]

    if min_years is not None and min_years < 0:
        raise HTTPException(status_code=400, detail="min_years must be >= 0")
    if max_years is not None and max_years < 0:
        raise HTTPException(status_code=400, detail="max_years must be >= 0")
    if min_years is not None and max_years is not None and min_years > max_years:
        raise HTTPException(status_code=400, detail="min_years cannot exceed max_years")

    if min_skills is not None:
        records = [r for r in records if len(r.skills) >= min_skills]
    if min_years is not None:
        records = [r for r in records if r.total_years_experience is not None and r.total_years_experience >= min_years]
    if max_years is not None:
        records = [r for r in records if r.total_years_experience is not None and r.total_years_experience <= max_years]

    if education_search:
        q = education_search.lower()
        records = [
            r for r in records
            if any(q in (e or "").lower() for e in r.education)
            or any(q in (e.get("institution", "") or "").lower() for e in r.education_entries)
            or any(q in (e.get("degree", "") or "").lower() for e in r.education_entries)
        ]

    if university:
        q = university.lower()
        records = [
            r for r in records
            if any(q in (e.get("institution", "") or "").lower() for e in r.education_entries)
            or any(q in (e or "").lower() for e in r.education)
        ]

    if degree:
        q = degree.lower()
        records = [
            r for r in records
            if any(q in (e.get("degree", "") or "").lower() for e in r.education_entries)
            or any(q in (e or "").lower() for e in r.education)
        ]

    if sort_by == "name":
        records.sort(key=lambda r: (r.full_name or "").lower(), reverse=(sort_dir == "desc"))
    elif sort_by == "experience":
        records.sort(key=lambda r: r.total_years_experience or 0, reverse=(sort_dir == "desc"))
    elif sort_by == "skills":
        records.sort(key=lambda r: len(r.skills), reverse=(sort_dir == "desc"))
    elif sort_by == "education":
        def _edu_score(r: CandidateRecord) -> int:
            for entry in r.education_entries:
                deg = (entry.get("degree", "") or "").lower()
                if "phd" in deg or "doctor" in deg: return 4
                if "master" in deg or "msc" in deg or "ma" in deg or "mba" in deg: return 3
                if "bachelor" in deg or "bs" in deg or "ba" in deg or "bsc" in deg: return 2
                if "associate" in deg or "diploma" in deg: return 1
            for e in r.education:
                el = e.lower()
                if "phd" in el or "doctor" in el: return 4
                if "master" in el or "msc" in el or "ma" in el or "mba" in el: return 3
                if "bachelor" in el or "bs" in el or "ba" in el or "bsc" in el: return 2
                if "associate" in el or "diploma" in el: return 1
            return 0
        records.sort(key=_edu_score, reverse=(sort_dir == "desc"))
    else:
        records.sort(key=lambda r: r.candidate_id or "", reverse=True)

    return records


@router.get("/candidates/me", response_model=CandidateRecord)
async def get_my_candidate_profile(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> CandidateRecord:
    stmt = select(Candidate).where(Candidate.email == current_user.email)
    result = await session.execute(stmt)
    candidate = result.scalars().first()
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate profile not found")

    return CandidateRecord(
        candidate_id=candidate.id,
        cv_url=f"/api/v1/candidates/{candidate.id}/cv",
        full_name=candidate.full_name,
        email=candidate.email,
        phone=candidate.phone,
        skills=candidate.skills,
        skills_detailed=candidate.skills_detailed or [],
        experience=candidate.experience,
        experience_entries=candidate.experience_entries or [],
        education=candidate.education,
        education_entries=candidate.education_entries or [],
        projects=candidate.projects,
        negative_skills=candidate.negative_skills or [],
        learning_skills=candidate.learning_skills or [],
        total_years_experience=candidate.total_years_experience,
        raw_text=candidate.raw_text,
    )


@router.get("/candidates/{candidate_id}", response_model=CandidateRecord)
async def get_candidate(
    candidate_id: str,
    current_user: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
    session: AsyncSession = Depends(get_db_session),
) -> CandidateRecord:
    await ensure_candidate_access(session, current_user, candidate_id)
    stmt = select(Candidate).where(Candidate.id == candidate_id)
    result = await session.execute(stmt)
    candidate = result.scalar_one_or_none()
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")

    return CandidateRecord(
        candidate_id=candidate.id,
        cv_url=f"/api/v1/candidates/{candidate.id}/cv",
        full_name=candidate.full_name,
        email=candidate.email,
        phone=candidate.phone,
        skills=candidate.skills,
        skills_detailed=candidate.skills_detailed or [],
        experience=candidate.experience,
        experience_entries=candidate.experience_entries or [],
        education=candidate.education,
        education_entries=candidate.education_entries or [],
        projects=candidate.projects,
        negative_skills=candidate.negative_skills or [],
        learning_skills=candidate.learning_skills or [],
        total_years_experience=candidate.total_years_experience,
        raw_text=candidate.raw_text,
    )


@router.get("/candidates/{candidate_id}/cv", response_model=None)
async def preview_cv(
    candidate_id: str,
    download: bool = Query(default=False, description="Download the original CV file"),
    current_user: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
    session: AsyncSession = Depends(get_db_session),
) -> PlainTextResponse | FileResponse:
    await ensure_candidate_access(session, current_user, candidate_id)
    stmt = select(Candidate).where(Candidate.id == candidate_id)
    result = await session.execute(stmt)
    candidate = result.scalar_one_or_none()
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")

    file_path = _get_cv_file_path(candidate_id)
    if download and file_path:
        media_type_map = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".doc": "application/msword",
            ".txt": "text/plain",
        }
        ext = file_path.suffix.lower()
        media_type = media_type_map.get(ext, "application/octet-stream")
        name = f"{candidate.full_name or 'CV'}{ext}"
        return FileResponse(
            path=str(file_path),
            media_type=media_type,
            filename=name,
        )

    if not candidate.raw_text:
        if file_path:
            return PlainTextResponse("CV file is available for download but no extracted text was stored.")
        raise HTTPException(status_code=404, detail="CV content is not available for this candidate")
    return PlainTextResponse(candidate.raw_text)


@router.delete("/candidates/{candidate_id}")
async def delete_candidate(
    candidate_id: str,
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    stmt = select(Candidate).where(Candidate.id == candidate_id)
    result = await session.execute(stmt)
    candidate = result.scalar_one_or_none()
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")

    await session.execute(sa_delete(MatchResult).where(MatchResult.candidate_id == candidate_id))
    await session.execute(sa_delete(Report).where(Report.candidate_id == candidate_id))
    await session.execute(sa_delete(InterviewSession).where(InterviewSession.candidate_id == candidate_id))
    await session.execute(
        sa_delete(Embedding).where(
            Embedding.entity_type == "candidate",
            Embedding.entity_id == candidate_id,
        )
    )

    await session.delete(candidate)
    await session.commit()

    logger.info("Candidate deleted", extra={"candidate_id": candidate_id})
    return {"status": "ok", "message": f"Candidate {candidate_id} deleted"}


@router.delete("/candidates")
async def delete_all_candidates(
    _: User = Depends(require_any_role("owner", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str | int]:
    cand_stmt = select(Candidate)
    cand_result = await session.execute(cand_stmt)
    candidates = cand_result.scalars().all()

    await session.execute(sa_delete(MatchResult).where(MatchResult.candidate_id.in_([c.id for c in candidates])))
    await session.execute(sa_delete(Report).where(Report.candidate_id.in_([c.id for c in candidates])))
    await session.execute(sa_delete(InterviewSession).where(InterviewSession.candidate_id.in_([c.id for c in candidates])))
    await session.execute(sa_delete(Embedding).where(Embedding.entity_type == "candidate"))

    for candidate in candidates:
        await session.delete(candidate)

    await session.commit()

    count = len(candidates)
    logger.info("All candidates deleted", extra={"count": count})
    return {"status": "ok", "message": f"Deleted {count} candidates", "count": count}


@router.post("/candidates/stream")
async def stream_candidates(
    files: list[UploadFile] = File(...),
    use_llm: bool = Query(default=True, description="Use LLM (Ollama) for enhanced CV parsing"),
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    async def event_stream():
        for file in files:
            try:
                record = await _create_candidate_from_upload(file=file, use_llm=use_llm, session=session)
                payload = {
                    "filename": file.filename,
                    "status": "success",
                    "candidate": record.model_dump(),
                }
            except Exception as exc:
                payload = {
                    "filename": file.filename,
                    "status": "failed",
                    "error": str(exc),
                }
            yield json.dumps(payload, ensure_ascii=True) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")
