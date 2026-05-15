import uuid

import pytest

from app.core.config import settings
from app.core.db import SessionLocal, init_db
from app.services.embedding import HashEmbeddingService
from app.services.vector_store import VectorStore


@pytest.mark.asyncio
async def test_vector_store_upsert_and_query() -> None:
    await init_db()
    embedder = HashEmbeddingService()
    entity_type = f"candidate-test-{uuid.uuid4().hex}"

    async with SessionLocal() as session:
        store = VectorStore(session)
        embeddings = await embedder.embed(["python backend developer", "data scientist"])

        await store.upsert_embedding(entity_type, "cand-1", embeddings[0])
        await store.upsert_embedding(entity_type, "cand-2", embeddings[1])

        query_result = await embedder.embed(["backend python engineer"])
        query = query_result[0]
        results = await store.query_similar(entity_type, query, top_k=2)

    assert results
    assert results[0][0] in {"cand-1", "cand-2"}


def test_vector_store_rejects_wrong_postgres_dimension() -> None:
    store = VectorStore.__new__(VectorStore)
    store.is_postgres = True

    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        store._validate_embedding_dimension([0.0] * (settings.embedding_dimension + 1))
