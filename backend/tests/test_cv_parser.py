import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal, init_db
from app.main import create_app
from app.models.candidate import Candidate
from app.models.embedding import Embedding
from app.models.user import User
from app.services.cv_parser import extract_text, parse_cv_text
from app.services.auth import hash_password
from app.services.enhanced_cv_parser import get_enhanced_cv_parser, get_simple_cv_parser
from app.services.job_parser import parse_job_description
from app.services.skill_catalog import normalize_text_for_skill_matching, skill_in_text
from sqlalchemy import select


def test_parse_cv_text_extracts_skills_and_sections() -> None:
    """
    Checks that parse CV text extracts skills and sections.
    """
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


def test_text_pdf_extracts_without_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Checks that text PDF extracts without OCR.
    """
    from app.services import cv_parser

    monkeypatch.setattr(
        cv_parser,
        "_extract_pdf_text",
        lambda content: "PDF Candidate\nSkills\nPython FastAPI",
    )
    monkeypatch.setattr(
        cv_parser,
        "_ocr_pdf_text",
        lambda content: pytest.fail("OCR should not run when PDF text layer is parseable"),
    )

    text = extract_text("candidate.pdf", b"pdf-bytes")

    assert "PDF Candidate" in text


def test_scanned_pdf_triggers_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Checks that scanned PDF triggers OCR.
    """
    from app.services import cv_parser

    monkeypatch.setattr(cv_parser, "_extract_pdf_text", lambda content: "   ")
    monkeypatch.setattr(
        cv_parser,
        "_ocr_pdf_text",
        lambda content: "Scanned Candidate\nSkills\nPython Docker",
    )

    text = extract_text("scanned.pdf", b"pdf-bytes")

    assert "Scanned Candidate" in text
    assert "Python Docker" in text


def test_empty_pdf_after_ocr_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Checks that empty PDF after OCR fails clearly.
    """
    from app.services import cv_parser

    monkeypatch.setattr(cv_parser, "_extract_pdf_text", lambda content: "")
    monkeypatch.setattr(cv_parser, "_ocr_pdf_text", lambda content: "")

    with pytest.raises(ValueError, match="OCR returned empty text"):
        extract_text("empty.pdf", b"pdf-bytes")


def test_corrupted_pdf_fails_without_backend_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Checks that corrupted PDF fails without backend crash.
    """
    from app.services import cv_parser

    def raise_corrupt(content: bytes) -> str:
        """
        Raises a parsing error to simulate a corrupted PDF.
        """
        raise ValueError("Could not safely extract text from PDF")

    monkeypatch.setattr(cv_parser, "_extract_pdf_text", raise_corrupt)

    with pytest.raises(ValueError, match="Could not safely extract text from PDF"):
        extract_text("corrupted.pdf", b"not-a-pdf")


def test_parsers_extract_symbol_skills() -> None:
    """
    Checks that parsers extract symbol skills.
    """
    cv = parse_cv_text("Candidate\nSkills\nC++ C# Python CI/CD")
    job = parse_job_description("Requirements\nC++ C# Python CI/CD")

    for skill in ("c++", "c#", "python", "ci/cd"):
        assert skill in cv.skills
        assert skill in job.required_skills


def test_catalog_aliases_normalize_to_canonical_names() -> None:
    """
    Checks that catalog aliases normalize to canonical names.
    """
    cv = parse_cv_text("Candidate\nSkills\nVueJS, k8s, React.js, Golang, Scikit Learn")
    job = parse_job_description("Requirements\nVueJS, k8s, React.js, Golang, Scikit Learn")

    expected = {"vue.js", "kubernetes", "react", "go", "scikit-learn"}
    assert expected.issubset(set(cv.skills))
    assert expected.issubset(set(job.required_skills))


def test_skill_matching_uses_exact_boundaries() -> None:
    """
    Checks that skill matching uses exact boundaries.
    """
    google_text = normalize_text_for_skill_matching("Google Cloud engineer")
    golang_text = normalize_text_for_skill_matching("Golang engineer")

    assert not skill_in_text("go", google_text)
    assert skill_in_text("go", golang_text)


def test_parsers_extract_restful_api_and_mongoose_variants() -> None:
    """
    Checks that parsers extract restful API and mongoose variants.
    """
    cv = parse_cv_text(
        "Azzam Candidate\n"
        "Skills\n"
        "Built RESTful APIs with Mongoose and MongoDB."
    )
    job = parse_job_description(
        "Junior Next.js Developer\n"
        "Requirements\n"
        "RESTful API Development\n"
        "Nice to have\n"
        "Mongoose"
    )

    assert {"rest api", "mongoose"}.issubset(set(cv.skills))
    assert "rest api" in job.required_skills
    assert "mongoose" in job.optional_skills


def test_enhanced_parser_does_not_treat_domain_learning_as_learning_status() -> None:
    """
    Checks that enhanced parser does not treat domain learning as learning status.
    """
    parser = get_simple_cv_parser()
    profile = parser.parse(
        "Candidate\n"
        "Skills\n"
        "Python (AI/ML/Deep Learning), Java, C/C++ (Data Structures & Algorithms)\n"
        "Education\n"
        "Specialized in Python programming, Machine Learning, and Software Development"
    )

    assert "python" in profile.skills
    assert "c++" in profile.skills
    assert "python" not in profile.learning_skills
    assert "c++" not in profile.learning_skills


