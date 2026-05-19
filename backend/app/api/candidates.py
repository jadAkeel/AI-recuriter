from __future__ import annotations

import logging
import json
import uuid
import re
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Query
from fastapi.responses import StreamingResponse, PlainTextResponse, FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal, get_db_session
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
from app.services.candidate_text import build_candidate_embedding_text_from_profile
from app.services.cv_parser import extract_text
from app.services.enhanced_cv_parser import get_enhanced_cv_parser
from app.services.embedding import embedding_metadata_for_text, get_embedding_service
from app.services.esco_extractor import get_esco_extractor
from app.services.skill_catalog import (
    SKILL_KEYWORDS,
    get_categories,
    normalize_skill_name,
    normalize_text_for_skill_matching,
    skill_in_text,
)
from app.services.task_queue import enqueue_cv_processing
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)

router = APIRouter()

CV_STORAGE = Path(settings.cv_storage_path)
PENDING_CV_STORAGE = CV_STORAGE.parent / "pending_cvs"
MAX_CV_UPLOAD_BYTES = settings.max_upload_bytes
ALLOWED_CV_EXTENSIONS = {".pdf", ".docx", ".txt", ""}


def _ensure_cv_storage():
    """
    Ensures the permanent CV storage directory exists.
    """
    CV_STORAGE.mkdir(parents=True, exist_ok=True)


def _ensure_pending_cv_storage():
    """
    Ensures the pending CV upload directory exists.
    """
    PENDING_CV_STORAGE.mkdir(parents=True, exist_ok=True)


def _safe_download_name(name: str | None, ext: str) -> str:
    """
    Builds a safe filename for downloading a stored CV.
    """
    base = re.sub(r"[^A-Za-z0-9._ -]+", "_", name or "CV").strip(" ._")
    return f"{base or 'CV'}{ext}"


def _validate_cv_filename(filename: str | None) -> str:
    """
    Validates a CV filename and returns a safe fallback name.
    """
    safe_name = filename or "cv.txt"
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_CV_EXTENSIONS:
        raise ValueError("Unsupported CV file type. Allowed types: PDF, DOCX, TXT.")
    return safe_name


def _save_cv_file(candidate_id: str, filename: str, content: bytes) -> str:
    """
    Saves an uploaded CV under the candidate ID.
    """
    _ensure_cv_storage()
    ext = Path(filename).suffix.lower()
    if ext not in (".pdf", ".docx", ".txt"):
        ext = ".pdf"
    dest = CV_STORAGE / f"{candidate_id}{ext}"
    dest.write_bytes(content)
    return str(dest)


def _save_pending_cv_file(task_id: str, filename: str, content: bytes) -> str:
    """
    Saves a queued CV upload under its task ID.
    """
    _ensure_pending_cv_storage()
    ext = Path(filename).suffix.lower()
    if ext not in (".pdf", ".docx", ".txt"):
        ext = ".pdf"
    dest = PENDING_CV_STORAGE / f"{task_id}{ext}"
    dest.write_bytes(content)
    return str(dest)


def _get_cv_file_path(candidate_id: str) -> Path | None:
    """
    Finds the stored CV file for a candidate.
    """
    for ext in (".pdf", ".docx", ".txt"):
        p = CV_STORAGE / f"{candidate_id}{ext}"
        if p.exists():
            return p
    return None


def _delete_cv_files(candidate_id: str) -> None:
    """
    Deletes stored CV files for a candidate.
    """
    for ext in (".pdf", ".docx", ".txt"):
        path = CV_STORAGE / f"{candidate_id}{ext}"
        try:
            path.unlink(missing_ok=True)
        except Exception:
            logger.warning("Failed to delete CV file", extra={"candidate_id": candidate_id, "path": str(path)})


async def _read_upload_content(file: UploadFile) -> bytes:
    """
    Reads an uploaded CV while enforcing type and size limits.
    """
    _validate_cv_filename(file.filename)
    content = await file.read(MAX_CV_UPLOAD_BYTES + 1)
    if len(content) > MAX_CV_UPLOAD_BYTES:
        max_mb = MAX_CV_UPLOAD_BYTES // (1024 * 1024)
        raise ValueError(f"CV file is too large. Maximum size is {max_mb}MB.")
    return content


def _esco_skill_has_text_evidence(skill: str, cv_text: str) -> bool:
    """
    Checks whether an ESCO skill is explicitly present in source text.
    """
    normalized_text = normalize_text_for_skill_matching(cv_text)
    return bool(normalized_text and skill_in_text(skill, normalized_text))


