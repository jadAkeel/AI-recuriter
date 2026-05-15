from __future__ import annotations

import functools
import hashlib
import logging
from typing import Protocol

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalEmbeddingService:
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import asyncio
        loop = asyncio.get_running_loop()
        vectors = await loop.run_in_executor(
            None, lambda: self.model.encode(texts, normalize_embeddings=True)
        )
        return [vector.tolist() for vector in vectors]


class HashEmbeddingService:
    def __init__(self, dimension: int | None = None) -> None:
        self.dimension = dimension or settings.embedding_dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._embed_sync, texts)

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            seed = int.from_bytes(digest[:8], "big", signed=False)
            rng = np.random.default_rng(seed)
            vector = rng.standard_normal(self.dimension)
            vector = vector / np.linalg.norm(vector)
            embeddings.append(vector.tolist())
        return embeddings


class OllamaEmbeddingService:
    def __init__(self, model_name: str | None = None, base_url: str | None = None) -> None:
        self.model_name = model_name or settings.ollama_embedding_model
        self.base_url = base_url or settings.ollama_base_url

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx
        payload = {
            "model": self.model_name,
            "input": texts,
        }
        async with httpx.AsyncClient(base_url=self.base_url, timeout=300.0) as client:
            response = await client.post("/api/embed", json=payload)
            response.raise_for_status()
            return response.json()["embeddings"]


class CachedEmbeddingService:
    """Caches embedding results in-memory to avoid recomputation."""

    def __init__(self, inner: EmbeddingProvider) -> None:
        self._inner = inner
        self._cache: dict[str, list[float]] = {}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float] | None] = [None] * len(texts)

        # Check cache for each text
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []
        for i, text in enumerate(texts):
            key = self._make_key(text)
            if key in self._cache:
                results[i] = self._cache[key]
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        if uncached_texts:
            embeddings = await self._inner.embed(uncached_texts)
            for idx, emb in zip(uncached_indices, embeddings):
                key = self._make_key(texts[idx])
                self._cache[key] = emb
                results[idx] = emb

        return [r for r in results if r is not None]

    def _make_key(self, text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def clear(self) -> None:
        self._cache.clear()


def get_embedding_service() -> EmbeddingProvider:
    provider = settings.embedding_provider.lower()
    inner: EmbeddingProvider

    if provider == "hash":
        logger.info("Using hash embedding provider")
        inner = HashEmbeddingService()
    elif provider == "ollama":
        logger.info("Using Ollama embedding provider", extra={"model": settings.ollama_embedding_model})
        inner = OllamaEmbeddingService()
    else:
        logger.info("Using local embedding provider", extra={"model": settings.embedding_model})
        inner = LocalEmbeddingService(settings.embedding_model)

    return CachedEmbeddingService(inner)
