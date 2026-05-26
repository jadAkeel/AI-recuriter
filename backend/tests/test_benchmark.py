import json
from pathlib import Path
import uuid

import pytest

from app.models.candidate import Candidate
from app.models.job import Job
from app.services.enhanced_cv_parser import EnhancedCVParser
from app.services.hybrid_matcher import HybridMatchingEngine

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def test_benchmark_cv_skill_extraction() -> None:
    parser = EnhancedCVParser(use_llm=False, use_esco=False)
    expected = json.loads((FIXTURE_DIR / "expected_skills.json").read_text(encoding="utf-8"))

    for filename, expected_skills in expected.items():
        profile = parser.parse((FIXTURE_DIR / filename).read_text(encoding="utf-8"))
        overlap = set(expected_skills) & set(profile.skills)
        assert len(overlap) / len(expected_skills) >= 0.9


@pytest.mark.asyncio
async def test_benchmark_match_scores() -> None:
    thresholds = json.loads((FIXTURE_DIR / "expected_match_scores.json").read_text(encoding="utf-8"))
    parser = EnhancedCVParser(use_llm=False, use_esco=False)
    engineer = parser.parse((FIXTURE_DIR / "cv_engineer.txt").read_text(encoding="utf-8"))
    marketing = parser.parse((FIXTURE_DIR / "cv_marketing.txt").read_text(encoding="utf-8"))
    job = Job(id=str(uuid.uuid4()), title="Backend Engineer", description=(FIXTURE_DIR / "job_engineer.txt").read_text(encoding="utf-8"), required_skills=["python", "fastapi", "postgresql"], optional_skills=["docker", "redis"], seniority="mid")

    engineer_candidate = Candidate(id="engineer", full_name=engineer.full_name, email=engineer.email, phone=None, skills=engineer.skills, skills_detailed=[skill.model_dump() for skill in engineer.skills_detailed], experience=engineer.experience, education=engineer.education, projects=engineer.projects, total_years_experience=engineer.total_years_experience, raw_text=engineer.raw_text)
    marketing_candidate = Candidate(id="marketing", full_name=marketing.full_name, email=marketing.email, phone=None, skills=marketing.skills, skills_detailed=[skill.model_dump() for skill in marketing.skills_detailed], experience=marketing.experience, education=marketing.education, projects=marketing.projects, total_years_experience=marketing.total_years_experience, raw_text=marketing.raw_text)

    engine = HybridMatchingEngine()
    engineer_result = await engine._compute_match(job, engineer_candidate, semantic_score=0.0)
    marketing_result = await engine._compute_match(job, marketing_candidate, semantic_score=0.0)

    assert engineer_result.final_score >= thresholds["engineer_min"]
    assert marketing_result.final_score <= thresholds["marketing_max"]
