import asyncio

from app.services import embedding


def test_local_embedding_constructor_failure_uses_hash_fallback(monkeypatch) -> None:
    """
    Checks that local embedding constructor failure uses hash fallback.
    """
    class BrokenLocalEmbeddingService:
        def __init__(self, model_name: str) -> None:
            """
            Initializes a test double used by the surrounding test.
            """
            raise ValueError("local model import failed")

    monkeypatch.setattr(embedding.settings, "embedding_provider", "sentence-transformers")
    monkeypatch.setattr(embedding, "LocalEmbeddingService", BrokenLocalEmbeddingService)
    embedding.get_embedding_service.cache_clear()

    try:
        service = embedding.get_embedding_service()
        vectors = asyncio.run(service.embed(["python backend engineer"]))
    finally:
        embedding.get_embedding_service.cache_clear()

    assert len(vectors) == 1
    assert len(vectors[0]) == embedding.settings.embedding_dimension
    assert any(value != 0 for value in vectors[0])
