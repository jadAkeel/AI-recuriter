from __future__ import annotations

import io
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.enhanced_interview import get_enhanced_interview_service

logger = logging.getLogger(__name__)

# In-memory store for voice session state
_voice_sessions: dict[str, dict[str, Any]] = {}

TEMP_AUDIO_TTL = 3600


def _cleanup_temp_files() -> None:
    temp_dir = Path(settings.voice_temp_dir)
    if not temp_dir.exists():
        return
    now = time.time()
    for f in temp_dir.iterdir():
        if f.is_file() and now - f.stat().st_mtime > TEMP_AUDIO_TTL:
            try:
                f.unlink()
            except Exception:
                pass


class VoiceService:
    def __init__(self) -> None:
        self.temp_dir = Path(settings.voice_temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._interview_service = get_enhanced_interview_service()

    async def start_session(self, session_id: str) -> dict[str, Any]:
        _voice_sessions[session_id] = {
            "status": "active",
            "current_question_idx": 0,
            "answers_count": 0,
            "started_at": time.time(),
        }
        return {"session_id": session_id, "status": "active"}

    async def process_audio(
        self,
        audio_data: bytes,
        session_id: str | None = None,
        question_id: str | None = None,
        question_text: str | None = None,
        skill: str | None = None,
        difficulty: str = "mid",
    ) -> dict[str, Any]:
        transcript = await self._speech_to_text(audio_data)

        if not transcript.strip():
            return {
                "transcript": "",
                "score": 0.0,
                "feedback": "لم يتم التعرف على أي كلام. يرجى المحاولة مرة أخرى.",
                "audio": None,
                "language_detected": "arabic",
            }

        evaluation = await self._interview_service.evaluate_answer_with_llm(
            question=question_text or "",
            answer=transcript,
            skill=skill or "general",
            difficulty=difficulty,
        )

        tts_text = self._build_tts_feedback(evaluation, transcript)
        audio_response = await self._text_to_speech(tts_text)

        return {
            "transcript": transcript,
            "score": evaluation["score"],
            "feedback": evaluation["feedback"],
            "strengths": evaluation.get("strengths", []),
            "weaknesses": evaluation.get("weaknesses", []),
            "language_detected": evaluation.get("language_detected", "english"),
            "audio": audio_response,
        }

    async def transcribe_audio(self, audio_data: bytes) -> str:
        return await self._speech_to_text(audio_data)

    def _build_tts_feedback(self, evaluation: dict[str, Any], transcript: str) -> str:
        score = evaluation["score"]
        feedback = evaluation["feedback"]
        is_arabic = evaluation.get("language_detected", "english") == "arabic"

        if score >= 0.7:
            prefix = "أحسنت! " if is_arabic else "Great! "
        elif score >= 0.4:
            prefix = "جيد. " if is_arabic else "Good. "
        else:
            prefix = "حاول مرة أخرى. " if is_arabic else "Keep trying. "

        return f"{prefix}{feedback}"

    async def get_session_status(self, session_id: str) -> dict[str, Any]:
        session = _voice_sessions.get(session_id)
        if session is None:
            return {"session_id": session_id, "status": "not_found"}
        return {
            "session_id": session_id,
            "status": session["status"],
            "answers_count": session["answers_count"],
            "started_at": session.get("started_at"),
        }

    async def _speech_to_text(self, audio_data: bytes) -> str:
        if settings.openai_api_key:
            try:
                return await self._stt_openai(audio_data)
            except Exception as e:
                logger.warning(f"OpenAI STT failed, trying fallback: {e}")

        try:
            return await self._stt_faster_whisper(audio_data)
        except Exception as e:
            logger.warning(f"faster-whisper failed: {e}")

        return ""

    async def _stt_openai(self, audio_data: bytes) -> str:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        tmp_path = self._save_temp_audio(audio_data, suffix=".webm")

        try:
            with open(tmp_path, "rb") as f:
                transcript = await client.audio.transcriptions.create(
                    model=settings.voice_stt_model,
                    file=f,
                    language="ar",
                    response_format="text",
                )
            return transcript or ""
        finally:
            self._remove_temp_file(tmp_path)

    async def _stt_faster_whisper(self, audio_data: bytes) -> str:
        from faster_whisper import WhisperModel

        model = WhisperModel("base", device="cpu", compute_type="int8")
        tmp_path = self._save_temp_audio(audio_data, suffix=".wav")

        try:
            segments, _ = model.transcribe(tmp_path, language="ar")
            return " ".join(seg.text for seg in segments)
        finally:
            self._remove_temp_file(tmp_path)

    async def _text_to_speech(self, text: str) -> bytes | None:
        if settings.openai_api_key:
            try:
                return await self._tts_openai(text)
            except Exception as e:
                logger.warning(f"OpenAI TTS failed, trying fallback: {e}")

        try:
            return await self._tts_edge(text)
        except Exception as e:
            logger.warning(f"Edge TTS failed: {e}")

        return None

    async def _tts_openai(self, text: str) -> bytes:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.audio.speech.create(
            model=settings.voice_tts_model,
            voice=settings.voice_tts_voice,
            input=text,
        )
        return response.content

    async def _tts_edge(self, text: str) -> bytes:
        import edge_tts

        has_arabic = any("\u0600" <= c <= "\u06FF" for c in text)
        voice = "ar-SA-ZariyahNeural" if has_arabic else "en-US-JennyNeural"

        communicate = edge_tts.Communicate(text, voice)
        audio_stream = io.BytesIO()

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_stream.write(chunk["data"])

        return audio_stream.getvalue()

    def _save_temp_audio(self, data: bytes, suffix: str = ".webm") -> str:
        _cleanup_temp_files()
        name = f"{uuid.uuid4().hex}{suffix}"
        path = os.path.join(str(self.temp_dir), name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def _remove_temp_file(self, path: str) -> None:
        try:
            if os.path.exists(path):
                os.unlink(path)
        except Exception:
            pass


def get_voice_service() -> VoiceService:
    return VoiceService()
