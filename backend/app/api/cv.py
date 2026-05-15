from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile, Query

from app.schemas.candidate import CandidateProfile
from app.services.cv_parser import extract_text
from app.services.enhanced_cv_parser import (
    get_enhanced_cv_parser,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/cv/parse", response_model=CandidateProfile)
async def parse_cv(
    file: UploadFile = File(...),
    use_llm: bool = Query(
        default=True,
        description="Use LLM (Ollama) for enhanced skill extraction and negation detection",
    ),
) -> CandidateProfile:
    try:
        content = await file.read()
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
        raise HTTPException(status_code=500, detail=f"CV parsing failed: {str(exc)}") from exc
