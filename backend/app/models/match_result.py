from __future__ import annotations

from sqlalchemy import JSON, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MatchResult(Base):
    __tablename__ = "match_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    score: Mapped[float] = mapped_column(Float)
    reasoning: Mapped[dict] = mapped_column(JSON)
