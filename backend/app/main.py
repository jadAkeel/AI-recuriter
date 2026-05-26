from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.db import init_db
from app.core.logging import configure_logging, shutdown_logging
from app.core.redis import close_redis, get_redis
from app.core.security import RateLimitMiddleware, SecurityHeadersMiddleware

logger = logging.getLogger(__name__)


# Background worker that processes CV uploads from the task queue
async def _cv_worker():
    """
    Runs the background worker that processes queued CV uploads.
    """
    from app.services.task_queue import run_cv_worker
    from app.core.db import SessionLocal
    from app.services.enhanced_cv_parser import get_enhanced_cv_parser
    from app.services.cv_parser import extract_text, parse_cv_text
    from app.services.candidate_text import upsert_candidate_embedding
    from app.services.skill_evidence import replace_candidate_skill_evidence
    from app.models.candidate import Candidate
    from sqlalchemy import select
    from pathlib import Path
    import uuid

    # Save the uploaded CV file to disk for later download
    def _save_processed_cv(candidate_id: str, file_name: str, content: bytes) -> str:
        """
        Saves a processed CV file and returns its API URL.
        """
        storage = Path(settings.cv_storage_path)
        storage.mkdir(parents=True, exist_ok=True)
        ext = Path(file_name).suffix.lower()
        if ext not in (".pdf", ".docx", ".txt"):
            ext = ".pdf"
        dest = storage / f"{candidate_id}{ext}"
        dest.write_bytes(content)
        return f"/api/v1/candidates/{candidate_id}/cv"

    # Remove old CV files when a candidate is re-uploaded
    def _delete_processed_cv_files(candidate_id: str) -> None:
        """
        Removes old stored CV files for a candidate.
        """
        storage = Path(settings.cv_storage_path)
        for ext in (".pdf", ".docx", ".txt"):
            (storage / f"{candidate_id}{ext}").unlink(missing_ok=True)

    # Copy all parsed profile fields onto the DB candidate record
    def _apply_profile_to_candidate(candidate: Candidate, profile) -> None:
        """
        Copies parsed profile fields onto a candidate database model.
        """
        candidate.full_name = profile.full_name
        candidate.email = profile.email
        candidate.phone = profile.phone
        candidate.skills = profile.skills
        candidate.skills_detailed = [s.model_dump() for s in (profile.skills_detailed or [])]
        candidate.experience = profile.experience
        candidate.experience_entries = [e.model_dump() for e in (profile.experience_entries or [])]
        candidate.education = profile.education
        candidate.education_entries = [e.model_dump() for e in (profile.education_entries or [])]
        candidate.projects = profile.projects
        candidate.raw_text = profile.raw_text
        candidate.total_years_experience = profile.total_years_experience
        candidate.negative_skills = profile.negative_skills or None
        candidate.learning_skills = profile.learning_skills or None
        candidate.uncatalogued_skills = profile.uncatalogued_skills or None

    async def process_cv(
        cv_text: str | None,
        file_name: str,
        use_llm: bool,
        file_path: str | None = None,
    ) -> dict:
        """
        Processes one queued CV upload into a candidate record.
        """
        content: bytes | None = None
        pending_path = Path(file_path) if file_path else None
        if pending_path and pending_path.exists():
            content = pending_path.read_bytes()
            cv_text = extract_text(file_name, content)
        if not cv_text:
            raise ValueError("CV text could not be extracted")

        async with SessionLocal() as session:
            parser = get_enhanced_cv_parser() if use_llm else None
            profile = await parser.parse_async(cv_text) if parser else parse_cv_text(cv_text)

            if profile.email:
                stmt = select(Candidate).where(Candidate.email == profile.email)
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()
                if existing:
                    _apply_profile_to_candidate(existing, profile)
                    await session.commit()
                    await replace_candidate_skill_evidence(session, existing, commit=True)
                    if content is not None:
                        _delete_processed_cv_files(existing.id)
                        cv_url = _save_processed_cv(existing.id, file_name, content)
                    else:
                        cv_url = f"/api/v1/candidates/{existing.id}/cv"
                    try:
                        await upsert_candidate_embedding(session, existing.id, profile)
                    except Exception:
                        logger.warning(
                            "Embedding update failed for existing candidate %s - candidate data saved",
                            existing.id,
                        )
                    if pending_path:
                        pending_path.unlink(missing_ok=True)
                    return {
                        "candidate_id": existing.id,
                        "cv_url": cv_url,
                        "full_name": profile.full_name,
                        "email": profile.email,
                        "skills": profile.skills,
                        "uncatalogued_skills": profile.uncatalogued_skills,
                        "total_years_experience": profile.total_years_experience,
                        "status": "updated",
                    }

            candidate_id = str(uuid.uuid4())
            candidate = Candidate(id=candidate_id)
            _apply_profile_to_candidate(candidate, profile)
            session.add(candidate)
            await session.commit()
            await replace_candidate_skill_evidence(session, candidate, commit=True)

            cv_url = (
                _save_processed_cv(candidate_id, file_name, content)
                if content is not None
                else f"/api/v1/candidates/{candidate_id}/cv"
            )
            if pending_path:
                pending_path.unlink(missing_ok=True)

            try:
                await upsert_candidate_embedding(session, candidate_id, profile)
            except Exception:
                logger.warning(
                    "Embedding generation failed for candidate %s — candidate created without vector",
                    candidate_id,
                )

            return {
                "candidate_id": candidate_id,
                "cv_url": cv_url,
                "full_name": profile.full_name,
                "email": profile.email,
                "skills": profile.skills,
                "uncatalogued_skills": profile.uncatalogued_skills,
                "total_years_experience": profile.total_years_experience,
                "status": "created",
            }

    await run_cv_worker(process_cv)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Starts and stops application resources around the FastAPI lifespan.
    """
    configure_logging()
    try:
        settings.validate_runtime()
        await init_db()
        if settings.is_production and await get_redis() is None:
            raise RuntimeError("Redis is required for production CV task queueing")
        logger.info("Embedding provider: %s", settings.embedding_provider)
        worker_task = asyncio.create_task(_cv_worker()) if settings.run_cv_worker_in_api else None
        if worker_task is None:
            logger.info("In-process CV worker disabled; expecting external worker service")
        yield
        if worker_task is not None:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
    finally:
        await close_redis()
        try:
            from app.services.ollama_cross_encoder import get_ollama_cross_encoder

            await get_ollama_cross_encoder().close()
        except Exception:
            logger.debug("Cross-encoder cleanup skipped", exc_info=True)
        shutdown_logging()


def create_app() -> FastAPI:
    """
    Creates and configures the FastAPI application.
    """
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    trusted = settings.trusted_hosts + ["*.ngrok-free.app", "*.ngrok-free.dev", "*.ngrok.io", "localhost", "127.0.0.1"]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted)
    if settings.rate_limit_enabled:
        app.add_middleware(
            RateLimitMiddleware,
            requests=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=r"https?://(.*\.ngrok-free\.(app|dev)|.*\.ngrok\.io|lhr\.life|localhost:\d+)",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """
        Logs unhandled errors and returns a generic API error response.
        """
        logger.exception("Unhandled application error", extra={"path": request.url.path})
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    return app


app = create_app()
