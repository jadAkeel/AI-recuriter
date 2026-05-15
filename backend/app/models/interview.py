from __future__ import annotations

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    questions: Mapped[list[dict]] = mapped_column(JSON)
    answers: Mapped[list[str]] = mapped_column(JSON)
    evaluations: Mapped[list[dict]] = mapped_column(JSON)
    # Use SQLAlchemy's Python-side default; avoid dataclass-only default_factory.
    chat_history: Mapped[list[dict]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20))
