from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MatchResult(Base):
    __tablename__ = "match_results"
    __table_args__ = (UniqueConstraint("job_id", "candidate_id", name="uq_match_results_job_candidate"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    score: Mapped[float] = mapped_column(Float)
    reasoning: Mapped[dict] = mapped_column(JSON)
    scoring_version: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    provider_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