def test_enhanced_parser_keeps_active_learning_searchable() -> None:
    """
    Checks that enhanced parser keeps active learning skills searchable.
    """
    parser = get_simple_cv_parser()
    profile = parser.parse(
        "Candidate\n"
        "Skills\n"
        "Python\n"
        "Experience\n"
        "I build APIs with Python. I want to learn Docker next."
    )

    assert "python" in profile.skills
    assert "docker" in profile.skills
    assert "docker" in profile.learning_skills
    docker_detail = next(item for item in profile.skills_detailed if item.name == "docker")
    assert docker_detail.status == "learning"


def test_enhanced_parser_keeps_inline_project_technologies_inside_projects_section() -> None:
    """
    Checks that enhanced parser keeps inline project technologies inside projects
    section.
    """
    parser = get_simple_cv_parser()
    profile = parser.parse(
        "Candidate\n"
        "Projects\n"
        "[1] Developer Experience Portal\n"
        "Technologies: Go, PostgreSQL, GraphQL, React, Docker\n"
        "Built an internal developer portal.\n"
        "Technical Skills\n"
        "Frontend: Next.js\n"
    )

    assert "Technologies: Go, PostgreSQL, GraphQL, React, Docker" in profile.projects
    assert "Built an internal developer portal." in profile.projects


@pytest.mark.asyncio
async def test_enhanced_parser_does_not_invent_all_single_word_skills() -> None:
    """
    Checks that enhanced parser does not invent all single word skills.
    """
    parser = get_enhanced_cv_parser()
    profile = await parser.parse_async("Candidate\nSkills\nPython FastAPI C++ C# CI/CD")

    assert {"python", "fastapi", "c++", "c#", "ci/cd"}.issubset(set(profile.skills))
    assert "java" not in profile.skills
    assert len(profile.skills) < 20


def test_stream_candidates_parses_uploaded_text_cv() -> None:
    """
    Checks that stream candidates parses uploaded text CV.
    """
    async def _seed_recruiter() -> tuple[str, str]:
        """
        Supports the surrounding test for test stream candidates parses uploaded text
        CV.
        """
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
    """
    Checks that create candidate succeeds when embedding fails.
    """
    from app.services import embedding as embedding_service

    class FailingEmbeddingService:
        async def embed(self, texts: list[str]) -> list[list[float]]:
            """
            Returns predictable embeddings for the test double.
            """
            raise RuntimeError("embedding service unavailable")

    async def _seed_recruiter() -> tuple[str, str]:
        """
        Supports the surrounding test for test create candidate succeeds when embedding
        fails.
        """
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

    monkeypatch.setattr(embedding_service, "get_embedding_service", lambda: FailingEmbeddingService())

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


def test_create_candidate_reupload_updates_existing_profile_and_embedding() -> None:
    """
    Checks that create candidate reupload updates existing profile and embedding.
    """
    async def _seed_recruiter() -> tuple[str, str]:
        """
        Supports the surrounding test for test create candidate reupload updates
        existing profile and embedding.
        """
        await init_db()
        email = f"reupload-recruiter-{uuid.uuid4().hex[:8]}@example.com"
        password = "password123"
        async with SessionLocal() as session:
            session.add(User(
                id=str(uuid.uuid4()),
                email=email,
                password_hash=hash_password(password),
                full_name="Reupload Recruiter",
                role="recruiter",
            ))
            await session.commit()
        return email, password

    async def _load_candidate(candidate_id: str) -> tuple[Candidate | None, Embedding | None]:
        """
        Loads the candidate and embedding rows created by the test.
        """
        async with SessionLocal() as session:
            candidate = await session.get(Candidate, candidate_id)
            embedding_result = await session.execute(
                select(Embedding).where(
                    Embedding.entity_type == "candidate",
                    Embedding.entity_id == candidate_id,
                )
            )
            return candidate, embedding_result.scalar_one_or_none()

    candidate_email = f"reupload-candidate-{uuid.uuid4().hex[:8]}@example.com"
    recruiter_email, password = asyncio.run(_seed_recruiter())
    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": recruiter_email, "password": password})
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        first_cv = f"""
        Reupload Candidate
        {candidate_email}
        Skills
        Python, FastAPI
        Experience
        Built Python APIs.
        """
        first = client.post(
            "/api/v1/candidates",
            params={"use_llm": "false"},
            files={"file": ("first.txt", first_cv.encode("utf-8"), "text/plain")},
            headers=headers,
        )
        assert first.status_code == 200, first.text

        second_cv = f"""
        Reupload Candidate
        {candidate_email}
        Skills
        Java, Spring Boot
        Experience
        Built Spring Boot services.
        Projects
        JVM migration.
        """
        second = client.post(
            "/api/v1/candidates",
            params={"use_llm": "false"},
            files={"file": ("second.txt", second_cv.encode("utf-8"), "text/plain")},
            headers=headers,
        )

    assert second.status_code == 200, second.text
    first_body = first.json()
    second_body = second.json()
    assert second_body["candidate_id"] == first_body["candidate_id"]
    assert "java" in second_body["skills"]
    assert "python" not in second_body["skills"]

    candidate, embedding = asyncio.run(_load_candidate(second_body["candidate_id"]))
    assert candidate is not None
    assert "Spring Boot" in candidate.raw_text
    assert "java" in candidate.skills
    assert "python" not in candidate.skills
    assert embedding is not None
