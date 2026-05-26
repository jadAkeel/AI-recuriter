from __future__ import annotations

import logging

from sqlalchemy import JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.db import engine
from app.models.base import Base

logger = logging.getLogger(__name__)

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # pragma: no cover
    Vector = None

_POSTGRES = engine.dialect.name == "postgresql"
_USE_VECTOR = _POSTGRES and Vector is not None

if not _USE_VECTOR and Vector is not None:
    logger.info("pgvector available but not used (non-PostgreSQL database)")


class Embedding(Base):
    __tablename__ = "embeddings"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", name="uq_embeddings_entity"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(50), index=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding_json: Mapped[list[float]] = mapped_column(JSON)
    embedding_language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_fallback: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="0")

    if _USE_VECTOR:
        embedding_vector: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dimension), nullable=True)
    else:
        embedding_vector: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)

