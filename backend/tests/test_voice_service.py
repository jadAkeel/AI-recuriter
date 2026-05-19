import asyncio

import pytest

from app.core.config import settings
from app.services.voice_service import VoiceService


@pytest.mark.asyncio
async def test_voice_stt_timeout_uses_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Checks that voice speech-to-text timeout uses fallback.
    """
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "voice_request_timeout_seconds", 0.01)

    service = VoiceService()

    async def _slow_openai_stt(audio_data: bytes) -> str:
        """
        Supports the surrounding test for test voice speech-to-text timeout uses
        fallback.
        """
        await asyncio.sleep(1)
        return "late transcript"

    async def _fallback_stt(audio_data: bytes) -> str:
        """
        Supports the surrounding test for test voice speech-to-text timeout uses
        fallback.
        """
        return "fallback transcript"

    monkeypatch.setattr(service, "_stt_openai", _slow_openai_stt)
    monkeypatch.setattr(service, "_stt_faster_whisper", _fallback_stt)

    assert await service.transcribe_audio(b"audio") == "fallback transcript"
