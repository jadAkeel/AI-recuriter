import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal, init_db
from app.main import create_app
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.match_result import MatchResult
from app.models.report import Report
from app.models.user import User
from sqlalchemy import select


def _auth_headers(client: TestClient) -> dict[str, str]:
    """
    Builds authenticated request headers for test API calls.
    """
    email = f"recruiter-{uuid.uuid4().hex[:8]}@example.com"
    register_payload = {
        "email": email,
        "password": "strongpass123",
        "full_name": "Recruiter User",
    }
    client.post("/api/v1/auth/register", json=register_payload)

    async def _promote_recruiter() -> None:
        """
        Promotes a test user so protected recruiter routes can be called.
        """
        async with SessionLocal() as session:
            result = await session.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()
            if user is not None:
                user.role = "recruiter"
                await session.commit()

    import asyncio
    asyncio.run(_promote_recruiter())

    login_payload = {"email": email, "password": "strongpass123"}
    login_resp = client.post("/api/v1/auth/login", json=login_payload)
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module", autouse=True)
def _setup():
    """
    Supports the surrounding test for setup.
    """
    import asyncio
    asyncio.run(init_db())


def _seed_data() -> tuple[str, str, str]:
    """
    Seeds database rows used by the surrounding test.
    """
    import asyncio
    async def _seed():
        """
        Seeds database rows used by the surrounding test.
        """
        async with SessionLocal() as session:
            job_id = str(uuid.uuid4())
            session.add(Job(
                id=job_id, title="Backend Engineer",
                description="Backend engineer with Python and FastAPI.",
                required_skills=["python", "fastapi", "sql"],
                optional_skills=["docker", "redis"], seniority="mid",
            ))
            cand1_id = str(uuid.uuid4())
            session.add(Candidate(
                id=cand1_id, full_name="Alice", email="alice@test.com",
                phone="+123", skills=["python", "fastapi", "docker"],
                experience=["Backend Dev"], education=["BSc"],
                projects=["API service"],
                raw_text="Alice is a backend developer with Python FastAPI Docker.",
            ))
            cand2_id = str(uuid.uuid4())
            session.add(Candidate(
                id=cand2_id, full_name="Bob", email="bob@test.com",
                phone="+456", skills=["python", "sql"],
                experience=["Junior Dev"], education=["BSc"],
                projects=["Data analysis"],
                raw_text="Bob is a junior Python developer with SQL skills.",
            ))
            await session.commit()
            return job_id, cand1_id, cand2_id
    return asyncio.run(_seed())


