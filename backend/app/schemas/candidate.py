from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _clean_optional_text(value: str | None, max_length: int = 500) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned[:max_length] or None


def _normalize_string_list(values: list[str], *, lowercase: bool = False, max_items: int = 100) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values or []:
        text = " ".join(str(item).strip().split())
        if lowercase:
            text = text.lower()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text[:300])
        if len(normalized) >= max_items:
            break
    return normalized


class SkillStatus(str, Enum):
    HAS_EXPERIENCE = "has_experience"
    LEARNING = "learning"
    NO_EXPERIENCE = "no_experience"
    UNKNOWN = "unknown"


class SkillLevel(str, Enum):
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    EXPERT = "expert"
    UNKNOWN = "unknown"


class SkillDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    level: SkillLevel = SkillLevel.UNKNOWN
    years: float | None = None
    status: SkillStatus = SkillStatus.UNKNOWN
    confidence: float = 0.0
    context: str | None = None
    esco_uri: str | None = None
    preferred_label: str | None = None
    category: str | None = None

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        cleaned = " ".join(str(value).strip().lower().split())
        if not cleaned:
            raise ValueError("skill name cannot be empty")
        return cleaned[:120]

    @field_validator("years", mode="before")
    @classmethod
    def _normalize_years(cls, value: float | None) -> float | None:
        if value is None:
            return None
        try:
            return max(0.0, min(60.0, float(value)))
        except (TypeError, ValueError):
            return None

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    @field_validator("context", "esco_uri", "preferred_label", "category")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)


class ExperienceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    company: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None
    skills_used: list[str] = Field(default_factory=list)

    @field_validator("title", "company", "start_date", "end_date", "description")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)

    @field_validator("skills_used")
    @classmethod
    def _normalize_skills_used(cls, values: list[str]) -> list[str]:
        return _normalize_string_list(values, lowercase=True, max_items=50)


class EducationEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    degree: str | None = None
    institution: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    gpa: str | None = None
    description: str | None = None

    @field_validator("degree", "institution", "start_date", "end_date", "gpa", "description")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)


class CandidateProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    
    skills: list[str] = Field(default_factory=list)
    skills_detailed: list[SkillDetail] = Field(default_factory=list)
    
    experience: list[str] = Field(default_factory=list)
    experience_entries: list[ExperienceEntry] = Field(default_factory=list)
    total_years_experience: float | None = None
    
    education: list[str] = Field(default_factory=list)
    education_entries: list[EducationEntry] = Field(default_factory=list)
    highest_degree: str | None = None
    
    projects: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    
    negative_skills: list[str] = Field(default_factory=list)
    learning_skills: list[str] = Field(default_factory=list)
    
    summary: str | None = None
    raw_text: str
    
    parser_version: str = "enhanced"

    @field_validator("full_name", "email", "phone", "location", "highest_degree", "summary")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)

    @field_validator("skills", "negative_skills", "learning_skills")
    @classmethod
    def _normalize_skill_lists(cls, values: list[str]) -> list[str]:
        return _normalize_string_list(values, lowercase=True, max_items=120)

    @field_validator("experience", "education", "projects")
    @classmethod
    def _normalize_text_lists(cls, values: list[str]) -> list[str]:
        return _normalize_string_list(values, lowercase=False, max_items=100)

    @field_validator("languages")
    @classmethod
    def _normalize_languages(cls, values: list[str]) -> list[str]:
        return _normalize_string_list(values, lowercase=True, max_items=20)

    @field_validator("total_years_experience", mode="before")
    @classmethod
    def _normalize_total_years(cls, value: float | None) -> float | None:
        if value is None:
            return None
        try:
            return max(0.0, min(60.0, float(value)))
        except (TypeError, ValueError):
            return None

    @field_validator("raw_text")
    @classmethod
    def _normalize_raw_text(cls, value: str) -> str:
        return str(value or "").strip()


class CandidateRecord(CandidateProfile):
    candidate_id: str
    cv_url: str | None = None
    total_years_experience: float | None = None
