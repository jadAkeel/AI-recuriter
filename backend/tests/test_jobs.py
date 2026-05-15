import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SessionLocal, init_db
from app.main import create_app
from app.models.embedding import Embedding
from app.models.interview import InterviewSession
from app.models.job import Job
from app.models.match_result import MatchResult
from app.models.report import Report
from app.models.user import User
from app.services.auth import hash_password

_VEC_384 = [0.0] * 384


@pytest.mark.asyncio
async def test_delete_job_happy_path():
    """Delete a job that has related MatchResult, InterviewSession, Report, Embedding."""
    await init_db()
    async with SessionLocal() as session:
        user = User(
            id=str(uuid.uuid4()), email="admin@del.com",
            password_hash=hash_password("p"), full_name="Admin", role="owner",
        )
        session.add(user)
        job_id = str(uuid.uuid4())
        session.add(Job(id=job_id, title="T", description="D", required_skills=[], optional_skills=[], seniority="mid"))
        session.add(MatchResult(job_id=job_id, candidate_id=str(uuid.uuid4()), score=0.9, reasoning={}))
        session.add(InterviewSession(id=str(uuid.uuid4()), job_id=job_id, candidate_id=str(uuid.uuid4()),
                                     questions=[], answers=[], evaluations=[], chat_history=[], status="completed"))
        session.add(Report(id=str(uuid.uuid4()), job_id=job_id, candidate_id=str(uuid.uuid4()),
                           overall_score=0.8, score_breakdown={}, skill_gap={}, strengths=[], weaknesses=[], recommendation=""))
        session.add(Embedding(entity_type="job", entity_id=job_id, embedding_json=_VEC_384, embedding_vector=_VEC_384))
        await session.commit()

    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": "admin@del.com", "password": "p"})
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.delete(f"/api/v1/jobs/{job_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "deleted", "job_id": job_id}

    async with SessionLocal() as session:
        assert (await session.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none() is None
        assert (await session.execute(select(MatchResult).where(MatchResult.job_id == job_id))).scalars().all() == []
        assert (await session.execute(select(InterviewSession).where(InterviewSession.job_id == job_id))).scalars().all() == []
        assert (await session.execute(select(Report).where(Report.job_id == job_id))).scalars().all() == []
        assert (await session.execute(
            select(Embedding).where(Embedding.entity_type == "job", Embedding.entity_id == job_id))).scalars().all() == []


@pytest.mark.asyncio
async def test_delete_job_no_related_data():
    """Delete a job that has no related data (just the Job row)."""
    await init_db()
    async with SessionLocal() as session:
        user = User(
            id=str(uuid.uuid4()), email="admin@del2.com",
            password_hash=hash_password("p"), full_name="Admin", role="owner",
        )
        session.add(user)
        job_id = str(uuid.uuid4())
        session.add(Job(id=job_id, title="T", description="D", required_skills=[], optional_skills=[], seniority="mid"))
        await session.commit()

    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": "admin@del2.com", "password": "p"})
        token = login.json()["access_token"]
        resp = client.delete(f"/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_delete_nonexistent_job():
    """Deleting a job that does not exist should return 404."""
    await init_db()
    async with SessionLocal() as session:
        user = User(
            id=str(uuid.uuid4()), email="admin@del3.com",
            password_hash=hash_password("p"), full_name="Admin", role="owner",
        )
        session.add(user)
        await session.commit()

    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": "admin@del3.com", "password": "p"})
        token = login.json()["access_token"]
        resp = client.delete(f"/api/v1/jobs/{str(uuid.uuid4())}", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Job not found"


@pytest.mark.asyncio
async def test_delete_job_unauthorized():
    """Users with role 'candidate' should not be allowed to delete jobs."""
    await init_db()
    async with SessionLocal() as session:
        user = User(
            id=str(uuid.uuid4()), email="cand@del.com",
            password_hash=hash_password("p"), full_name="Candidate", role="candidate",
        )
        session.add(user)
        job_id = str(uuid.uuid4())
        session.add(Job(id=job_id, title="T", description="D", required_skills=[], optional_skills=[], seniority="mid"))
        await session.commit()

    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": "cand@del.com", "password": "p"})
        token = login.json()["access_token"]
        resp = client.delete(f"/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    async with SessionLocal() as session:
        assert (await session.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_delete_job_unauthenticated():
    """Request without a token should return 401."""
    app = create_app()
    with TestClient(app) as client:
        resp = client.delete(f"/api/v1/jobs/{str(uuid.uuid4())}")
        assert resp.status_code == 401
