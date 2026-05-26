from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("job_id", "candidate_id", name="uq_reports_job_candidate"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    overall_score: Mapped[float] = mapped_column(Float)
    score_breakdown: Mapped[dict] = mapped_column(JSON)
    skill_gap: Mapped[dict] = mapped_column(JSON)
    strengths: Mapped[list[str]] = mapped_column(JSON)
    weaknesses: Mapped[list[str]] = mapped_column(JSON)
    recommendation: Mapped[str] = mapped_column(Text)
    scoring_version: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    provider_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    report_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
