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
from app.core.redis import close_redis
from app.core.security import RateLimitMiddleware, SecurityHeadersMiddleware

logger = logging.getLogger(__name__)


async def _cv_worker():
    from app.services.task_queue import run_cv_worker
    from app.core.db import SessionLocal
    from app.services.enhanced_cv_parser import get_enhanced_cv_parser
    from app.services.cv_parser import extract_text, parse_cv_text
    from app.services.embedding import get_embedding_service
    from app.services.vector_store import VectorStore
    from app.models.candidate import Candidate
    from sqlalchemy import select
    from pathlib import Path
    import uuid

    def _save_processed_cv(candidate_id: str, file_name: str, content: bytes) -> str:
        storage = Path(settings.cv_storage_path)
        storage.mkdir(parents=True, exist_ok=True)
        ext = Path(file_name).suffix.lower()
        if ext not in (".pdf", ".docx", ".txt"):
            ext = ".pdf"
        dest = storage / f"{candidate_id}{ext}"
        dest.write_bytes(content)
        return f"/api/v1/candidates/{candidate_id}/cv"

    async def process_cv(
        cv_text: str | None,
        file_name: str,
        use_llm: bool,
        file_path: str | None = None,
    ) -> dict:
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
                    cv_url = (
                        _save_processed_cv(existing.id, file_name, content)
                        if content is not None
                        else f"/api/v1/candidates/{existing.id}/cv"
                    )
                    if pending_path:
                        pending_path.unlink(missing_ok=True)
                    return {
                        "candidate_id": existing.id,
                        "cv_url": cv_url,
                        "full_name": existing.full_name,
                        "email": existing.email,
                        "skills": existing.skills,
                        "total_years_experience": existing.total_years_experience,
                        "status": "exists",
                    }

            candidate_id = str(uuid.uuid4())
            candidate = Candidate(
                id=candidate_id, full_name=profile.full_name, email=profile.email,
                phone=profile.phone, skills=profile.skills,
                skills_detailed=[s.model_dump() for s in (profile.skills_detailed or [])],
                experience=profile.experience,
                experience_entries=[e.model_dump() for e in (profile.experience_entries or [])],
                education=profile.education,
                education_entries=[e.model_dump() for e in (profile.education_entries or [])],
                projects=profile.projects, raw_text=cv_text,
                total_years_experience=profile.total_years_experience,
                negative_skills=profile.negative_skills or None,
                learning_skills=profile.learning_skills or None,
            )
            session.add(candidate)
            await session.commit()

            cv_url = (
                _save_processed_cv(candidate_id, file_name, content)
                if content is not None
                else f"/api/v1/candidates/{candidate_id}/cv"
            )
            if pending_path:
                pending_path.unlink(missing_ok=True)

            parts = [f"Skills: {', '.join(profile.skills)}"]
            if profile.experience:
                parts.append(f"Experience: {' '.join(profile.experience[:10])}")
            if profile.education:
                parts.append(f"Education: {' '.join(profile.education[:5])}")
            try:
                embedder = get_embedding_service()
                embedding = (await embedder.embed([". ".join(parts)]))[0]
                store = VectorStore(session)
                await store.upsert_embedding("candidate", candidate_id, embedding)
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
                "total_years_experience": profile.total_years_experience,
                "status": "created",
            }

    await run_cv_worker(process_cv)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    try:
        settings.validate_runtime()
        await init_db()
        logger.info("Embedding provider: %s", settings.embedding_provider)
        worker_task = asyncio.create_task(_cv_worker())
        yield
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
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    if settings.trusted_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    if settings.rate_limit_enabled:
        app.add_middleware(
            RateLimitMiddleware,
            requests=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled application error", extra={"path": request.url.path})
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    return app


app = create_app()
