from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.services.hybrid_matcher import SCORING_VERSION


def current_ai_provider_metadata() -> dict[str, Any]:
    """
    Captures provider/model settings needed to interpret generated AI outputs later.
    """
    return {
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "multilingual_embedding_model": settings.multilingual_embedding_model,
        "embedding_dimension": settings.embedding_dimension,
        "llm_provider": settings.llm_provider,
        "ollama_model": settings.ollama_model,
        "ollama_interview_model": settings.ollama_interview_model,
        "ollama_parsing_model": settings.ollama_parsing_model,
        "ollama_embedding_model": settings.ollama_embedding_model,
        "openai_model": settings.openai_model,
    }


def scoring_version_from_reasoning(reasoning: dict[str, Any] | None) -> str:
    """
    Reads scoring version from persisted reasoning while keeping old records interpretable.
    """
    if isinstance(reasoning, dict):
        trace = reasoning.get("score_trace")
        if isinstance(trace, dict) and trace.get("scoring_version"):
            return str(trace["scoring_version"])
        if reasoning.get("scoring_version"):
            return str(reasoning["scoring_version"])
    return SCORING_VERSION
