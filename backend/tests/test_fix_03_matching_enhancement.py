import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app.core.db import SessionLocal, init_db
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.knowledge import KnowledgeDocument
from app.services.hybrid_matcher import HybridMatchingEngine
from app.services.rag import get_skill_definitions


@pytest.mark.asyncio
async def test_rag_skill_definitions_and_matching_integration() -> None:
    await init_db()
    async with SessionLocal() as session:
        document = KnowledgeDocument(
            id=str(uuid.uuid4()),
            title="GraphQL Skill Definition",
            content="GraphQL APIs use schema queries and resolvers for client-driven data access.",
            category="skill",
            tags=["graphql"],
        )
        job = Job(id=str(uuid.uuid4()), title="API Engineer", description="Needs GraphQL.", required_skills=["graphql"], optional_skills=[], seniority="mid")
        candidate = Candidate(
            id=str(uuid.uuid4()),
            full_name="Schema Candidate",
            email="schema@example.com",
            phone=None,
            skills=[],
            experience=["Built schema queries and resolvers for data services."],
            education=[],
            projects=[],
            raw_text="Built schema queries and resolvers for data services.",
        )
        session.add_all([document, job, candidate])
        await session.commit()

        definitions = await get_skill_definitions(["graphql"], session=session)
        result = await HybridMatchingEngine()._compute_match(job, candidate, semantic_score=0.0, rag_session=session)

    assert "graphql" in definitions
    assert result is not None
    assert result.skill_match.rag_matched_count == 1
    assert result.skill_match.matched_required[0].match_type == "rag"
    assert result.reasoning.rag_enriched_skills == ["graphql"]


def test_cross_encoder_evaluation_script_outputs_report() -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_cross_encoder_impact.py"
    completed = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=True)
    report = json.loads(completed.stdout)

    assert report["sample_size"] == 3
    assert "decision" in report
