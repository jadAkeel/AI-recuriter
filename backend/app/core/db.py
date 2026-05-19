from __future__ import annotations

import logging
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.base import Base

logger = logging.getLogger(__name__)

def _create_engine() -> AsyncEngine:
    """
    Creates the async database engine from current settings.
    """
    url = str(settings.database_url)
    connect_args = {}
    # Enable WAL mode for SQLite to allow concurrent reads during writes
    if url.startswith("sqlite"):
        separator = "&" if "?" in url else "?"
        url += f"{separator}journal_mode=wal&timeout=10000"
        connect_args["timeout"] = 10
    return create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


# Global async engine and session factory
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
    """
    Yields an async database session for dependency injection.
    """
    async with SessionLocal() as session:
        yield session


async def check_db_connection() -> bool:
    """
    Checks whether the database responds to a simple query.
    """
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("Database connectivity check failed")
        return False


async def init_db() -> None:
    # Import models here to avoid circular imports (models reference db, db references models)
    """
    Creates database tables and validates embedding schema requirements.
    """
    import app.models.candidate  # noqa: F401
    import app.models.embedding  # noqa: F401
    import app.models.interview  # noqa: F401
    import app.models.job  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.match_result  # noqa: F401
    import app.models.report  # noqa: F401
    import app.models.user  # noqa: F401

    async with engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            await connection.execute(text("PRAGMA journal_mode=WAL"))
            await connection.execute(text("PRAGMA foreign_keys=ON"))
        if engine.dialect.name == "postgresql":
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.create_all)
        await _ensure_embedding_metadata_columns(connection)
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


async def _ensure_embedding_metadata_columns(connection) -> None:
    """
    Adds missing embedding metadata columns for older databases.
    """
    columns = {
        "provider": "VARCHAR(50)",
        "model_name": "VARCHAR(255)",
        "source_hash": "VARCHAR(64)",
    }
    if engine.dialect.name == "sqlite":
        result = await connection.execute(text("PRAGMA table_info(embeddings)"))
        existing = {row[1] for row in result.fetchall()}
    else:
        result = await connection.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'embeddings'
              AND table_schema = current_schema()
        """))
        existing = {row[0] for row in result.fetchall()}

    for column, column_type in columns.items():
        if column not in existing:
            await connection.execute(text(f"ALTER TABLE embeddings ADD COLUMN {column} {column_type}"))
