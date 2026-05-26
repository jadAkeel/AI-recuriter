import uuid

import pytest

from app.models.candidate import Candidate
from app.models.job import Job
from app.services.hybrid_matcher import HybridMatchingEngine


@pytest.mark.asyncio
async def test_core_matching_regression_still_ranks_skill_fit() -> None:
    job = Job(id=str(uuid.uuid4()), title="Backend Engineer", description="Python FastAPI PostgreSQL", required_skills=["python", "fastapi"], optional_skills=["postgresql"], seniority="mid")
    candidate = Candidate(
        id=str(uuid.uuid4()),
        full_name="Backend Candidate",
        email="backend-regression@example.com",
        phone=None,
        skills=["python", "fastapi", "postgresql"],
        experience=["Built Python FastAPI services"],
        education=[],
        projects=[],
        total_years_experience=3,
        raw_text="Python FastAPI PostgreSQL services",
    )

    result = await HybridMatchingEngine()._compute_match(job, candidate, semantic_score=0.0)

    assert result is not None
    assert result.skill_match.required_score == 1.0
    assert result.final_score >= 0.7