def _apply_profile_to_candidate(candidate: Candidate, profile) -> None:
    """
    Copies parsed profile fields onto a candidate database model.
    """
    candidate.full_name = profile.full_name
    candidate.email = profile.email
    candidate.phone = profile.phone
    candidate.skills = profile.skills
    candidate.skills_detailed = [s.model_dump() for s in profile.skills_detailed] if profile.skills_detailed else None
    candidate.experience = profile.experience
    candidate.experience_entries = [e.model_dump() for e in profile.experience_entries] if profile.experience_entries else None
    candidate.education = profile.education
    candidate.education_entries = [e.model_dump() for e in profile.education_entries] if profile.education_entries else None
    candidate.projects = profile.projects
    candidate.negative_skills = profile.negative_skills or None
    candidate.learning_skills = profile.learning_skills or None
    candidate.total_years_experience = profile.total_years_experience
    candidate.raw_text = profile.raw_text


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
        context = str(detail.get("context", "") or "").strip()
        if name and status not in {"no_experience", "learning"} and context:
            skills.append(name)

    result: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        normalized = normalize_skill_name(skill)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


async def _upsert_candidate_embedding(session: AsyncSession, candidate_id: str, profile) -> None:
    """
    Creates or updates the embedding stored for a candidate profile.
    """
    embedding_text = build_candidate_embedding_text_from_profile(profile)
    embedder = get_embedding_service()
    embedding = (await embedder.embed([embedding_text]))[0]
    store = VectorStore(session)
    await store.upsert_embedding(
        "candidate",
        candidate_id,
        embedding,
        metadata=embedding_metadata_for_text(embedding_text),
    )


async def _create_candidate_from_content(
    filename: str,
    content: bytes,
    use_llm: bool,
    session: AsyncSession,
) -> CandidateRecord:
    """
    Parses CV content, creates or updates the candidate, and stores its embedding.
    """
    filename = _validate_cv_filename(filename)
    text = extract_text(filename, content)

    if use_llm:
        parser = get_enhanced_cv_parser()
        profile = await parser.parse_async(text)
        logger.info(
            "Candidate created with enhanced parser",
            extra={
                "cv_filename": filename,
                "skills_count": len(profile.skills),
                "negative_count": len(profile.negative_skills),
            },
        )
    else:
        from app.services.cv_parser import parse_cv_text

        profile = parse_cv_text(text)
        logger.info(
            "Candidate created with simple parser",
            extra={"cv_filename": filename, "skills_count": len(profile.skills)},
        )

    if settings.esco_api_enabled:
        try:
            esco = await get_esco_extractor()
            esco_result = await esco.extract_skills(text, top_k=20)
            esco_skills = {
                normalize_skill_name(m.skill.title)
                for m in esco_result.skills
                if _esco_skill_has_text_evidence(m.skill.title, text)
            }
            existing_skills = {normalize_skill_name(s) for s in profile.skills}
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
            "Candidate already exists, updating from new CV",
            extra={"email": profile.email, "candidate_id": existing_candidate.id},
        )
        _apply_profile_to_candidate(existing_candidate, profile)
        await session.commit()
        _delete_cv_files(existing_candidate.id)
        _save_cv_file(existing_candidate.id, filename, content)
        try:
            await _upsert_candidate_embedding(session, existing_candidate.id, profile)
        except Exception:
            logger.warning(
                "Embedding update failed for existing candidate %s - candidate data saved",
                existing_candidate.id,
            )
        cv_url = f"/api/v1/candidates/{existing_candidate.id}/cv"
        return CandidateRecord(
            candidate_id=existing_candidate.id,
            cv_url=cv_url,
            **profile.model_dump(),
        )

    candidate_id = str(uuid.uuid4())
    candidate = Candidate(id=candidate_id)
    _apply_profile_to_candidate(candidate, profile)
    session.add(candidate)
    await session.commit()

    _save_cv_file(candidate_id, filename, content)

    try:
        await _upsert_candidate_embedding(session, candidate_id, profile)
    except Exception:
        logger.warning(
            "Embedding generation failed for candidate %s — candidate created without vector",
            candidate_id,
        )

    cv_url = f"/api/v1/candidates/{candidate_id}/cv"
    return CandidateRecord(candidate_id=candidate_id, cv_url=cv_url, **profile.model_dump())


async def _create_candidate_from_upload(
    file: UploadFile,
    use_llm: bool,
    session: AsyncSession,
) -> CandidateRecord:
    """
    Reads an uploaded CV and creates or updates the candidate record.
    """
    content = await _read_upload_content(file)
    return await _create_candidate_from_content(
        filename=file.filename or "cv.txt",
        content=content,
        use_llm=use_llm,
        session=session,
    )


@router.get("/skills/categories")
async def list_skill_categories(
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
) -> dict[str, list[str]]:
    """
    Returns the skill catalog grouped by category.
    """
    return get_categories()


@router.get("/skills")
async def list_all_skills(
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
) -> list[str]:
    """
    Returns all known skill names from the catalog.
    """
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
    """
    Handles a synchronous candidate CV upload.
    """
    try:
        return await _create_candidate_from_upload(file=file, use_llm=use_llm, session=session)
    except ValueError as exc:
        logger.warning("Unsupported CV file", extra={"cv_filename": file.filename})
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Candidate creation failed")
        raise HTTPException(status_code=500, detail="Candidate creation failed") from exc


