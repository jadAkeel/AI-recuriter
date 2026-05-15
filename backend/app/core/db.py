from __future__ import annotations

import logging
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.base import Base

logger = logging.getLogger(__name__)

def _create_engine() -> AsyncEngine:
    url = str(settings.database_url)
    # Enable WAL mode for SQLite to allow concurrent reads during writes
    if url.startswith("sqlite"):
        separator = "&" if "?" in url else "?"
        url += f"{separator}journal_mode=wal&timeout=10000"
    return create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
    )


engine: AsyncEngine = _create_engine()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


def reset_engine() -> None:
    """Recreate engine/session after env-based settings changes.

    Tests set DATABASE_URL via environment variables; settings are loaded at import
    time, so we need a way to re-initialize the engine with the updated URL.
    """

    global engine, SessionLocal
    engine = _create_engine()
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def check_db_connection() -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("Database connectivity check failed")
        return False


async def init_db() -> None:
    # Import models here to avoid circular imports (models reference db, db references models)
    import app.models.candidate  # noqa: F401
    import app.models.embedding  # noqa: F401
    import app.models.interview  # noqa: F401
    import app.models.job  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.match_result  # noqa: F401
    import app.models.report  # noqa: F401
    import app.models.user  # noqa: F401

    async with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "postgresql":
            result = await connection.execute(text("""
                SELECT format_type(a.atttypid, a.atttypmod)
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = 'embeddings'
                  AND n.nspname = current_schema()
                  AND a.attname = 'embedding_vector'
                  AND NOT a.attisdropped
            """))
            vector_type = result.scalar_one_or_none()
            expected_type = f"vector({settings.embedding_dimension})"
            if vector_type and vector_type != expected_type:
                raise RuntimeError(
                    "Embedding vector column dimension mismatch: "
                    f"database has {vector_type}, settings expect {expected_type}. "
                    "Run a migration or set EMBEDDING_DIMENSION to the existing schema."
                )
