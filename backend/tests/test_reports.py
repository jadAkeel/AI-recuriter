import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal, init_db
from app.main import create_app
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.user import User
from sqlalchemy import select


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = f"recruiter-{uuid.uuid4().hex[:8]}@example.com"
    register_payload = {
        "email": email,
        "password": "strongpass123",
        "full_name": "Recruiter User",
    }
    client.post("/api/v1/auth/register", json=register_payload)

    async def _promote_recruiter() -> None:
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
    import asyncio
    asyncio.run(init_db())


def _seed_data() -> tuple[str, str, str]:
    import asyncio
    async def _seed():
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


def test_compare_candidates() -> None:
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
