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
    import app.models.audit_log  # noqa: F401
    import app.models.report_version  # noqa: F401
    import app.models.skill_evidence  # noqa: F401
    import app.models.skill_feedback  # noqa: F401
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
    Adds missing embedding metadata columns and other dynamic columns for older databases.
    """
    # 1. Update embeddings table
    emb_columns = {
        "provider": "VARCHAR(50)",
        "model_name": "VARCHAR(255)",
        "source_hash": "VARCHAR(64)",
        "embedding_language": "VARCHAR(50)",
        "is_fallback": "BOOLEAN DEFAULT FALSE" if engine.dialect.name == "postgresql" else "INTEGER DEFAULT 0",
    }
    if engine.dialect.name == "sqlite":
        result = await connection.execute(text("PRAGMA table_info(embeddings)"))
        existing_emb = {row[1] for row in result.fetchall()}
    else:
        result = await connection.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'embeddings'
              AND table_schema = current_schema()
        """))
        existing_emb = {row[0] for row in result.fetchall()}

    for column, column_type in emb_columns.items():
        if column not in existing_emb:
            logger.info("Adding column %s to table embeddings", column)
            await connection.execute(text(f"ALTER TABLE embeddings ADD COLUMN {column} {column_type}"))

    # 2. Update knowledge_documents table
    kd_columns = {
        "embedding_multilingual": "TEXT" if engine.dialect.name == "sqlite" else "JSON",
    }
    if engine.dialect.name == "sqlite":
        result = await connection.execute(text("PRAGMA table_info(knowledge_documents)"))
        existing_kd = {row[1] for row in result.fetchall()}
    else:
        result = await connection.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'knowledge_documents'
              AND table_schema = current_schema()
        """))
        existing_kd = {row[0] for row in result.fetchall()}

    for column, column_type in kd_columns.items():
        if column not in existing_kd:
            logger.info("Adding column %s to table knowledge_documents", column)
            await connection.execute(text(f"ALTER TABLE knowledge_documents ADD COLUMN {column} {column_type}"))

    # 3. Update candidates table
    cand_columns = {
        "uncatalogued_skills": "TEXT" if engine.dialect.name == "sqlite" else "JSON",
    }
    
    # Check if table candidates exists first
    has_candidates = False
    if engine.dialect.name == "sqlite":
        res = await connection.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='candidates'"))
        has_candidates = res.scalar() is not None
    else:
        res = await connection.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_name = 'candidates'
                  AND table_schema = current_schema()
            )
        """))
        has_candidates = res.scalar() is True

    if has_candidates:
        if engine.dialect.name == "sqlite":
            result = await connection.execute(text("PRAGMA table_info(candidates)"))
            existing_cand = {row[1] for row in result.fetchall()}
        else:
            result = await connection.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'candidates'
                  AND table_schema = current_schema()
            """))
            existing_cand = {row[0] for row in result.fetchall()}

        for column, column_type in cand_columns.items():
            if column not in existing_cand:
                logger.info("Adding column %s to table candidates", column)
                await connection.execute(text(f"ALTER TABLE candidates ADD COLUMN {column} {column_type}"))

    # 4. Update match_results and reports for production-readiness metadata.
    await _ensure_table_columns(
        connection,
        "match_results",
        {
            "scoring_version": "VARCHAR(50)",
            "provider_metadata": "TEXT" if engine.dialect.name == "sqlite" else "JSON",
            "is_stale": "BOOLEAN DEFAULT FALSE" if engine.dialect.name == "postgresql" else "INTEGER DEFAULT 0",
        },
    )
    await _ensure_table_columns(
        connection,
        "reports",
        {
            "scoring_version": "VARCHAR(50)",
            "provider_metadata": "TEXT" if engine.dialect.name == "sqlite" else "JSON",
            "report_version": "INTEGER DEFAULT 1",
            "is_stale": "BOOLEAN DEFAULT FALSE" if engine.dialect.name == "postgresql" else "INTEGER DEFAULT 0",
        },
    )


async def _ensure_table_columns(connection, table_name: str, columns: dict[str, str]) -> None:
    """
    Adds missing columns for legacy dev databases until Alembic owns all upgrades.
    """
    if engine.dialect.name == "sqlite":
        has_table_result = await connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        )
        if has_table_result.scalar() is None:
            return
        result = await connection.execute(text(f"PRAGMA table_info({table_name})"))
        existing = {row[1] for row in result.fetchall()}
    else:
        has_table_result = await connection.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = :table_name
                      AND table_schema = current_schema()
                )
            """),
            {"table_name": table_name},
        )
        if has_table_result.scalar() is not True:
            return
        result = await connection.execute(
            text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = :table_name
                  AND table_schema = current_schema()
            """),
            {"table_name": table_name},
        )
        existing = {row[0] for row in result.fetchall()}

    for column, column_type in columns.items():
        if column not in existing:
            logger.info("Adding column %s to table %s", column, table_name)
            await connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column} {column_type}"))
