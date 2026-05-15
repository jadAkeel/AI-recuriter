from __future__ import annotations

from pydantic import BaseModel, Field


class JobProfile(BaseModel):
    title: str | None = None
    description: str
    required_skills: list[str] = Field(default_factory=list)
    optional_skills: list[str] = Field(default_factory=list)
    seniority: str | None = None


class JobParseRequest(BaseModel):
    description: str


class JobUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    required_skills: list[str] | None = None
    optional_skills: list[str] | None = None
    seniority: str | None = None


class JobRecord(JobProfile):
    job_id: str
