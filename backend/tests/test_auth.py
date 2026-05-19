import uuid
import asyncio

from fastapi.testclient import TestClient

from app.core.db import SessionLocal, init_db
from app.main import create_app
from app.models.candidate import Candidate


def test_register_and_login() -> None:
    """
    Checks that register and login.
    """
    app = create_app()
    with TestClient(app) as client:
        email = f"test-{uuid.uuid4().hex[:8]}@example.com"

        register_payload = {
            "email": email,
            "password": "strongpass123",
            "full_name": "Test User",
        }
        resp = client.post("/api/v1/auth/register", json=register_payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == email
        assert data["role"] == "candidate"
        assert "id" in data

        login_payload = {"email": email, "password": "strongpass123"}
        resp = client.post("/api/v1/auth/login", json=login_payload)
        assert resp.status_code == 200
        tokens = resp.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens

        resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        assert resp.status_code == 200
        me = resp.json()
        assert me["email"] == email


def test_candidate_can_only_read_own_candidate_profile() -> None:
    """
    Checks that candidate can only read own candidate profile.
    """
    app = create_app()
    with TestClient(app) as client:
        email = f"candidate-{uuid.uuid4().hex[:8]}@example.com"
        register_payload = {
            "email": email,
            "password": "strongpass123",
            "full_name": "Candidate User",
        }
        assert client.post("/api/v1/auth/register", json=register_payload).status_code == 201

        own_id = str(uuid.uuid4())
        other_id = str(uuid.uuid4())

        async def _seed_candidates() -> None:
            """
            Supports the surrounding test for test candidate can only read own candidate
            profile.
            """
            await init_db()
            async with SessionLocal() as session:
                session.add(Candidate(
                    id=own_id,
                    full_name="Own Candidate",
                    email=email,
                    phone="+123",
                    skills=["python"],
                    experience=[],
                    education=[],
                    projects=[],
                    raw_text="Own CV",
                ))
                session.add(Candidate(
                    id=other_id,
                    full_name="Other Candidate",
                    email=f"other-{uuid.uuid4().hex[:8]}@example.com",
                    phone="+456",
                    skills=["java"],
                    experience=[],
                    education=[],
                    projects=[],
                    raw_text="Other CV",
                ))
                await session.commit()

        asyncio.run(_seed_candidates())

        login_resp = client.post("/api/v1/auth/login", json={"email": email, "password": "strongpass123"})
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        own_resp = client.get(f"/api/v1/candidates/{own_id}", headers=headers)
        assert own_resp.status_code == 200

        other_resp = client.get(f"/api/v1/candidates/{other_id}", headers=headers)
        assert other_resp.status_code == 403
