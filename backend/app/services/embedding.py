from __future__ import annotations

import functools
import hashlib
import logging
import math
from collections import OrderedDict
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
            if not is_embedding_quality_text(text):
                embeddings.append(zero_embedding())
                continue
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
        last_error: Exception | None = None
        timeout = httpx.Timeout(settings.ai_request_timeout_seconds)
        async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout) as client:
            for attempt in range(settings.ai_max_retries + 1):
                try:
                    response = await client.post("/api/embed", json=payload)
                    response.raise_for_status()
                    embeddings = response.json()["embeddings"]
                    return _validate_embedding_batch(embeddings, expected_count=len(texts))
                except Exception as exc:
                    last_error = exc
                    if attempt >= settings.ai_max_retries:
                        break
                    await _retry_backoff(attempt)
        raise RuntimeError("Ollama embedding request failed") from last_error


class FallbackEmbeddingService:
    """Falls back to deterministic hash embeddings when the primary provider fails."""

    def __init__(self, primary: EmbeddingProvider, fallback: EmbeddingProvider | None = None) -> None:
        self._primary = primary
        self._fallback = fallback or HashEmbeddingService()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            return _validate_embedding_batch(
                await self._primary.embed(texts),
                expected_count=len(texts),
            )
        except Exception as exc:
            logger.warning(
                "Embedding provider failed; using deterministic fallback",
                extra={"error_type": type(exc).__name__},
            )
            return _validate_embedding_batch(
                await self._fallback.embed(texts),
                expected_count=len(texts),
            )


class CachedEmbeddingService:
    """Caches embedding results in-memory to avoid recomputation."""

    def __init__(self, inner: EmbeddingProvider, max_size: int = 2048) -> None:
        self._inner = inner
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._max_size = max(1, max_size)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float] | None] = [None] * len(texts)

        # Check cache for each text and de-duplicate misses within the same batch.
        uncached_by_key: OrderedDict[str, str] = OrderedDict()
        positions_by_key: dict[str, list[int]] = {}
        for i, text in enumerate(texts):
            key = self._make_key(text)
            if key in self._cache:
                cached = self._cache.pop(key)
                self._cache[key] = cached
                results[i] = cached
            elif not is_embedding_quality_text(text):
                vector = zero_embedding()
                self._cache[key] = vector
                while len(self._cache) > self._max_size:
                    self._cache.popitem(last=False)
                results[i] = vector
            else:
                positions_by_key.setdefault(key, []).append(i)
                uncached_by_key.setdefault(key, text)

        if uncached_by_key:
            uncached_keys = list(uncached_by_key.keys())
            uncached_texts = list(uncached_by_key.values())
            embeddings = _validate_embedding_batch(
                await self._inner.embed(uncached_texts),
                expected_count=len(uncached_texts),
            )
            for key, emb in zip(uncached_keys, embeddings):
                self._cache[key] = emb
                while len(self._cache) > self._max_size:
                    self._cache.popitem(last=False)
                for idx in positions_by_key[key]:
                    results[idx] = emb

        if any(r is None for r in results):
            raise RuntimeError("Embedding cache failed to populate all requested vectors")
        return [r for r in results if r is not None]

    def _make_key(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def clear(self) -> None:
        self._cache.clear()


def _validate_embedding_batch(embeddings: list[list[float]], expected_count: int) -> list[list[float]]:
    if len(embeddings) != expected_count:
        raise ValueError("Embedding provider returned an unexpected number of vectors")
    for embedding in embeddings:
        validate_embedding_vector(embedding)
    return embeddings


def validate_embedding_vector(embedding: list[float], expected_dimension: int | None = None) -> None:
    expected = expected_dimension or settings.embedding_dimension
    if len(embedding) != expected:
        raise ValueError(
            "Embedding dimension mismatch: "
            f"got {len(embedding)}, expected {expected}. "
            "Set EMBEDDING_DIMENSION to match the configured embedding model."
        )
    for value in embedding:
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError("Embedding provider returned a non-finite numeric value")


def is_embedding_quality_text(text: str | None) -> bool:
    if not text:
        return False
    alnum_count = sum(1 for char in text if char.isalnum())
    return alnum_count >= 3


def zero_embedding(dimension: int | None = None) -> list[float]:
    return [0.0] * (dimension or settings.embedding_dimension)


async def _retry_backoff(attempt: int) -> None:
    import asyncio

    delay = min(2.0, 0.25 * (2 ** attempt))
    await asyncio.sleep(delay)


@functools.lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingProvider:
    provider = settings.embedding_provider.lower()
    inner: EmbeddingProvider

    if provider == "hash":
        logger.info("Using hash embedding provider")
        inner = HashEmbeddingService()
    elif provider == "ollama":
        logger.info("Using Ollama embedding provider", extra={"model": settings.ollama_embedding_model})
        inner = FallbackEmbeddingService(OllamaEmbeddingService())
    else:
        logger.info("Using local embedding provider", extra={"model": settings.embedding_model})
        inner = FallbackEmbeddingService(LocalEmbeddingService(settings.embedding_model))

    return CachedEmbeddingService(inner)
