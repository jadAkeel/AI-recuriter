from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Query

from app.core.config import settings
from app.core.deps import require_any_role
from app.models.user import User
from app.schemas.candidate import CandidateProfile
from app.services.cv_parser import extract_text
from app.services.enhanced_cv_parser import (
    get_enhanced_cv_parser,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _read_limited_upload(file: UploadFile) -> bytes:
    """
    Reads an upload while enforcing the configured size limit.
    """
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        max_mb = settings.max_upload_bytes // (1024 * 1024)
        raise ValueError(f"CV file is too large. Maximum size is {max_mb}MB.")
    return content


@router.post("/cv/parse", response_model=CandidateProfile)
async def parse_cv(
    file: UploadFile = File(...),
    use_llm: bool = Query(
        default=True,
        description="Use LLM (Ollama) for enhanced skill extraction and negation detection",
    ),
    _: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
) -> CandidateProfile:
    """
    Parses an uploaded CV and returns the extracted candidate profile.
    """
    try:
        content = await _read_limited_upload(file)
        text = extract_text(file.filename or "", content)

        if use_llm:
            parser = get_enhanced_cv_parser()
            parser.use_llm = use_llm
            result = await parser.parse_async(text)
            logger.info(
                "CV parsed with enhanced parser",
                extra={
                    "cv_filename": file.filename,
                    "use_llm": use_llm,
                    "skills_count": len(result.skills),
                    "negative_count": len(result.negative_skills),
                },
            )
            return result
        else:
            from app.services.cv_parser import parse_cv_text

            result = parse_cv_text(text)
            logger.info(
                "CV parsed with simple parser",
                extra={"cv_filename": file.filename, "skills_count": len(result.skills)},
            )
            return result

    except ValueError as exc:
        logger.warning("Unsupported CV file", extra={"cv_filename": file.filename})
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("CV parsing failed")
        raise HTTPException(status_code=500, detail="CV parsing failed") from exc
