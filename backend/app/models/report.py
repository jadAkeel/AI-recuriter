from __future__ import annotations

from sqlalchemy import JSON, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    overall_score: Mapped[float] = mapped_column(Float)
    score_breakdown: Mapped[dict] = mapped_column(JSON)
    skill_gap: Mapped[dict] = mapped_column(JSON)
    strengths: Mapped[list[str]] = mapped_column(JSON)
    weaknesses: Mapped[list[str]] = mapped_column(JSON)
    recommendation: Mapped[str] = mapped_column(Text)