def test_candidate_report() -> None:
    """
    Checks that candidate report.
    """
    app = create_app()
    with TestClient(app) as client:
        job_id, cand_id, _ = _seed_data()
        headers = _auth_headers(client)

        resp = client.post("/api/v1/reports/candidate", json={
            "job_id": job_id, "candidate_id": cand_id,
        }, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["candidate_name"] == "Alice"
        assert data["job_title"] == "Backend Engineer"
        assert "score_breakdown" in data
        assert "skill_gap" in data
        assert set(data["skill_gap"]["matched_required"]) == {"python", "fastapi"}
        assert data["skill_gap"]["missing_required"] == ["sql"]
        assert data["recommendation"]


def test_candidate_report_matches_restful_api_and_mongoose_typos() -> None:
    """
    Checks that candidate report matches restful API and mongoose typos.
    """
    import asyncio

    async def _seed() -> tuple[str, str]:
        """
        Seeds database rows used by the surrounding test.
        """
        async with SessionLocal() as session:
            job_id = str(uuid.uuid4())
            cand_id = str(uuid.uuid4())
            session.add(Job(
                id=job_id,
                title="Junior Next.js Developer",
                description="Junior role with REST API and Mongoose as optional skills.",
                required_skills=["next.js"],
                optional_skills=["rest api", "mongose"],
                seniority="junior",
            ))
            session.add(Candidate(
                id=cand_id,
                full_name="Azzam-like Candidate",
                email=f"azzam-like-{uuid.uuid4().hex[:8]}@test.com",
                phone="+123",
                skills=["next.js"],
                experience=[],
                education=[],
                projects=["Built a full-stack app with RESTful APIs and Mongoose."],
                raw_text="Backend: Node.js, Express.js, RESTful API Development. Databases: MongoDB, PostgreSQL, Mongoose.",
            ))
            await session.commit()
            return job_id, cand_id

    app = create_app()
    with TestClient(app) as client:
        job_id, cand_id = asyncio.run(_seed())
        headers = _auth_headers(client)
        resp = client.post("/api/v1/reports/candidate", json={
            "job_id": job_id,
            "candidate_id": cand_id,
        }, headers=headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["score_breakdown"]["optional_skills_score"] == 1.0
    assert set(data["skill_gap"]["matched_optional"]) == {"mongose", "rest api"}
    assert data["skill_gap"]["missing_required"] == []


def test_dashboard_results_include_report_without_interview() -> None:
    """
    Checks that dashboard results include report without interview.
    """
    import asyncio

    async def _seed() -> tuple[str, str, str, str]:
        """
        Seeds database rows used by the surrounding test.
        """
        async with SessionLocal() as session:
            job_id = str(uuid.uuid4())
            candidate_id = str(uuid.uuid4())
            report_id = str(uuid.uuid4())
            session.add(Job(
                id=job_id,
                title="AI Engineer Dashboard",
                description="AI engineer with Python.",
                required_skills=["python"],
                optional_skills=[],
                seniority="mid",
            ))
            session.add(Candidate(
                id=candidate_id,
                full_name="Jad Akil Dashboard",
                email=f"jad-dashboard-{uuid.uuid4().hex[:8]}@test.com",
                phone="+961",
                skills=["python"],
                experience=["Built AI systems."],
                education=["BSc"],
                projects=["NLP project"],
                raw_text="Python AI engineer.",
            ))
            session.add(Report(
                id=report_id,
                job_id=job_id,
                candidate_id=candidate_id,
                overall_score=0.77,
                score_breakdown={},
                skill_gap={},
                strengths=[],
                weaknesses=[],
                recommendation="Strong candidate.",
            ))
            await session.commit()
            return job_id, candidate_id, report_id, "Jad Akil Dashboard"

    app = create_app()
    with TestClient(app) as client:
        job_id, candidate_id, report_id, candidate_name = asyncio.run(_seed())
        headers = _auth_headers(client)

        resp = client.get("/api/v1/interviews/dashboard-results", headers=headers)

    assert resp.status_code == 200, resp.text
    rows = [row for row in resp.json() if row.get("report_id") == report_id]
    assert len(rows) == 1
    row = rows[0]
    assert row["session_id"] is None
    assert row["candidate_id"] == candidate_id
    assert row["candidate_name"] == candidate_name
    assert row["job_id"] == job_id
    assert row["analysis_status"] == "ready"
    assert row["report_score"] == 0.77
    assert row["answered_questions"] == 0


def test_dashboard_results_refresh_saved_match_without_report_or_interview() -> None:
    """
    Checks that dashboard results refresh saved match without report or interview.
    """
    import asyncio

    async def _seed() -> tuple[str, str]:
        """
        Seeds database rows used by the surrounding test.
        """
        await init_db()
        async with SessionLocal() as session:
            job_id = str(uuid.uuid4())
            candidate_id = str(uuid.uuid4())
            session.add(Job(
                id=job_id,
                title="Saved Match Dashboard",
                description="Python backend role.",
                required_skills=["python"],
                optional_skills=[],
                seniority="mid",
            ))
            session.add(Candidate(
                id=candidate_id,
                full_name="Saved Match Candidate",
                email=f"saved-dashboard-{uuid.uuid4().hex[:8]}@test.com",
                phone="+961",
                skills=["python"],
                experience=["Built services."],
                education=["BSc"],
                projects=["API"],
                raw_text="Python backend engineer.",
            ))
            session.add(MatchResult(
                job_id=job_id,
                candidate_id=candidate_id,
                score=0.83,
                reasoning={"scoring_model": "hybrid"},
            ))
            await session.commit()
            return job_id, candidate_id

    app = create_app()
    with TestClient(app) as client:
        job_id, candidate_id = asyncio.run(_seed())
        headers = _auth_headers(client)
        resp = client.get("/api/v1/interviews/dashboard-results", headers=headers)

    assert resp.status_code == 200, resp.text
    rows = [
        row for row in resp.json()
        if row["job_id"] == job_id and row["candidate_id"] == candidate_id
    ]
    assert len(rows) == 1
    row = rows[0]
    assert row["session_id"] is None
    assert row["report_id"] is None
    assert row["analysis_status"] == "saved"
    assert row["match_score"] == 0.575
    assert row["answered_questions"] == 0


def test_dashboard_results_returns_saved_match_when_refresh_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Checks that dashboard results returns saved match when refresh fails.
    """
    import asyncio
    import app.api.interviews as interviews_api

    class BrokenMatchingEngine:
        def __init__(self) -> None:
            """
            Initializes a test double used by the surrounding test.
            """
            raise RuntimeError("embedding provider unavailable")

    async def _seed() -> tuple[str, str]:
        """
        Seeds database rows used by the surrounding test.
        """
        await init_db()
        async with SessionLocal() as session:
            job_id = str(uuid.uuid4())
            candidate_id = str(uuid.uuid4())
            session.add(Job(
                id=job_id,
                title="Dashboard Refresh Fallback",
                description="Python backend role.",
                required_skills=["python"],
                optional_skills=[],
                seniority="mid",
            ))
            session.add(Candidate(
                id=candidate_id,
                full_name="Refresh Fallback Candidate",
                email=f"refresh-fallback-{uuid.uuid4().hex[:8]}@test.com",
                phone="+961",
                skills=["python"],
                experience=["Built services."],
                education=["BSc"],
                projects=["API"],
                raw_text="Python backend engineer.",
            ))
            session.add(MatchResult(
                job_id=job_id,
                candidate_id=candidate_id,
                score=0.42,
                reasoning={"scoring_model": "legacy", "semantic_score": 0.0},
            ))
            await session.commit()
            return job_id, candidate_id

    monkeypatch.setattr(interviews_api, "HybridMatchingEngine", BrokenMatchingEngine)

    app = create_app()
    with TestClient(app) as client:
        job_id, candidate_id = asyncio.run(_seed())
        headers = _auth_headers(client)
        resp = client.get("/api/v1/interviews/dashboard-results", headers=headers)

    assert resp.status_code == 200, resp.text
    rows = [
        row for row in resp.json()
        if row["job_id"] == job_id and row["candidate_id"] == candidate_id
    ]
    assert len(rows) == 1
    assert rows[0]["analysis_status"] == "saved"
    assert rows[0]["match_score"] == 0.42


def test_candidate_report_normalizes_skill_aliases_and_cv_evidence() -> None:
    """
    Checks that candidate report normalizes skill aliases and CV evidence.
    """
    import asyncio

    async def _seed() -> tuple[str, str]:
        """
        Seeds database rows used by the surrounding test.
        """
        async with SessionLocal() as session:
            job_id = str(uuid.uuid4())
            candidate_id = str(uuid.uuid4())
            session.add(Job(
                id=job_id,
                title="AI Engineer",
                description="AI engineer with Python, deep learning, vector databases, SQL, C/C++, and big data.",
                required_skills=["python", "deep learning", "sql", "vector database"],
                optional_skills=["c/c++", "big data"],
                seniority="mid",
            ))
            session.add(Candidate(
                id=candidate_id,
                full_name="Jad Akil",
                email=f"jad-{uuid.uuid4().hex[:8]}@test.com",
                phone="+961",
                skills=["Python", "PyTorch", "SQL", "Vector DB", "C++", "Hadoop"],
                experience=["Built PyTorch deep learning models and Hadoop big data pipelines."],
                education=["BSc Computer Science"],
                projects=["RAG system using a vector database and Python APIs."],
                raw_text="Python, PyTorch, SQL, Vector DB, C/C++, Hadoop and Big Data experience.",
            ))
            await session.commit()
            return job_id, candidate_id

    app = create_app()
    with TestClient(app) as client:
        job_id, candidate_id = asyncio.run(_seed())
        headers = _auth_headers(client)

        resp = client.post("/api/v1/reports/candidate", json={
            "job_id": job_id,
            "candidate_id": candidate_id,
        }, headers=headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    items = {item["skill"]: item["matched"] for item in data["skill_gap"]["items"]}

    assert items == {
        "python": True,
        "deep learning": True,
        "sql": True,
        "vector database": True,
        "c/c++": True,
        "big data": True,
    }
    assert data["skill_gap"]["missing_required"] == []
    assert data["score_breakdown"]["required_skills_score"] == 1.0
    assert data["score_breakdown"]["optional_skills_score"] == 1.0


def test_candidate_report_uses_cv_evidence_when_learning_was_false_positive() -> None:
    """
    Checks that candidate report uses CV evidence when learning was false positive.
    """
    import asyncio

    async def _seed() -> tuple[str, str]:
        """
        Seeds database rows used by the surrounding test.
        """
        async with SessionLocal() as session:
            job_id = str(uuid.uuid4())
            candidate_id = str(uuid.uuid4())
            session.add(Job(
                id=job_id,
                title="AI Engineer",
                description="AI engineer with Python and C/C++.",
                required_skills=["python"],
                optional_skills=["c/c++"],
                seniority="mid",
            ))
            session.add(Candidate(
                id=candidate_id,
                full_name="False Learning Candidate",
                email=f"false-learning-{uuid.uuid4().hex[:8]}@test.com",
                phone="+961",
                skills=["pytorch"],
                skills_detailed=[
                    {
                        "name": "python",
                        "status": "learning",
                        "context": "Specialized in Python programming, Machine Learning, and Software Development",
                    },
                    {
                        "name": "c++",
                        "status": "learning",
                        "context": "Python (AI/ML/Deep Learning), Java, C/C++ (Data Structures & Algorithms)",
                    },
                ],
                negative_skills=[],
                learning_skills=["python", "c++"],
                experience=[],
                education=[],
                projects=[],
                raw_text=(
                    "Technical Skills: Python (AI/ML/Deep Learning), Java, "
                    "C/C++ (Data Structures & Algorithms). "
                    "Specialized in Python programming, Machine Learning, and Software Development."
                ),
            ))
            await session.commit()
            return job_id, candidate_id

    app = create_app()
    with TestClient(app) as client:
        job_id, candidate_id = asyncio.run(_seed())
        headers = _auth_headers(client)

        resp = client.post("/api/v1/reports/candidate", json={
            "job_id": job_id,
            "candidate_id": candidate_id,
        }, headers=headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    items = {item["skill"]: item["matched"] for item in data["skill_gap"]["items"]}

    assert items["python"] is True
    assert items["c/c++"] is True
    assert data["skill_gap"]["missing_required"] == []


def test_candidate_report_preserves_zero_semantic_but_refreshes_stale_match_score() -> None:
    """
    Checks that candidate report preserves zero semantic but refreshes stale match
    score.
    """
    import asyncio

    async def _seed() -> tuple[str, str]:
        """
        Seeds database rows used by the surrounding test.
        """
        async with SessionLocal() as session:
            job_id = str(uuid.uuid4())
            candidate_id = str(uuid.uuid4())
            session.add(Job(
                id=job_id,
                title="Docker Engineer",
                description="Engineer with Docker.",
                required_skills=["docker"],
                optional_skills=[],
                seniority="mid",
            ))
            session.add(Candidate(
                id=candidate_id,
                full_name="Zero Semantic Candidate",
                email=f"zero-semantic-{uuid.uuid4().hex[:8]}@test.com",
                phone="+961",
                skills=["docker"],
                experience=["Built containerized services."],
                education=["BSc"],
                projects=["Deployment pipeline"],
                raw_text="Docker deployment experience.",
            ))
            session.add(MatchResult(
                job_id=job_id,
                candidate_id=candidate_id,
                score=0.42,
                reasoning={"semantic_score": 0.0},
            ))
            await session.commit()
            return job_id, candidate_id

    app = create_app()
    with TestClient(app) as client:
        job_id, candidate_id = asyncio.run(_seed())
        headers = _auth_headers(client)

        resp = client.post("/api/v1/reports/candidate", json={
            "job_id": job_id,
            "candidate_id": candidate_id,
        }, headers=headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["score_breakdown"]["similarity_score"] == 0.0
    assert data["score_breakdown"]["overall_score"] == 0.575
    assert data["score_breakdown"]["scoring_model"] == "hybrid_v2"
    assert data["score_breakdown"]["score_trace"]["source"] == "report_refresh_stale_match"


def test_candidate_report_uses_junior_project_bonus_without_existing_match() -> None:
    """
    Checks that candidate report uses junior project bonus without existing match.
    """
    import asyncio

    async def _seed() -> tuple[str, str]:
        """
        Seeds database rows used by the surrounding test.
        """
        async with SessionLocal() as session:
            job_id = str(uuid.uuid4())
            candidate_id = str(uuid.uuid4())
            session.add(Job(
                id=job_id,
                title="Junior Next.js Developer",
                description="Junior developer building React and Next.js apps.",
                required_skills=["next.js", "react"],
                optional_skills=["postgresql"],
                seniority="junior",
            ))
            session.add(Candidate(
                id=candidate_id,
                full_name="Project Bonus Candidate",
                email=f"project-bonus-{uuid.uuid4().hex[:8]}@test.com",
                phone="+961",
                skills=[],
                experience=[],
                education=[],
                projects=["GitHub portfolio: built a Next.js React dashboard with PostgreSQL data."],
                raw_text="Projects: Next.js React dashboard with PostgreSQL.",
            ))
            await session.commit()
            return job_id, candidate_id

    app = create_app()
    with TestClient(app) as client:
        job_id, candidate_id = asyncio.run(_seed())
        headers = _auth_headers(client)

        resp = client.post("/api/v1/reports/candidate", json={
            "job_id": job_id,
            "candidate_id": candidate_id,
        }, headers=headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["score_breakdown"]["similarity_score"] == 0.5


def test_candidate_report_uses_junior_project_bonus_with_existing_zero_semantic_match() -> None:
    """
    Checks that candidate report uses junior project bonus with existing zero semantic
    match.
    """
    import asyncio

    async def _seed() -> tuple[str, str]:
        """
        Seeds database rows used by the surrounding test.
        """
        async with SessionLocal() as session:
            job_id = str(uuid.uuid4())
            candidate_id = str(uuid.uuid4())
            session.add(Job(
                id=job_id,
                title="Junior Next.js Developer",
                description="Junior developer building React and Next.js apps.",
                required_skills=["next.js", "react"],
                optional_skills=["postgresql"],
                seniority="junior",
            ))
            session.add(Candidate(
                id=candidate_id,
                full_name="Stored Zero Project Candidate",
                email=f"stored-zero-project-{uuid.uuid4().hex[:8]}@test.com",
                phone="+961",
                skills=[],
                experience=[],
                education=[],
                projects=["[1] Developer Experience Portal"],
                raw_text=(
                    "PROJECTS\n"
                    "[1] Developer Experience Portal\n"
                    "Technologies: Go, PostgreSQL, GraphQL, React, Docker\n"
                    "Built an internal developer portal.\n"
                    "TECHNICAL SKILLS\n"
                    "Frontend: Next.js\n"
                ),
            ))
            session.add(MatchResult(
                job_id=job_id,
                candidate_id=candidate_id,
                score=0.42,
                reasoning={"semantic_score": 0.0},
            ))
            await session.commit()
            return job_id, candidate_id

    app = create_app()
    with TestClient(app) as client:
        job_id, candidate_id = asyncio.run(_seed())
        headers = _auth_headers(client)

        resp = client.post("/api/v1/reports/candidate", json={
            "job_id": job_id,
            "candidate_id": candidate_id,
        }, headers=headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["score_breakdown"]["similarity_score"] == 0.5


def test_candidate_report_ignores_projects_as_required_skill_term() -> None:
    """
    Checks that candidate report ignores projects as required skill term.
    """
    import asyncio

    async def _seed() -> tuple[str, str]:
        """
        Seeds database rows used by the surrounding test.
        """
        async with SessionLocal() as session:
            job_id = str(uuid.uuid4())
            candidate_id = str(uuid.uuid4())
            session.add(Job(
                id=job_id,
                title="AI Engineer",
                description="Junior AI engineer with Python projects.",
                required_skills=["python", "projects"],
                optional_skills=[],
                seniority="junior",
            ))
            session.add(Candidate(
                id=candidate_id,
                full_name="Project Word Candidate",
                email=f"project-word-{uuid.uuid4().hex[:8]}@test.com",
                phone="+961",
                skills=["python"],
                experience=[],
                education=[],
                projects=[],
                raw_text="PROJ PROJECT EXPERIENCE\nPython model project.",
            ))
            await session.commit()
            return job_id, candidate_id

    app = create_app()
    with TestClient(app) as client:
        job_id, candidate_id = asyncio.run(_seed())
        headers = _auth_headers(client)

        resp = client.post("/api/v1/reports/candidate", json={
            "job_id": job_id,
            "candidate_id": candidate_id,
        }, headers=headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["score_breakdown"]["required_skills_score"] == 1.0
    assert "projects" not in [item["skill"] for item in data["skill_gap"]["items"]]


def test_candidate_report_explains_interview_blended_score() -> None:
    """
    Checks that candidate report explains interview blended score.
    """
    import asyncio

    async def _seed() -> tuple[str, str]:
        """
        Seeds database rows used by the surrounding test.
        """
        async with SessionLocal() as session:
            job_id = str(uuid.uuid4())
            candidate_id = str(uuid.uuid4())
            session.add(Job(
                id=job_id,
                title="Python Engineer",
                description="Engineer with Python.",
                required_skills=["python"],
                optional_skills=[],
                seniority="mid",
            ))
            session.add(Candidate(
                id=candidate_id,
                full_name="Interview Candidate",
                email=f"interview-report-{uuid.uuid4().hex[:8]}@test.com",
                phone="+961",
                skills=["python"],
                experience=["Built Python services."],
                education=["BSc"],
                projects=["API"],
                raw_text="Python service experience.",
            ))
            session.add(MatchResult(
                job_id=job_id,
                candidate_id=candidate_id,
                score=0.705,
                reasoning={
                    "scoring_model": "cv_interview_blend",
                    "semantic_score": 0.0,
                    "cv_match_score": 0.6,
                    "interview_score": 0.9,
                    "interview_analysis_status": "ready",
                },
            ))
            await session.commit()
            return job_id, candidate_id

    app = create_app()
    with TestClient(app) as client:
        job_id, candidate_id = asyncio.run(_seed())
        headers = _auth_headers(client)

        resp = client.post("/api/v1/reports/candidate", json={
            "job_id": job_id,
            "candidate_id": candidate_id,
        }, headers=headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["score_breakdown"]["overall_score"] == 0.705
    assert "CV/job match: 60%, interview: 90%" in data["recommendation"]


def test_compare_candidates() -> None:
    """
    Checks that compare candidates.
    """
    app = create_app()
    with TestClient(app) as client:
        job_id, cand1_id, cand2_id = _seed_data()
        headers = _auth_headers(client)

        resp = client.post("/api/v1/reports/compare", json={
            "job_id": job_id,
            "candidate_ids": [cand1_id, cand2_id],
        }, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_title"] == "Backend Engineer"
        assert len(data["candidates"]) == 2
        assert data["candidates"][0]["candidate_name"] in ("Alice", "Bob")


def test_compare_candidates_refreshes_stale_persisted_match_scores() -> None:
    """
    Checks that compare candidates refreshes stale persisted match scores.
    """
    import asyncio

    async def _seed() -> tuple[str, str, str]:
        """
        Seeds database rows used by the surrounding test.
        """
        async with SessionLocal() as session:
            job_id = str(uuid.uuid4())
            first_id = str(uuid.uuid4())
            second_id = str(uuid.uuid4())
            session.add(Job(
                id=job_id,
                title="Persisted Score Role",
                description="Python engineer.",
                required_skills=["python"],
                optional_skills=[],
                seniority="mid",
            ))
            session.add_all([
                Candidate(
                    id=first_id,
                    full_name="Lower Persisted",
                    email=f"lower-{uuid.uuid4().hex[:8]}@test.com",
                    phone="+1",
                    skills=["python"],
                    experience=["Python"],
                    education=["BSc"],
                    projects=[],
                    raw_text="Python.",
                ),
                Candidate(
                    id=second_id,
                    full_name="Higher Persisted",
                    email=f"higher-{uuid.uuid4().hex[:8]}@test.com",
                    phone="+2",
                    skills=[],
                    experience=["General backend"],
                    education=["BSc"],
                    projects=[],
                    raw_text="General backend.",
                ),
            ])
            session.add_all([
                MatchResult(
                    job_id=job_id,
                    candidate_id=first_id,
                    score=0.25,
                    reasoning={
                        "semantic_score": 0.0,
                        "skill_score": 1.0,
                        "matched_required": ["python"],
                        "matched_optional": [],
                        "missing_required": [],
                    },
                ),
                MatchResult(
                    job_id=job_id,
                    candidate_id=second_id,
                    score=0.95,
                    reasoning={
                        "semantic_score": 0.0,
                        "skill_score": 0.0,
                        "matched_required": [],
                        "matched_optional": [],
                        "missing_required": ["python"],
                    },
                ),
            ])
            await session.commit()
            return job_id, first_id, second_id

    app = create_app()
    with TestClient(app) as client:
        job_id, first_id, second_id = asyncio.run(_seed())
        headers = _auth_headers(client)
        resp = client.post("/api/v1/reports/compare", json={
            "job_id": job_id,
            "candidate_ids": [first_id, second_id],
        }, headers=headers)

    assert resp.status_code == 200, resp.text
    candidates = resp.json()["candidates"]
    assert candidates[0]["candidate_id"] == first_id
    assert candidates[0]["overall_score"] > candidates[1]["overall_score"]
    assert candidates[1]["candidate_id"] == second_id
