from __future__ import annotations

import logging
from fastapi import APIRouter

from app.core.db import check_db_connection
from app.schemas.health import HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse)
async def readiness() -> HealthResponse:
    ok = await check_db_connection()
    status = "ok" if ok else "degraded"
    return HealthResponse(status=status)
