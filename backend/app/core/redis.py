from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis = None


async def get_redis():
    global _redis
    if _redis is None:
        try:
            import redis.asyncio as aioredis
            _redis = aioredis.from_url(str(settings.redis_url), decode_responses=True)
            await _redis.ping()
            logger.info("Connected to Redis")
        except Exception:
            logger.warning("Redis not available, caching disabled")
            _redis = None
    return _redis


async def cache_get(key: str) -> Any | None:
    r = await get_redis()
    if r is None:
        return None
    try:
        data = await r.get(key)
        return json.loads(data) if data else None
    except Exception:
        return None


async def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    r = await get_redis()
    if r is None:
        return
    try:
        await r.setex(key, ttl, json.dumps(value))
    except Exception:
        pass


async def cache_delete(key: str) -> None:
    r = await get_redis()
    if r is None:
        return
    try:
        await r.delete(key)
    except Exception:
        pass


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.close()
        _redis = None
