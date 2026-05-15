from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from app.core.deps import require_any_role
from app.models.user import User
from app.schemas.esco import EscoExtractionResult
from app.services.esco_extractor import get_esco_extractor

logger = logging.getLogger(__name__)

router = APIRouter()


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
    text: str
    top_k: int = 30
    threshold: float = 0.55


@router.get("/esco/skills/count")
async def esco_skill_count(
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
) -> dict[str, int]:
    extractor = await get_esco_extractor()
    count = await extractor.skill_count()
    return {"total_esco_skills": count}


@router.post("/esco/extract", response_model=EscoExtractionResult)
async def extract_skills_esco(
    request: EscoExtractRequest,
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
) -> EscoExtractionResult:
    extractor = await get_esco_extractor()
    try:
        return await extractor.extract_skills(request.text, top_k=request.top_k)
    except Exception as exc:
        logger.exception("ESCO skill extraction failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/esco/refresh")
async def refresh_esco_cache(
    _: User = Depends(require_any_role("owner", "admin")),
) -> dict[str, int]:
    extractor = await get_esco_extractor()
    count = await extractor.fetch_and_cache()
    return {"cached_skills_count": count, "status": "refreshed"}
