from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_skill_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values or []:
        skill = " ".join(str(item).strip().lower().split())
        if not skill or skill in seen:
            continue
        seen.add(skill)
        normalized.append(skill[:120])
    return normalized


class JobProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str = Field(min_length=1, max_length=20000)
    required_skills: list[str] = Field(default_factory=list)
    optional_skills: list[str] = Field(default_factory=list)
    seniority: str | None = None

    @field_validator("title")
    @classmethod
    def _normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.strip().split())
        return cleaned[:120] or None

    @field_validator("description", mode="before")
    @classmethod
    def _normalize_description_value(cls, value: str) -> str:
        return value.strip()

    @field_validator("required_skills", "optional_skills")
    @classmethod
    def _normalize_skills(cls, values: list[str]) -> list[str]:
        return _normalize_skill_list(values)

    @field_validator("seniority")
    @classmethod
    def _normalize_seniority(cls, value: str | None) -> str | None:
        if value is None:
            return None
        seniority = value.strip().lower()
        return seniority if seniority in {"junior", "mid", "senior", "lead", "principal", "staff"} else None


class JobParseRequest(BaseModel):
    description: str = Field(min_length=1, max_length=20000)

    @field_validator("description")
    @classmethod
    def _normalize_description(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("description cannot be empty")
        return normalized


class JobUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    required_skills: list[str] | None = None
    optional_skills: list[str] | None = None
    seniority: str | None = None

    @field_validator("required_skills", "optional_skills")
    @classmethod
    def _normalize_optional_skills(cls, values: list[str] | None) -> list[str] | None:
        return _normalize_skill_list(values or []) if values is not None else None

    @field_validator("seniority")
    @classmethod
    def _normalize_update_seniority(cls, value: str | None) -> str | None:
        if value is None:
            return None
        seniority = value.strip().lower()
        return seniority if seniority in {"junior", "mid", "senior", "lead", "principal", "staff"} else None


class JobRecord(JobProfile):
    job_id: str
