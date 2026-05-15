from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from app.services.voice_service import get_voice_service, _voice_sessions

logger = logging.getLogger(__name__)

router = APIRouter()


class VoiceStartResponse(BaseModel):
    session_id: str
    status: str


class VoiceProcessRequest(BaseModel):
    audio: str
    session_id: str | None = None
    question_id: str | None = None
    question_text: str | None = None
    skill: str | None = None
    difficulty: str = "mid"


class VoiceProcessResponse(BaseModel):
    transcript: str
    score: float
    feedback: str
    strengths: list[str] = []
    weaknesses: list[str] = []
    language_detected: str = "english"
    audio: str | None = None


class VoiceStatusResponse(BaseModel):
    session_id: str
    status: str
    answers_count: int = 0
    started_at: float | None = None


@router.post("/voice/start/{session_id}", response_model=VoiceStartResponse)
async def voice_start(session_id: str) -> VoiceStartResponse:
    try:
        svc = get_voice_service()
        result = await svc.start_session(session_id)
        return VoiceStartResponse(**result)
    except Exception as e:
        logger.error(f"Voice start failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/voice/process", response_model=VoiceProcessResponse)
async def voice_process(request: VoiceProcessRequest) -> VoiceProcessResponse:
    try:
        svc = get_voice_service()
        audio_bytes = base64.b64decode(request.audio)

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
    except Exception as e:
        logger.error(f"Voice process failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/voice/process/upload")
async def voice_process_upload(
    file: UploadFile = File(...),
    session_id: str = Form(""),
    question_id: str = Form(""),
    question_text: str = Form(""),
    skill: str = Form("general"),
    difficulty: str = Form("mid"),
) -> VoiceProcessResponse:
    try:
        svc = get_voice_service()
        audio_bytes = await file.read()

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
    except Exception as e:
        logger.error(f"Voice process upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/voice/status/{session_id}", response_model=VoiceStatusResponse)
async def voice_status(session_id: str) -> VoiceStatusResponse:
    try:
        svc = get_voice_service()
        result = await svc.get_session_status(session_id)
        return VoiceStatusResponse(
            session_id=result["session_id"],
            status=result["status"],
            answers_count=result.get("answers_count", 0),
            started_at=result.get("started_at"),
        )
    except Exception as e:
        logger.error(f"Voice status failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
