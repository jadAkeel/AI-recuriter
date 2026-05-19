from __future__ import annotations

from pydantic import BaseModel, Field


class ScoreBreakdown(BaseModel):
    similarity_score: float
    required_skills_score: float
    optional_skills_score: float
    overall_score: float
    scoring_model: str | None = None
    scoring_formula: str | None = None
    score_weights: dict[str, float] = Field(default_factory=dict)
    score_contributions: dict[str, float] = Field(default_factory=dict)
    score_penalties: dict[str, float] = Field(default_factory=dict)
    pre_cap_score: float | None = None
    score_cap: float | None = None
    score_cap_reason: str | None = None
    score_trace: dict = Field(default_factory=dict)


class SkillGapItem(BaseModel):
    skill: str
    required: bool
    matched: bool


class SkillGapAnalysis(BaseModel):
    matched_required: list[str]
    missing_required: list[str]
    matched_optional: list[str]
    items: list[SkillGapItem]


class CandidateReportRequest(BaseModel):
    job_id: str
    candidate_id: str


class CandidateReportResponse(BaseModel):
    job_title: str | None = None
    candidate_name: str | None = None
    score_breakdown: ScoreBreakdown
    skill_gap: SkillGapAnalysis
    strengths: list[str]
    weaknesses: list[str]
    recommendation: str


class ComparisonRequest(BaseModel):
    job_id: str
    candidate_ids: list[str]


class ComparisonItem(BaseModel):
    candidate_id: str
    candidate_name: str | None = None
    overall_score: float
    similarity_score: float
    skill_score: float
    matched_skills: int
    missing_skills: int


class ComparisonResponse(BaseModel):
    job_id: str
    job_title: str | None = None
    candidates: list[ComparisonItem]
