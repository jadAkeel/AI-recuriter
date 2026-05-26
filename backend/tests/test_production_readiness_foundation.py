import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SessionLocal, init_db
from app.main import create_app
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.match_result import MatchResult
from app.models.report import Report
from app.models.report_version import ReportVersion
from app.models.skill_evidence import SkillEvidence
from app.models.user import User
from app.services.auth import hash_password
from app.services.explainability import generate_candidate_report
from app.services.production_backfill import run_production_backfill


@pytest.mark.asyncio
async def test_backfill_creates_skill_evidence_and_marks_stale_outputs() -> None:
    await init_db()
    candidate_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    async with SessionLocal() as session:
        session.add_all([
            Candidate(
                id=candidate_id,
                full_name="Backfill Candidate",
                email=f"backfill-{candidate_id}@example.com",
                phone=None,
                skills=["RESTful APIs", "Python"],
                skills_detailed=[{"name": "Python", "context": "Built Python APIs", "confidence": 0.9}],
                experience=["Built Python APIs"],
                experience_entries=[],
                education=[],
                education_entries=[],
                projects=["RESTful API project"],
                negative_skills=None,
                learning_skills=None,
                uncatalogued_skills=None,
                total_years_experience=2.0,
                raw_text="Built Python RESTful APIs for production systems.",
            ),
            Job(
                id=job_id,
                title="Backend Engineer",
                description="Need Python and REST APIs.",
                required_skills=["python"],
                optional_skills=["rest api"],
                seniority="mid",
            ),
            MatchResult(
                job_id=job_id,
                candidate_id=candidate_id,
                score=0.5,
                reasoning={"scoring_model": "legacy"},
                scoring_version="old",
            ),
            Report(
                id=str(uuid.uuid4()),
                job_id=job_id,
                candidate_id=candidate_id,
                overall_score=0.5,
                score_breakdown={},
                skill_gap={},
                strengths=[],
                weaknesses=[],
                recommendation="old",
                scoring_version="old",
            ),
        ])
        await session.commit()

        summary = await run_production_backfill(session)

        assert summary.candidates_seen >= 1
        assert summary.skill_evidence_rows >= 2
        evidence = list((await session.execute(
            select(SkillEvidence).where(SkillEvidence.candidate_id == candidate_id)
        )).scalars().all())
        assert {row.normalized_skill for row in evidence} >= {"python", "rest api"}

        match = (await session.execute(select(MatchResult).where(MatchResult.job_id == job_id))).scalar_one()
        report = (await session.execute(select(Report).where(Report.job_id == job_id))).scalar_one()
        assert match.is_stale is True
        assert report.is_stale is True


@pytest.mark.asyncio
async def test_report_generation_creates_version_and_audit_log() -> None:
    await init_db()
    candidate_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    async with SessionLocal() as session:
        session.add_all([
            User(
                id=user_id,
                email=f"report-{user_id}@example.com",
                password_hash=hash_password("p"),
                full_name="Reporter",
                role="owner",
            ),
            Candidate(
                id=candidate_id,
                full_name="Report Candidate",
                email=f"candidate-{candidate_id}@example.com",
                phone=None,
                skills=["python", "fastapi"],
                skills_detailed=[],
                experience=["Built Python FastAPI services"],
                experience_entries=[],
                education=[],
                education_entries=[],
                projects=[],
                negative_skills=None,
                learning_skills=None,
                uncatalogued_skills=None,
                total_years_experience=3.0,
                raw_text="Python FastAPI backend engineer.",
            ),
            Job(
                id=job_id,
                title="Backend Engineer",
                description="Need Python and FastAPI.",
                required_skills=["python"],
                optional_skills=["fastapi"],
                seniority="mid",
            ),
        ])
        await session.commit()

        await generate_candidate_report(session, job_id, candidate_id, actor_user_id=user_id)

        report = (await session.execute(select(Report).where(Report.job_id == job_id))).scalar_one()
        versions = list((await session.execute(
            select(ReportVersion).where(ReportVersion.report_id == report.id)
        )).scalars().all())
        audits = list((await session.execute(
            select(AuditLog).where(AuditLog.entity_type == "report", AuditLog.entity_id == report.id)
        )).scalars().all())

        assert report.scoring_version
        assert report.provider_metadata
        assert report.report_version == 1
        assert len(versions) == 1
        assert versions[0].created_by_user_id == user_id
        assert audits and audits[0].action == "report.generated"


def test_api_e2e_upload_match_report_persists_evidence_and_report_version() -> None:
    email = f"owner-{uuid.uuid4()}@example.com"
    password = "password123"

    async def _setup_owner() -> None:
        await init_db()
        async with SessionLocal() as session:
            session.add(User(
                id=str(uuid.uuid4()),
                email=email,
                password_hash=hash_password(password),
                full_name="Owner",
                role="owner",
            ))
            await session.commit()

    import asyncio
    asyncio.run(_setup_owner())

    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        cv_text = (
            "John E2E\nEmail: john.e2e@example.com\nSkills\nPython, FastAPI, PostgreSQL\n"
            "Experience\nBuilt Python FastAPI APIs with PostgreSQL.\n"
            "Projects\nInventory API using Python and PostgreSQL.\nEducation\nBS Computer Science"
        )
        candidate_response = client.post(
            "/api/v1/candidates?use_llm=false",
            files={"file": ("cv.txt", cv_text.encode("utf-8"), "text/plain")},
            headers=headers,
        )
        assert candidate_response.status_code == 200, candidate_response.text
        candidate_id = candidate_response.json()["candidate_id"]

        job_response = client.post(
            "/api/v1/jobs",
            json={"description": "Backend Engineer\nRequirements\nPython, FastAPI, PostgreSQL"},
            headers=headers,
        )
        assert job_response.status_code == 200, job_response.text
        job_id = job_response.json()["job_id"]

        match_response = client.post(f"/api/v1/jobs/{job_id}/match?top_k=5", headers=headers)
        assert match_response.status_code == 200, match_response.text
        assert any(item["candidate_id"] == candidate_id for item in match_response.json()["results"])

        report_response = client.post(
            "/api/v1/reports/candidate",
            json={"job_id": job_id, "candidate_id": candidate_id},
            headers=headers,
        )
        assert report_response.status_code == 200, report_response.text

    async def _assert_persisted() -> None:
        async with SessionLocal() as session:
            evidence = list((await session.execute(
                select(SkillEvidence).where(SkillEvidence.candidate_id == candidate_id)
            )).scalars().all())
            report = (await session.execute(
                select(Report).where(Report.job_id == job_id, Report.candidate_id == candidate_id)
            )).scalar_one()
            versions = list((await session.execute(
                select(ReportVersion).where(ReportVersion.report_id == report.id)
            )).scalars().all())
            match = (await session.execute(
                select(MatchResult).where(MatchResult.job_id == job_id, MatchResult.candidate_id == candidate_id)
            )).scalar_one()
            assert evidence
            assert versions
            assert match.scoring_version
            assert match.provider_metadata

    asyncio.run(_assert_persisted())
