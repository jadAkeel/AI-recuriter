from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.deps import require_any_role
from app.models.user import User
from app.services.voice_service import get_voice_service

logger = logging.getLogger(__name__)

router = APIRouter()


class VoiceStartResponse(BaseModel):
    session_id: str
    status: str


class VoiceProcessRequest(BaseModel):
    audio: str = Field(min_length=1)
    session_id: str | None = None
    question_id: str | None = None
    question_text: str | None = Field(default=None, max_length=5000)
    skill: str | None = None
    difficulty: str = "mid"


class VoiceProcessResponse(BaseModel):
    transcript: str
    score: float
    feedback: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    language_detected: str = "english"
    audio: str | None = None


class VoiceStatusResponse(BaseModel):
    session_id: str
    status: str
    answers_count: int = 0
    started_at: float | None = None


def _validate_audio_size(audio_bytes: bytes) -> None:
    if len(audio_bytes) > settings.max_audio_upload_bytes:
        max_mb = settings.max_audio_upload_bytes // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"Audio file is too large. Maximum size is {max_mb}MB.")


@router.post("/voice/start/{session_id}", response_model=VoiceStartResponse)
async def voice_start(
    session_id: str,
    _: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
) -> VoiceStartResponse:
    try:
        svc = get_voice_service()
        result = await svc.start_session(session_id)
        return VoiceStartResponse(**result)
    except Exception:
        logger.exception("Voice start failed")
        raise HTTPException(status_code=500, detail="Voice session could not be started")


@router.post("/voice/process", response_model=VoiceProcessResponse)
async def voice_process(
    request: VoiceProcessRequest,
    _: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
) -> VoiceProcessResponse:
    try:
        svc = get_voice_service()
        audio_bytes = base64.b64decode(request.audio, validate=True)
        _validate_audio_size(audio_bytes)

        result = await svc.process_audio(
            audio_data=audio_bytes,
            session_id=request.session_id,
            question_id=request.question_id,
            question_text=request.question_text,
            skill=request.skill,
            difficulty=request.difficulty,
        )

        audio_b64 = None
        if result.get("audio"):
            audio_b64 = base64.b64encode(result["audio"]).decode("utf-8")

        return VoiceProcessResponse(
            transcript=result["transcript"],
            score=result["score"],
            feedback=result["feedback"],
            strengths=result.get("strengths", []),
            weaknesses=result.get("weaknesses", []),
            language_detected=result.get("language_detected", "english"),
            audio=audio_b64,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 audio payload") from exc
    except Exception:
        logger.exception("Voice process failed")
        raise HTTPException(status_code=500, detail="Voice processing failed")


@router.post("/voice/process/upload")
async def voice_process_upload(
    file: UploadFile = File(...),
    session_id: str = Form(""),
    question_id: str = Form(""),
    question_text: str = Form(""),
    skill: str = Form("general"),
    difficulty: str = Form("mid"),
    _: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
) -> VoiceProcessResponse:
    try:
        svc = get_voice_service()
        audio_bytes = await file.read()
        _validate_audio_size(audio_bytes)

        result = await svc.process_audio(
            audio_data=audio_bytes,
            session_id=session_id or None,
            question_id=question_id or None,
            question_text=question_text or None,
            skill=skill,
            difficulty=difficulty,
        )

        audio_b64 = None
        if result.get("audio"):
            audio_b64 = base64.b64encode(result["audio"]).decode("utf-8")

        return VoiceProcessResponse(
            transcript=result["transcript"],
            score=result["score"],
            feedback=result["feedback"],
            strengths=result.get("strengths", []),
            weaknesses=result.get("weaknesses", []),
            language_detected=result.get("language_detected", "english"),
            audio=audio_b64,
        )
    except Exception:
        logger.exception("Voice process upload failed")
        raise HTTPException(status_code=500, detail="Voice processing failed")


@router.get("/voice/status/{session_id}", response_model=VoiceStatusResponse)
async def voice_status(
    session_id: str,
    _: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
) -> VoiceStatusResponse:
    try:
        svc = get_voice_service()
        result = await svc.get_session_status(session_id)
        return VoiceStatusResponse(
            session_id=result["session_id"],
            status=result["status"],
            answers_count=result.get("answers_count", 0),
            started_at=result.get("started_at"),
        )
    except Exception:
        logger.exception("Voice status failed")
        raise HTTPException(status_code=500, detail="Voice status lookup failed")
