from pathlib import Path

from app.models.candidate import Candidate
from app.services.enhanced_cv_parser import EnhancedCVParser
from app.services.esco_service import ESCOSkillService
from app.services.hybrid_matcher import HybridMatchingEngine
from app.services.skill_catalog import extract_uncatalogued_skills
from app.models.job import Job


def test_real_esco_file_loads_and_hierarchy_matches() -> None:
    path = Path(__file__).resolve().parents[1] / "data" / "esco_skills.json"
    service = ESCOSkillService(path)

    assert service.is_real_esco_loaded() is True
    assert service.compute_skill_similarity("Python", "Programming Language") >= 0.7
    assert service.compute_skill_similarity("Database", "PostgreSQL") >= 0.75
    assert service.compute_skill_similarity("Docker", "Kubernetes") >= 0.6


def test_uncatalogued_skill_detection_keeps_additional_skills() -> None:
    detected = extract_uncatalogued_skills("Skills: Python, Starlette, Temporal.io, FastAPI", ["python", "fastapi"])

    assert "starlette" in detected
    assert "temporal.io" in detected
    assert "python" not in detected


def test_parser_surfaces_uncatalogued_skills() -> None:
    parser = EnhancedCVParser(use_llm=False, use_esco=False)
    profile = parser.parse("Candidate\nSkills\nPython, Starlette, Temporal.io\nExperience\nBuilt Python services.")

    assert "python" in profile.skills
    assert "starlette" in profile.uncatalogued_skills


async def _match_uncatalogued() -> str:
    job = Job(id="job", title="API Engineer", description="Needs Starlette", required_skills=["starlette"], optional_skills=[], seniority="mid")
    candidate = Candidate(
        id="candidate",
        full_name="API Candidate",
        email="api@example.com",
        phone=None,
        skills=[],
        uncatalogued_skills=["starlette"],
        experience=[],
        education=[],
        projects=[],
        raw_text="Built ASGI services.",
    )
    result = await HybridMatchingEngine()._compute_match(job, candidate, semantic_score=0.0)
    return result.skill_match.matched_required[0].match_type


def test_uncatalogued_skills_match_weakly() -> None:
    import asyncio

    assert asyncio.run(_match_uncatalogued()) == "uncatalogued"
