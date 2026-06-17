from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.skill_catalog import normalize_skill_list


def _normalize_skill_list(values: list[str]) -> list[str]:
    """
    Normalizes skill lists for API schemas or job records.
    """
    return normalize_skill_list(values)[:120]


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
        """
        Normalizes an optional job title.
        """
        if value is None:
            return None
        cleaned = " ".join(value.strip().split())
        return cleaned[:120] or None

    @field_validator("description", mode="before")
    @classmethod
    def _normalize_description_value(cls, value: str) -> str:
        """
        Normalizes required job description text.
        """
        return value.strip()

    @field_validator("required_skills", "optional_skills")
    @classmethod
    def _normalize_skills(cls, values: list[str]) -> list[str]:
        """
        Normalizes job skill lists.
        """
        return _normalize_skill_list(values)

    @field_validator("seniority")
    @classmethod
    def _normalize_seniority(cls, value: str | None) -> str | None:
        """
        Normalizes job seniority labels.
        """
        if value is None:
            return None
        seniority = value.strip().lower()
        return seniority if seniority in {"junior", "mid", "senior", "lead", "principal", "staff"} else None


class JobParseRequest(BaseModel):
    description: str = Field(min_length=1, max_length=20000)

    @field_validator("description")
    @classmethod
    def _normalize_description(cls, value: str) -> str:
        """
        Normalizes update request job description text.
        """
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

    @field_validator("description", mode="before")
    @classmethod
    def _normalize_update_description(cls, value: str | None) -> str | None:
        """
        Normalizes optional job descriptions and rejects empty updates.
        """
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("description cannot be empty")
        return normalized

    @field_validator("required_skills", "optional_skills")
    @classmethod
    def _normalize_optional_skills(cls, values: list[str] | None) -> list[str] | None:
        """
        Normalizes optional skills when provided on an update request.
        """
        return _normalize_skill_list(values or []) if values is not None else None

    @field_validator("seniority")
    @classmethod
    def _normalize_update_seniority(cls, value: str | None) -> str | None:
        """
        Normalizes optional seniority on a job update request.
        """
        if value is None:
            return None
        seniority = value.strip().lower()
        return seniority if seniority in {"junior", "mid", "senior", "lead", "principal", "staff"} else None


class JobRecord(JobProfile):
    job_id: str