@router.post("/candidates/async")
async def create_candidate_async(
    file: UploadFile = File(...),
    use_llm: bool = Query(default=True),
    _: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
) -> dict[str, str]:
    """
    Queues a candidate CV upload for background processing.
    """
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
    """
    Returns the result of a queued candidate CV processing task.
    """
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
    limit: int = Query(default=200, ge=1, le=1000, description="Maximum candidates to return"),
    offset: int = Query(default=0, ge=0, description="Number of candidates to skip after filtering"),
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
    session: AsyncSession = Depends(get_db_session),
) -> list[CandidateRecord]:
    """
    Lists candidates with filtering, sorting, and pagination.
    """
    if skill_logic not in {"and", "or"}:
        raise HTTPException(status_code=400, detail="skill_logic must be 'and' or 'or'")
    if sort_dir not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="sort_dir must be 'asc' or 'desc'")

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
            skills=_candidate_display_skills(candidate),
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
        skill_list = [normalize_skill_name(s) for s in skills.split(",") if s.strip()]
        if skill_logic == "or":
            records = [
                r for r in records
                if any(skill_lower in {normalize_skill_name(cs) for cs in r.skills} for skill_lower in skill_list)
            ]
        else:
            records = [
                r for r in records
                if all(skill_lower in {normalize_skill_name(cs) for cs in r.skills} for skill_lower in skill_list)
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
            """
            Scores education level for candidate sorting.
            """
            for entry in r.education_entries:
                deg = (entry.get("degree", "") or "").lower()
                if "phd" in deg or "doctor" in deg:
                    return 4
                if "master" in deg or "msc" in deg or "ma" in deg or "mba" in deg:
                    return 3
                if "bachelor" in deg or "bs" in deg or "ba" in deg or "bsc" in deg:
                    return 2
                if "associate" in deg or "diploma" in deg:
                    return 1
            for e in r.education:
                el = e.lower()
                if "phd" in el or "doctor" in el:
                    return 4
                if "master" in el or "msc" in el or "ma" in el or "mba" in el:
                    return 3
                if "bachelor" in el or "bs" in el or "ba" in el or "bsc" in el:
                    return 2
                if "associate" in el or "diploma" in el:
                    return 1
            return 0
        records.sort(key=_edu_score, reverse=(sort_dir == "desc"))
    else:
        records.sort(key=lambda r: r.candidate_id or "", reverse=True)

    return records[offset: offset + limit]


@router.get("/candidates/me", response_model=CandidateRecord)
async def get_my_candidate_profile(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> CandidateRecord:
    """
    Returns the candidate profile linked to the current user email.
    """
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
        skills=_candidate_display_skills(candidate),
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
    """
    Returns one candidate profile after access checks.
    """
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
        skills=_candidate_display_skills(candidate),
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
    """
    Returns extracted CV text or the stored CV file for download.
    """
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
        name = _safe_download_name(candidate.full_name, ext)
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
    """
    Deletes a candidate and all dependent records.
    """
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
    _delete_cv_files(candidate_id)

    logger.info("Candidate deleted", extra={"candidate_id": candidate_id})
    return {"status": "ok", "message": f"Candidate {candidate_id} deleted"}


@router.delete("/candidates")
async def delete_all_candidates(
    _: User = Depends(require_any_role("owner", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str | int]:
    """
    Deletes all candidates and their dependent records.
    """
    cand_stmt = select(Candidate)
    cand_result = await session.execute(cand_stmt)
    candidates = cand_result.scalars().all()

    candidate_ids = [c.id for c in candidates]
    if candidate_ids:
        await session.execute(sa_delete(MatchResult).where(MatchResult.candidate_id.in_(candidate_ids)))
        await session.execute(sa_delete(Report).where(Report.candidate_id.in_(candidate_ids)))
        await session.execute(sa_delete(InterviewSession).where(InterviewSession.candidate_id.in_(candidate_ids)))
    await session.execute(sa_delete(Embedding).where(Embedding.entity_type == "candidate"))

    for candidate in candidates:
        _delete_cv_files(candidate.id)
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
) -> StreamingResponse:
    """
    Streams results while uploading and parsing multiple CV files.
    """
    prepared_files: list[tuple[str, bytes]] = []
    for file in files:
        try:
            prepared_files.append((file.filename or "cv.txt", await _read_upload_content(file)))
        except ValueError as exc:
            prepared_files.append((file.filename or "cv.txt", b""))
            logger.warning("Rejected CV in stream upload", extra={"cv_filename": file.filename, "error": str(exc)})

    async def event_stream():
        """
        Yields one NDJSON result per streamed CV upload.
        """
        for filename, content in prepared_files:
            try:
                if not content:
                    raise ValueError("CV file is empty or invalid")
                async with SessionLocal() as stream_session:
                    record = await _create_candidate_from_content(
                        filename=filename,
                        content=content,
                        use_llm=use_llm,
                        session=stream_session,
                    )
                payload = {
                    "filename": filename,
                    "status": "success",
                    "candidate": record.model_dump(),
                }
            except Exception as exc:
                payload = {
                    "filename": filename,
                    "status": "failed",
                    "error": str(exc),
                }
            yield json.dumps(payload, ensure_ascii=True) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")
