from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings
from app.core.db import check_db_connection
from app.core.redis import get_redis
from app.services.embedding import get_embedding_service

logger = logging.getLogger(__name__)


def _result(ok: bool, message: str, **extra: Any) -> dict[str, Any]:
    return {"status": "ok" if ok else "degraded", "message": message, **extra}


def _model_matches(required: str, available: set[str]) -> bool:
    required = required.strip()
    if not required:
        return True
    if required in available:
        return True
    if ":" not in required:
        return any(name == required or name.startswith(f"{required}:") for name in available)
    return False


def required_ollama_models() -> list[str]:
    models: set[str] = set()
    if settings.llm_provider.lower() == "ollama":
        models.update({settings.ollama_model, settings.ollama_interview_model, settings.ollama_parsing_model})
    if settings.embedding_provider.lower() == "ollama":
        models.add(settings.ollama_embedding_model)
    return sorted(model for model in models if model)


async def _check_database() -> dict[str, Any]:
    ok = await check_db_connection()
    return _result(ok, "database reachable" if ok else "database unreachable")


async def _check_redis() -> dict[str, Any]:
    r = await get_redis()
    if r is None:
        return _result(False, "redis unavailable")
    try:
        await r.ping()
    except Exception as exc:
        logger.warning("Redis readiness check failed", extra={"error_type": type(exc).__name__})
        return _result(False, "redis ping failed", error_type=type(exc).__name__)
    return _result(True, "redis reachable")


async def _check_ollama_models() -> dict[str, Any]:
    required = required_ollama_models()
    if not required:
        return _result(True, "ollama not required", required_models=[])

    try:
        timeout = httpx.Timeout(settings.ai_request_timeout_seconds)
        async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=timeout) as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.warning("Ollama readiness check failed", extra={"error_type": type(exc).__name__})
        return _result(False, "ollama unreachable", required_models=required, error_type=type(exc).__name__)

    available = {
        str(model.get("name", "")).strip()
        for model in payload.get("models", [])
        if isinstance(model, dict)
    }
    missing = [model for model in required if not _model_matches(model, available)]
    return _result(
        not missing,
        "required ollama models available" if not missing else "required ollama models missing",
        required_models=required,
        missing_models=missing,
    )


async def _check_llm_provider() -> dict[str, Any]:
    provider = settings.llm_provider.lower()
    if provider == "rule":
        ok = not settings.is_production
        return _result(ok, "rule llm is development-only" if ok else "rule llm is not allowed in production", provider=provider)
    if provider == "openai":
        ok = bool(settings.openai_api_key)
        return _result(ok, "openai key configured" if ok else "openai key missing", provider=provider)
    if provider == "ollama":
        return _result(True, "ollama model availability checked separately", provider=provider)
    return _result(False, "unsupported llm provider", provider=provider)


async def _check_embedding_provider() -> dict[str, Any]:
    provider = settings.embedding_provider.lower()
    if provider == "hash":
        ok = not settings.is_production
        return _result(ok, "hash embeddings are development-only" if ok else "hash embeddings are not allowed in production", provider=provider)
    if provider == "ollama":
        return _result(True, "ollama embedding model availability checked separately", provider=provider)

    try:
        embedder = get_embedding_service()
        await embedder.embed(["readiness check"])
    except Exception as exc:
        logger.warning("Embedding readiness check failed", extra={"error_type": type(exc).__name__})
        return _result(False, "embedding provider failed", provider=provider, error_type=type(exc).__name__)
    return _result(True, "embedding provider reachable", provider=provider)


async def collect_readiness() -> dict[str, Any]:
    checks = {
        "database": await _check_database(),
        "redis": await _check_redis(),
        "llm_provider": await _check_llm_provider(),
        "embedding_provider": await _check_embedding_provider(),
        "ollama_models": await _check_ollama_models(),
    }
    ok = all(check["status"] == "ok" for check in checks.values())
    return {"status": "ok" if ok else "degraded", "checks": checks}
