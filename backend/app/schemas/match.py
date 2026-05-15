from __future__ import annotations

from pydantic import BaseModel


class MatchItem(BaseModel):
    candidate_id: str
    candidate_name: str | None = None
    candidate_email: str | None = None
    candidate_skills: list[str] = []
    candidate_total_years_experience: float | None = None
    score: float
    reasoning: dict


class MatchResponse(BaseModel):
    job_id: str
    results: list[MatchItem]
