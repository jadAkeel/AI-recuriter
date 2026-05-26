from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.db import init_db
from app.core.logging import configure_logging, shutdown_logging
from app.core.redis import close_redis, get_redis
from app.main import _cv_worker

logger = logging.getLogger(__name__)


async def run() -> None:
    """
    Runs the CV queue worker as a separate production process.
    """
    configure_logging()
    try:
        settings.validate_runtime()
        await init_db()
        if settings.is_production and await get_redis() is None:
            raise RuntimeError("Redis is required for production CV worker")
        logger.info("Starting standalone CV worker")
        await _cv_worker()
    finally:
        await close_redis()
        shutdown_logging()


if __name__ == "__main__":
    asyncio.run(run())
