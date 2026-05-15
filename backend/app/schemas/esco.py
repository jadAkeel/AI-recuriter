from __future__ import annotations

from pydantic import BaseModel, Field


class EscoSkill(BaseModel):
    uri: str
    title: str
    description: str | None = None
    skill_type: str | None = None
    reuse_level: str | None = None
    broader_skills: list[str] = Field(default_factory=list)


class EscoSkillMatch(BaseModel):
    skill: EscoSkill
    score: float
    matched_from: str | None = None


class EscoExtractionResult(BaseModel):
    skills: list[EscoSkillMatch]
    total_esco_skills: int = 0
    provider: str = "esco_api"


class EscoCacheInfo(BaseModel):
    cached_skills_count: int
    cached_embeddings: bool
    last_updated: str | None = None
