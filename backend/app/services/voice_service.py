from __future__ import annotations

import io
import asyncio
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.enhanced_interview import get_simple_interview_service

logger = logging.getLogger(__name__)

# In-memory store for voice session state
_voice_sessions: dict[str, dict[str, Any]] = {}

TEMP_AUDIO_TTL = 3600
_WHISPER_MODEL: Any | None = None


def _cleanup_temp_files() -> None:
    """
    Removes expired temporary audio files.
    """
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
        """
        Initializes voice storage and the simple interview evaluator.
        """
        self.temp_dir = Path(settings.voice_temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._interview_service = get_simple_interview_service()

    async def start_session(self, session_id: str) -> dict[str, Any]:
        """
        Creates in-memory state for a voice interview session.
        """
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
        """
        Transcribes audio, evaluates the answer, and optionally returns spoken feedback.
        """
        transcript = await self._speech_to_text(audio_data)

        if not transcript.strip():
            return {
                "transcript": "",
                "score": 0.0,
                "feedback": "No speech detected. Please try again.",
                "audio": None,
                "language_detected": "english",
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
        """
        Transcribes raw audio bytes into text.
        """
        return await self._speech_to_text(audio_data)

    def _build_tts_feedback(self, evaluation: dict[str, Any], transcript: str) -> str:
        """
        Builds the short spoken feedback text from an evaluation.
        """
        score = evaluation["score"]
        feedback = evaluation["feedback"]

        if score >= 0.7:
            prefix = "Great! "
        elif score >= 0.4:
            prefix = "Good. "
        else:
            prefix = "Keep trying. "

        return f"{prefix}{feedback}"

    async def get_session_status(self, session_id: str) -> dict[str, Any]:
        """
        Returns in-memory status for a voice session.
        """
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
        """
        Runs speech-to-text with OpenAI first and local fallback second.
        """
        timeout = settings.voice_request_timeout_seconds
        if settings.openai_api_key:
            try:
                return await asyncio.wait_for(self._stt_openai(audio_data), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("OpenAI STT timed out, trying fallback")
            except Exception as e:
                logger.warning(f"OpenAI STT failed, trying fallback: {e}")

        try:
            return await asyncio.wait_for(self._stt_faster_whisper(audio_data), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("faster-whisper STT timed out")
        except Exception as e:
            logger.warning(f"faster-whisper failed: {e}")

        return ""

    async def _stt_openai(self, audio_data: bytes) -> str:
        """
        Transcribes audio with OpenAI speech-to-text.
        """
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.voice_request_timeout_seconds)
        tmp_path = self._save_temp_audio(audio_data, suffix=".webm")

        try:
            with open(tmp_path, "rb") as f:
                transcript = await client.audio.transcriptions.create(
                    model=settings.voice_stt_model,
                    file=f,
                    response_format="text",
                )
            return transcript or ""
        finally:
            self._remove_temp_file(tmp_path)

    async def _stt_faster_whisper(self, audio_data: bytes) -> str:
        """
        Runs faster-whisper transcription in a worker thread.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._stt_faster_whisper_sync, audio_data)

    def _stt_faster_whisper_sync(self, audio_data: bytes) -> str:
        """
        Performs synchronous faster-whisper transcription from a temp file.
        """
        global _WHISPER_MODEL
        from faster_whisper import WhisperModel

        if _WHISPER_MODEL is None:
            _WHISPER_MODEL = WhisperModel("base", device="cpu", compute_type="int8")
        tmp_path = self._save_temp_audio(audio_data, suffix=".webm")

        try:
            segments, _ = _WHISPER_MODEL.transcribe(tmp_path)
            return " ".join(seg.text for seg in segments)
        finally:
            self._remove_temp_file(tmp_path)

    async def _text_to_speech(self, text: str) -> bytes | None:
        """
        Converts text feedback into audio with provider fallback.
        """
        timeout = settings.voice_request_timeout_seconds
        if settings.openai_api_key:
            try:
                return await asyncio.wait_for(self._tts_openai(text), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("OpenAI TTS timed out, trying fallback")
            except Exception as e:
                logger.warning(f"OpenAI TTS failed, trying fallback: {e}")

        try:
            return await asyncio.wait_for(self._tts_edge(text), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Edge TTS timed out")
        except Exception as e:
            logger.warning(f"Edge TTS failed: {e}")

        return None

    async def _tts_openai(self, text: str) -> bytes:
        """
        Generates speech audio with OpenAI TTS.
        """
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.voice_request_timeout_seconds)
        response = await client.audio.speech.create(
            model=settings.voice_tts_model,
            voice=settings.voice_tts_voice,
            input=text,
        )
        return response.content

    async def _tts_edge(self, text: str) -> bytes:
        """
        Generates speech audio with Edge TTS.
        """
        import edge_tts

        voice = "en-US-JennyNeural"

        communicate = edge_tts.Communicate(text, voice)
        audio_stream = io.BytesIO()

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_stream.write(chunk["data"])

        return audio_stream.getvalue()

    def _save_temp_audio(self, data: bytes, suffix: str = ".webm") -> str:
        """
        Writes temporary audio bytes to disk.
        """
        _cleanup_temp_files()
        name = f"{uuid.uuid4().hex}{suffix}"
        path = os.path.join(str(self.temp_dir), name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def _remove_temp_file(self, path: str) -> None:
        """
        Deletes a temporary audio file if it exists.
        """
        try:
            if os.path.exists(path):
                os.unlink(path)
        except Exception:
            pass


def get_voice_service() -> VoiceService:
    """
    Creates a voice service instance.
    """
    return VoiceService()
