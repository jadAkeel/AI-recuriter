import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal, init_db
from app.main import create_app
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.user import User
from app.services.auth import hash_password
from app.services.embedding import HashEmbeddingService
from app.services.matching import rank_candidates
from app.services.vector_store import VectorStore


@pytest.mark.asyncio
async def test_rank_candidates_returns_results() -> None:
    await init_db()
    embedder = HashEmbeddingService()

    async with SessionLocal() as session:
        job_id = str(uuid.uuid4())
        job = Job(
            id=job_id,
            title="Backend Engineer",
            description="We need a backend engineer with Python and FastAPI.",
            required_skills=["python", "fastapi"],
            optional_skills=["docker"],
            seniority="mid",
        )
        session.add(job)

        candidate_id = str(uuid.uuid4())
        candidate = Candidate(
            id=candidate_id,
            full_name="Jane Doe",
            email="jane@example.com",
            phone="+15551234567",
            skills=["python", "fastapi", "docker"],
            experience=["Backend Engineer"],
            education=["BSc Computer Science"],
            projects=["API platform"],
            raw_text="Python FastAPI backend engineer",
        )
        session.add(candidate)
        await session.commit()

        store = VectorStore(session)
        emb = await embedder.embed([candidate.raw_text])
        await store.upsert_embedding("candidate", candidate_id, emb[0])

        job_result = await embedder.embed([job.description])
        job_embedding = job_result[0]
        results = await rank_candidates(session, job, job_embedding, top_k=5)

    assert results
    assert results[0].candidate_id == candidate_id


@pytest.mark.asyncio
async def test_python_job_ranks_python_candidate_above_java_candidate() -> None:
    await init_db()
    async with SessionLocal() as session:
        job = Job(
            id=str(uuid.uuid4()),
            title="Python Backend Engineer",
            description="Senior Python Backend Engineer with FastAPI, PostgreSQL, Docker, and Redis.",
            required_skills=["python", "fastapi", "postgresql"],
            optional_skills=["docker", "redis"],
            seniority="senior",
        )
        good_candidate = Candidate(
            id=str(uuid.uuid4()),
            full_name="Python Candidate",
            email="python@example.com",
            phone="+15550000001",
            skills=["python", "fastapi", "postgresql", "docker", "redis"],
            experience=["Senior Backend Engineer 2018 2025"],
            education=["BSc Computer Science"],
            projects=["FastAPI PostgreSQL platform"],
            total_years_experience=7,
            raw_text="Senior Python FastAPI PostgreSQL Docker Redis engineer",
        )
        wrong_candidate = Candidate(
            id=str(uuid.uuid4()),
            full_name="Java Candidate",
            email="java@example.com",
            phone="+15550000002",
            skills=["java", "spring boot", "mysql"],
            experience=["Backend Engineer 2018 2025"],
            education=["BSc Computer Science"],
            projects=["Spring Boot service"],
            total_years_experience=7,
            raw_text="Senior Java Spring Boot MySQL engineer",
        )
        session.add_all([job, good_candidate, wrong_candidate])
        await session.commit()

        results = await rank_candidates(
            session,
            job,
            [0.0] * 384,
            top_k=2,
            candidates=[good_candidate, wrong_candidate],
            cross_encoder_top_k=0,
            use_hybrid=True,
        )

    assert [result.candidate_id for result in results] == [good_candidate.id, wrong_candidate.id]
    assert results[0].reasoning["required_score"] == 1.0
    assert results[1].reasoning["required_score"] == 0.0


def test_matching_api_returns_candidate_details() -> None:
    import asyncio

    async def _seed() -> tuple[str, dict[str, str]]:
        await init_db()
        async with SessionLocal() as session:
            user = User(
                id=str(uuid.uuid4()),
                email="recruiter-match@example.com",
                password_hash=hash_password("password123"),
                full_name="Recruiter Match",
                role="recruiter",
            )
            job = Job(
                id=str(uuid.uuid4()),
                title="FastAPI Engineer",
                description="FastAPI engineer with Python and PostgreSQL.",
                required_skills=["python", "fastapi", "postgresql"],
                optional_skills=["docker"],
                seniority="mid",
            )
            candidate = Candidate(
                id=str(uuid.uuid4()),
                full_name="Visible Candidate",
                email="visible@example.com",
                phone="+15550000003",
                skills=["python", "fastapi", "postgresql", "docker"],
                experience=["Backend Engineer"],
                education=["BSc"],
                projects=["API"],
                total_years_experience=4,
                raw_text="Python FastAPI PostgreSQL Docker",
            )
            session.add_all([user, job, candidate])
            await session.commit()
            return job.id, {"email": user.email, "password": "password123"}

    job_id, credentials = asyncio.run(_seed())
    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json=credentials)
        token = login.json()["access_token"]
        response = client.post(
            f"/api/v1/jobs/{job_id}/match",
            params={"cross_encoder_top_k": 0},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    first = response.json()["results"][0]
    assert first["candidate_name"] == "Visible Candidate"
    assert first["candidate_email"] == "visible@example.com"
    assert "python" in first["candidate_skills"]
