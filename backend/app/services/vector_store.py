from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.models.embedding import Embedding
from app.services.embedding import validate_embedding_vector

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(self, session: AsyncSession) -> None:
        """
        Initializes vector storage around the active database session.
        """
        self.session = session
        self.is_postgres = db.engine.dialect.name == "postgresql"

    async def upsert_embedding(
        self,
        entity_type: str,
        entity_id: str,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> None:
        """
        Creates or updates an embedding row for an entity.
        """
        self._validate_embedding_dimension(embedding)
        stmt = select(Embedding).where(
            Embedding.entity_type == entity_type,
            Embedding.entity_id == entity_id,
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()

        meta = metadata or {}
        provider = meta.get("provider") or "hash"
        is_fallback = meta.get("is_fallback")
        if is_fallback is None:
            is_fallback = provider.lower() == "hash"
        if isinstance(is_fallback, str):
            is_fallback = is_fallback.lower() == "true"
        
        embedding_language = meta.get("embedding_language")

        if row is None:
            row = Embedding(
                entity_type=entity_type,
                entity_id=entity_id,
                provider=provider,
                model_name=meta.get("model_name"),
                source_hash=meta.get("source_hash"),
                embedding_json=embedding,
                embedding_vector=embedding,
                embedding_language=embedding_language,
                is_fallback=bool(is_fallback),
            )
            self.session.add(row)
        else:
            row.provider = provider
            row.model_name = meta.get("model_name")
            row.source_hash = meta.get("source_hash")
            row.embedding_json = embedding
            row.embedding_vector = embedding
            row.embedding_language = embedding_language
            row.is_fallback = bool(is_fallback)

        if commit:
            await self.session.commit()

    async def query_similar(
        self,
        entity_type: str,
        embedding: list[float],
        top_k: int = 5,
        language: str | None = None,
    ) -> list[tuple[str, float]]:
        """
        Finds the most similar stored embeddings for an entity type.
        """
        self._validate_embedding_dimension(embedding)
        if np.linalg.norm(np.array(embedding, dtype=np.float32)) == 0:
            return []
        if self.is_postgres:
            return await self._query_postgres(entity_type, embedding, top_k, language)

        return await self._query_in_memory(entity_type, embedding, top_k, language)

    async def _query_postgres(
        self,
        entity_type: str,
        embedding: list[float],
        top_k: int,
        language: str | None = None,
    ) -> list[tuple[str, float]]:
        """
        Queries PostgreSQL pgvector for nearest embeddings.
        """
        if Embedding.embedding_vector is None:
            logger.warning("Vector column unavailable, falling back to in-memory scoring")
            return await self._query_in_memory(entity_type, embedding, top_k, language)

        stmt: Select = (
            select(Embedding.entity_id, Embedding.embedding_vector.cosine_distance(embedding))
            .where(Embedding.entity_type == entity_type)
        )
        if language:
            stmt = stmt.where(Embedding.embedding_language == language)
            
        stmt = (
            stmt.order_by(Embedding.embedding_vector.cosine_distance(embedding))
            .limit(top_k)
        )
        result = await self.session.execute(stmt)
        rows = result.all()
        return [(row[0], float(1 - row[1])) for row in rows]

    async def _query_in_memory(
        self,
        entity_type: str,
        embedding: list[float],
        top_k: int,
        language: str | None = None,
    ) -> list[tuple[str, float]]:
        """
        Computes cosine similarity in Python for non-pgvector databases.
        """
        stmt = select(Embedding.entity_id, Embedding.embedding_json).where(
            Embedding.entity_type == entity_type
        )
        if language:
            stmt = stmt.where(Embedding.embedding_language == language)
        result = await self.session.execute(stmt)
        rows = result.all()

        count = len(rows)
        if count > 5000:
            logger.warning("Large in-memory similarity query (%d rows). Consider using PostgreSQL + pgvector.", count)

        if count == 0:
            return []

        query = np.array(embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query)
        if query_norm == 0:
            return []

        valid_rows = []
        valid_embeddings = []
        query_dim = len(embedding)
        for row in rows:
            if not row[1] or len(row[1]) != query_dim:
                continue
            try:
                self._validate_embedding_dimension(row[1])
            except ValueError:
                logger.warning("Skipping stored embedding with invalid dimension", extra={"entity_id": row[0]})
                continue
            valid_rows.append(row)
            valid_embeddings.append(row[1])
        if not valid_rows:
            return []

        vectors = np.array(valid_embeddings, dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1)
        norms[norms == 0] = 1.0

        scores = np.dot(vectors, query) / (query_norm * norms)

        top_indices = np.argsort(scores)[-top_k:][::-1]
        return [(valid_rows[i][0], float(scores[i])) for i in top_indices]

    def _validate_embedding_dimension(self, embedding: list[float]) -> None:
        """
        Validates an embedding before storage or similarity search.
        """
        validate_embedding_vector(embedding)
