from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class QuestionItem(BaseModel):
    id: str
    skill: str
    question: str
    difficulty: str = "medium"
    category: str = "Technical"
    expected_answer_hint: str | None = None
    evaluation_criteria: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("difficulty")
    @classmethod
    def _normalize_difficulty(cls, value: str) -> str:
        difficulty = str(value or "mid").strip().lower()
        return difficulty if difficulty in {"junior", "mid", "senior", "medium"} else "mid"


class StartInterviewRequest(BaseModel):
    job_id: str
    candidate_id: str


class StartInterviewResponse(BaseModel):
    session_id: str
    candidate_name: str | None = None
    job_title: str | None = None
    questions: list[QuestionItem]
    status: str
    created_at: str


class AnswerRequest(BaseModel):
    session_id: str
    question_id: str
    answer: str


class AnswerResponse(BaseModel):
    question_id: str
    skill: str
    answer: str
    score: float
    feedback: str

    @field_validator("score", mode="before")
    @classmethod
    def _clamp_score(cls, value: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0


class InterviewSessionStatus(BaseModel):
    session_id: str
    job_id: str
    candidate_id: str
    status: str
    answers_count: int
    questions: list[QuestionItem]
    answers: list[AnswerResponse] = Field(default_factory=list)
    average_score: float | None = None


class EvaluateRequest(BaseModel):
    session_id: str


class EvaluateResponse(BaseModel):
    session_id: str
    overall_score: float
    skill_scores: dict[str, float]
    feedback: str
    strengths: list[str]
    weaknesses: list[str]


class InterviewRubricItem(BaseModel):
    criterion: str
    weight: float = 1.0
    description: str = ""


class InterviewRubric(BaseModel):
    items: list[InterviewRubricItem] = Field(default_factory=list)


class InterviewScoreBreakdown(BaseModel):
    technical: float = 0.0
    problem_solving: float = 0.0
    behavioral: float = 0.0
    communication: float = 0.0
    overall: float = 0.0

    @field_validator("technical", "problem_solving", "behavioral", "communication", "overall", mode="before")
    @classmethod
    def _clamp_scores(cls, value: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0
