import pytest
from fastapi.testclient import TestClient

from app.api import health as health_api
from app.core.config import settings
from app.main import create_app
from app.services import embedding as embedding_module
from app.services import task_queue


def test_ready_returns_503_when_dependency_is_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_collect_readiness() -> dict:
        return {"status": "degraded", "checks": {"redis": {"status": "degraded"}}}

    monkeypatch.setattr(health_api, "collect_readiness", fake_collect_readiness)

    client = TestClient(create_app())
    response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_ready_returns_200_when_dependencies_are_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_collect_readiness() -> dict:
        return {"status": "ok", "checks": {"database": {"status": "ok"}}}

    monkeypatch.setattr(health_api, "collect_readiness", fake_collect_readiness)

    client = TestClient(create_app())
    response = client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_cv_queue_requires_redis_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unavailable_redis():
        return None

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(task_queue, "get_redis", unavailable_redis)

    with pytest.raises(RuntimeError, match="Redis is required"):
        await task_queue.enqueue_cv_processing("Python", "candidate.txt")


def test_production_ollama_embedding_constructs_without_hash_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "embedding_provider", "ollama")
    monkeypatch.setattr(settings, "ollama_embedding_model", "nomic-embed-text")
    monkeypatch.setattr(settings, "embedding_dimension", 768)

    embedding_module._get_cached_embedding_service.cache_clear()
    service = embedding_module.get_standard_embedding_service()
    embedding_module._get_cached_embedding_service.cache_clear()

    assert service is not None
