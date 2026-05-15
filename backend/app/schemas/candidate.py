from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


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
    name: str
    level: SkillLevel = SkillLevel.UNKNOWN
    years: float | None = None
    status: SkillStatus = SkillStatus.UNKNOWN
    confidence: float = 0.0
    context: str | None = None
    esco_uri: str | None = None
    preferred_label: str | None = None
    category: str | None = None


class ExperienceEntry(BaseModel):
    title: str | None = None
    company: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None
    skills_used: list[str] = Field(default_factory=list)


class EducationEntry(BaseModel):
    degree: str | None = None
    institution: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    gpa: str | None = None
    description: str | None = None


class CandidateProfile(BaseModel):
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
    
    negative_skills: list[str] = Field(default_factory=list)
    learning_skills: list[str] = Field(default_factory=list)
    
    summary: str | None = None
    raw_text: str
    
    parser_version: str = "enhanced"


class CandidateRecord(CandidateProfile):
    candidate_id: str
    cv_url: str | None = None
    total_years_experience: float | None = None
