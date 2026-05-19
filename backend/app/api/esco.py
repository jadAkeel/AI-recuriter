from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.core.deps import require_any_role
from app.core.config import settings
from app.models.user import User
from app.schemas.esco import EscoExtractionResult
from app.services.esco_extractor import get_esco_extractor

logger = logging.getLogger(__name__)

router = APIRouter()


def _ensure_esco_enabled() -> None:
    """
    Rejects ESCO API calls when ESCO extraction is disabled.
    """
    if not settings.esco_api_enabled:
        raise HTTPException(status_code=503, detail="ESCO API integration is disabled")


class EscoExtractRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "text": "Experienced Python developer with FastAPI and Docker skills",
                "top_k": 30,
                "threshold": 0.55,
            }
        }
    )
    text: str = Field(min_length=1, max_length=20000)
    top_k: int = Field(default=30, ge=1, le=100)
    threshold: float = Field(default=0.55, ge=0.0, le=1.0)


@router.get("/esco/skills/count")
async def esco_skill_count(
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
) -> dict[str, int]:
    """
    Returns the number of ESCO skills currently available.
    """
    _ensure_esco_enabled()
    extractor = await get_esco_extractor()
    count = await extractor.skill_count()
    return {"total_esco_skills": count}


@router.post("/esco/extract", response_model=EscoExtractionResult)
async def extract_skills_esco(
    request: EscoExtractRequest,
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
) -> EscoExtractionResult:
    """
    Extracts ESCO skill matches from submitted text.
    """
    _ensure_esco_enabled()
    extractor = await get_esco_extractor()
    try:
        extractor.threshold = request.threshold
        return await extractor.extract_skills(request.text, top_k=request.top_k)
    except Exception as exc:
        logger.exception("ESCO skill extraction failed")
        raise HTTPException(status_code=500, detail="ESCO skill extraction failed") from exc


@router.post("/esco/refresh")
async def refresh_esco_cache(
    _: User = Depends(require_any_role("owner", "admin")),
) -> dict[str, int]:
    """
    Fetches ESCO skills again and refreshes the local cache.
    """
    _ensure_esco_enabled()
    extractor = await get_esco_extractor()
    count = await extractor.fetch_and_cache()
    return {"cached_skills_count": count, "status": "refreshed"}
