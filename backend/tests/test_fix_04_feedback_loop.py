import uuid

import pytest

from app.core.db import SessionLocal, init_db
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.skill_feedback import SkillFeedback
from app.services.continuous_learning import get_feedback_stats, process_feedback_batch
from app.services.hybrid_matcher import HybridMatchingEngine
from app.services.skill_catalog import SYNONYM_MAP, normalize_skill_name


@pytest.mark.asyncio
async def test_feedback_batch_adds_dynamic_synonym() -> None:
    await init_db()
    async with SessionLocal() as session:
        job = Job(id=str(uuid.uuid4()), title="API Engineer", description="FastAPI services", required_skills=["fastapi"], optional_skills=[], seniority="mid")
        session.add(job)
        for index in range(3):
            candidate = Candidate(
                id=str(uuid.uuid4()),
                full_name=f"Candidate {index}",
                email=f"candidate-{index}@example.com",
                phone=None,
                skills=["starlette"],
                experience=["Built Starlette services"],
                education=[],
                projects=[],
                raw_text="Built Starlette services",
            )
            session.add(candidate)
            session.add(SkillFeedback(
                job_id=job.id,
                candidate_id=candidate.id,
                skill_name="fastapi",
                was_matched=False,
                recruiter_action="added",
                correct_match=True,
            ))
        await session.commit()

        stats = await process_feedback_batch(session, batch_size=3)

    assert stats["total_feedback"] >= 3
    assert "starlette" in SYNONYM_MAP[normalize_skill_name("fastapi")]


@pytest.mark.asyncio
async def test_matching_uses_historical_feedback() -> None:
    await init_db()
    async with SessionLocal() as session:
        job = Job(id=str(uuid.uuid4()), title="Worker Engineer", description="Needs Celery.", required_skills=["celery"], optional_skills=[], seniority="mid")
        candidate = Candidate(
            id=str(uuid.uuid4()),
            full_name="Feedback Candidate",
            email="feedback@example.com",
            phone=None,
            skills=[],
            experience=["Built background workers."],
            education=[],
            projects=[],
            raw_text="Built background workers.",
        )
        feedback = SkillFeedback(
            job_id=job.id,
            candidate_id=candidate.id,
            skill_name="celery",
            was_matched=False,
            recruiter_action="added",
            correct_match=True,
        )
        session.add_all([job, candidate, feedback])
        await session.commit()

        result = await HybridMatchingEngine()._compute_match(job, candidate, semantic_score=0.0, rag_session=session)
        stats = await get_feedback_stats(session)

    assert result is not None
    assert result.skill_match.matched_required[0].match_type == "historical_feedback"
    assert stats["total_feedback"] >= 1
