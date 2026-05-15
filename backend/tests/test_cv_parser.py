import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal, init_db
from app.main import create_app
from app.models.user import User
from app.services.cv_parser import parse_cv_text
from app.services.auth import hash_password
from app.services.enhanced_cv_parser import get_enhanced_cv_parser
from app.services.job_parser import parse_job_description


def test_parse_cv_text_extracts_skills_and_sections() -> None:
    text = """
    Jane Doe
    jane.doe@example.com
    +1 (555) 123-4567

    Skills
    Python, FastAPI, PostgreSQL, Docker

    Experience
    Senior Software Engineer at Acme Corp (2019-2024)
    Built API services using FastAPI and PostgreSQL.

    Education
    BSc Computer Science, State University

    Projects
    Resume Parser: Built a CV parsing pipeline in Python.
    """

    profile = parse_cv_text(text)

    assert profile.full_name == "Jane Doe"
    assert profile.email == "jane.doe@example.com"
    assert "python" in profile.skills
    assert "fastapi" in profile.skills
    assert profile.experience
    assert profile.education
    assert profile.projects


def test_parsers_extract_symbol_skills() -> None:
    cv = parse_cv_text("Candidate\nSkills\nC++ C# Python CI/CD")
    job = parse_job_description("Requirements\nC++ C# Python CI/CD")

    for skill in ("c++", "c#", "python", "ci/cd"):
        assert skill in cv.skills
        assert skill in job.required_skills


@pytest.mark.asyncio
async def test_enhanced_parser_does_not_invent_all_single_word_skills() -> None:
    parser = get_enhanced_cv_parser()
    profile = await parser.parse_async("Candidate\nSkills\nPython FastAPI C++ C# CI/CD")

    assert {"python", "fastapi", "c++", "c#", "ci/cd"}.issubset(set(profile.skills))
    assert "java" not in profile.skills
    assert len(profile.skills) < 20


def test_stream_candidates_parses_uploaded_text_cv() -> None:
    async def _seed_recruiter() -> tuple[str, str]:
        await init_db()
        email = f"stream-recruiter-{uuid.uuid4().hex[:8]}@example.com"
        password = "password123"
        async with SessionLocal() as session:
            session.add(User(
                id=str(uuid.uuid4()),
                email=email,
                password_hash=hash_password(password),
                full_name="Stream Recruiter",
                role="recruiter",
            ))
            await session.commit()
        return email, password

    email, password = asyncio.run(_seed_recruiter())
    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        token = login.json()["access_token"]
        cv_text = """
        Stream Candidate
        stream.candidate@example.com
        Skills
        Python, FastAPI, PostgreSQL
        Experience
        Built matching APIs with Python and FastAPI.
        """
        response = client.post(
            "/api/v1/candidates/stream",
            params={"use_llm": "false"},
            files=[("files", ("stream-candidate.txt", cv_text.encode("utf-8"), "text/plain"))],
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert lines[0]["status"] == "success"
    assert lines[0]["candidate"]["full_name"] == "Stream Candidate"
    assert "python" in lines[0]["candidate"]["skills"]


def test_create_candidate_succeeds_when_embedding_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import candidates as candidates_api

    class FailingEmbeddingService:
        async def embed(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("embedding service unavailable")

    async def _seed_recruiter() -> tuple[str, str]:
        await init_db()
        email = f"embed-fail-recruiter-{uuid.uuid4().hex[:8]}@example.com"
        password = "password123"
        async with SessionLocal() as session:
            session.add(User(
                id=str(uuid.uuid4()),
                email=email,
                password_hash=hash_password(password),
                full_name="Embedding Fail Recruiter",
                role="recruiter",
            ))
            await session.commit()
        return email, password

    monkeypatch.setattr(candidates_api, "get_embedding_service", lambda: FailingEmbeddingService())

    email, password = asyncio.run(_seed_recruiter())
    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        token = login.json()["access_token"]
        cv_text = f"""
        Embed Failure Candidate
        embed.failure.{uuid.uuid4().hex[:8]}@example.com
        Skills
        Python, FastAPI
        """
        response = client.post(
            "/api/v1/candidates",
            params={"use_llm": "false"},
            files={"file": ("embed-failure.txt", cv_text.encode("utf-8"), "text/plain")},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["full_name"] == "Embed Failure Candidate"
    assert "python" in body["skills"]
