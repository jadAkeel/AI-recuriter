import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal, init_db
from app.api.candidates import _candidate_display_skills as candidate_api_display_skills
from app.main import create_app
from app.models.candidate import Candidate
from app.models.embedding import Embedding
from app.models.job import Job
from app.models.match_result import MatchResult
from app.models.user import User
from app.api.matching import _candidate_display_skills as matching_api_display_skills, _filter_candidates
from app.services.auth import hash_password
from app.services.embedding import HashEmbeddingService
from app.services.hybrid_matcher import (
    HybridMatchingEngine,
    compute_seniority_score,
    required_skill_score_cap_from_coverage,
)
from app.services.matching import rank_candidates
from app.services.skill_catalog import normalize_skill_name
from app.services.vector_store import VectorStore


def test_skill_normalization_handles_common_problem_solving_typo() -> None:
    """
    Checks that skill normalization handles common problem solving typo.
    """
    assert normalize_skill_name("porble solving") == "problem solving"


def test_required_skill_score_cap_uses_continuous_coverage() -> None:
    """
    Checks that required-skill coverage applies a smooth score cap.
    """
    assert required_skill_score_cap_from_coverage(0.0, True) == pytest.approx(0.30)
    assert required_skill_score_cap_from_coverage(0.4, True) == pytest.approx(0.58)
    assert required_skill_score_cap_from_coverage(1.0, True) == pytest.approx(1.0)
    assert required_skill_score_cap_from_coverage(0.4, False) == pytest.approx(1.0)


def test_seniority_overqualification_penalty_is_capped() -> None:
    """
    Checks that overqualified candidates keep a strong seniority score.
    """
    assert compute_seniority_score("junior", 20) == pytest.approx(0.85)


def test_contextless_detailed_skills_are_visible_for_filtering() -> None:
    """
    Checks that detailed skills do not require context to be searchable.
    """
    candidate = Candidate(
        id=str(uuid.uuid4()),
        full_name="Contextless Candidate",
        email="contextless@example.com",
        phone=None,
        skills=[],
        skills_detailed=[
            {"name": "Python", "status": "has_experience", "context": ""},
            {"name": "Docker", "status": "learning", "context": ""},
            {"name": "Scala", "status": "no_experience", "context": ""},
        ],
        experience=[],
        education=[],
        projects=[],
        raw_text="",
    )

    for display_skills in (candidate_api_display_skills(candidate), matching_api_display_skills(candidate)):
        assert "python" in display_skills
        assert "docker" in display_skills
        assert "scala" not in display_skills


@pytest.mark.asyncio
async def test_hybrid_matching_keeps_learning_and_contextless_detailed_skills() -> None:
    """
    Checks that matching uses learning and contextless detailed skills.
    """
    job = Job(
        id=str(uuid.uuid4()),
        title="Platform Engineer",
        description="Needs Python and Docker.",
        required_skills=["python", "docker"],
        optional_skills=[],
        seniority="mid",
    )
    candidate = Candidate(
        id=str(uuid.uuid4()),
        full_name="Learning Candidate",
        email="learning-contextless@example.com",
        phone=None,
        skills=[],
        skills_detailed=[
            {"name": "Python", "status": "has_experience", "context": ""},
            {"name": "Docker", "status": "learning", "context": ""},
        ],
        experience=[],
        education=[],
        projects=[],
        learning_skills=["docker"],
        raw_text="",
    )

    result = await HybridMatchingEngine()._compute_match(job, candidate, semantic_score=0.0)

    assert result is not None
    assert [match.skill for match in result.skill_match.matched_required] == ["python", "docker"]
    assert result.skill_match.required_score == pytest.approx(0.70)


@pytest.mark.asyncio
async def test_junior_project_evidence_supplies_capped_semantic_bonus() -> None:
    """
    Checks that junior project evidence supplies capped semantic bonus.
    """
    job = Job(
        id=str(uuid.uuid4()),
        title="Junior Next.js Developer",
        description="Junior developer building React and Next.js apps.",
        required_skills=["next.js", "react"],
        optional_skills=["postgresql"],
        seniority="junior",
    )
    candidate = Candidate(
        id=str(uuid.uuid4()),
        full_name="Project Candidate",
        email="project@example.com",
        phone=None,
        skills=[],
        experience=[],
        education=[],
        projects=["GitHub portfolio: built a Next.js React dashboard with PostgreSQL data."],
        total_years_experience=None,
        raw_text="",
    )

    result = await HybridMatchingEngine()._compute_match(job, candidate, semantic_score=0.0)

    assert result is not None
    assert result.semantic_score == pytest.approx(0.50)
    assert result.reasoning.score_breakdown["project_semantic_bonus"] == pytest.approx(0.50)
    assert result.reasoning.score_breakdown["raw_semantic"] == 0.0
    assert "Relevant project evidence for junior role" in result.reasoning.strengths


@pytest.mark.asyncio
async def test_project_semantic_bonus_requires_relevant_project_evidence() -> None:
    """
    Checks that project semantic bonus requires relevant project evidence.
    """
    job = Job(
        id=str(uuid.uuid4()),
        title="Junior Next.js Developer",
        description="Junior developer building React and Next.js apps.",
        required_skills=["next.js", "react"],
        optional_skills=["postgresql"],
        seniority="junior",
    )
    candidate = Candidate(
        id=str(uuid.uuid4()),
        full_name="Unrelated Project Candidate",
        email="unrelated-project@example.com",
        phone=None,
        skills=[],
        experience=[],
        education=[],
        projects=["GitHub portfolio: a marketing copywriting website and photography gallery."],
        total_years_experience=None,
        raw_text="",
    )

    result = await HybridMatchingEngine()._compute_match(job, candidate, semantic_score=0.0)

    assert result is not None
    assert result.semantic_score == 0.0
    assert "project_semantic_bonus" not in result.reasoning.score_breakdown


@pytest.mark.asyncio
async def test_project_semantic_bonus_uses_raw_project_section_when_projects_only_store_titles() -> None:
    """
    Checks that project semantic bonus uses raw project section when projects only store
    titles.
    """
    job = Job(
        id=str(uuid.uuid4()),
        title="Junior Next.js Developer",
        description="Junior developer building React and Next.js apps.",
        required_skills=["next.js", "react"],
        optional_skills=["postgresql"],
        seniority="junior",
    )
    candidate = Candidate(
        id=str(uuid.uuid4()),
        full_name="Raw Project Candidate",
        email="raw-project@example.com",
        phone=None,
        skills=[],
        experience=[],
        education=[],
        projects=["[1] Developer Experience Portal"],
        total_years_experience=None,
        raw_text=(
            "PROJECTS\n"
            "[1] Developer Experience Portal\n"
            "Technologies: Go, PostgreSQL, GraphQL, React, Docker\n"
            "Built an internal portal for engineers.\n"
            "TECHNICAL SKILLS\n"
            "Frontend: Next.js\n"
        ),
    )

    result = await HybridMatchingEngine()._compute_match(job, candidate, semantic_score=0.0)

    assert result is not None
    assert result.semantic_score == pytest.approx(0.50)
    assert result.reasoning.score_breakdown["project_semantic_bonus"] == pytest.approx(0.50)


@pytest.mark.asyncio
async def test_project_semantic_bonus_uses_project_context_when_pdf_text_order_is_split() -> None:
    """
    Checks that project semantic bonus uses project context when PDF text order is
    split.
    """
    job = Job(
        id=str(uuid.uuid4()),
        title="AI Engineer",
        description="Junior AI engineer with PyTorch and deep learning.",
        required_skills=["python", "pytorch", "deep learning"],
        optional_skills=[],
        seniority="junior",
    )
    candidate = Candidate(
        id=str(uuid.uuid4()),
        full_name="Split Project Candidate",
        email="split-project@example.com",
        phone=None,
        skills=["python", "pytorch"],
        experience=[],
        education=[],
        projects=[],
        total_years_experience=None,
        raw_text=(
            "PROJ PROJECT EXPERIENCE\n"
            "Machine Learning Project - Heart Disease Prediction\n"
            "Built a decision tree model.\n"
            "PROFESSIONAL SUMMARY\n"
            "Computer Science graduate.\n"
            "Chess Hybrid AI Platform (Full-Stack Project)\n"
            "Built a PyTorch-based policy and value neural network for deep learning move prediction.\n"
        ),
    )

    result = await HybridMatchingEngine()._compute_match(job, candidate, semantic_score=0.0)

    assert result is not None
    assert result.semantic_score == pytest.approx(0.50)
    assert result.reasoning.score_breakdown["project_semantic_bonus"] == pytest.approx(0.50)


@pytest.mark.asyncio
async def test_project_semantic_bonus_is_junior_only() -> None:
    """
    Checks that project semantic bonus is junior only.
    """
    job = Job(
        id=str(uuid.uuid4()),
        title="Mid Next.js Developer",
        description="Mid developer building React and Next.js apps.",
        required_skills=["next.js", "react"],
        optional_skills=["postgresql"],
        seniority="mid",
    )
    candidate = Candidate(
        id=str(uuid.uuid4()),
        full_name="Project Candidate",
        email="project-mid@example.com",
        phone=None,
        skills=[],
        experience=[],
        education=[],
        projects=["GitHub portfolio: built a Next.js React dashboard with PostgreSQL data."],
        total_years_experience=None,
        raw_text="",
    )

    result = await HybridMatchingEngine()._compute_match(job, candidate, semantic_score=0.0)

    assert result is not None
    assert result.semantic_score == 0.0
    assert "project_semantic_bonus" not in result.reasoning.score_breakdown


@pytest.mark.asyncio
async def test_rank_candidates_returns_results() -> None:
    """
    Checks that rank candidates returns results.
    """
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
        results = await rank_candidates(
            session,
            job,
            job_embedding,
            top_k=5,
            candidates=[candidate],
            cross_encoder_top_k=0,
        )

    assert results
    assert results[0].candidate_id == candidate_id


@pytest.mark.asyncio
async def test_python_job_ranks_python_candidate_above_java_candidate() -> None:
    """
    Checks that python job ranks python candidate above java candidate.
    """
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


@pytest.mark.asyncio
async def test_matching_uses_detailed_and_raw_cv_skill_evidence() -> None:
    """
    Checks that matching uses detailed and raw CV skill evidence.
    """
    await init_db()
    async with SessionLocal() as session:
        job = Job(
            id=str(uuid.uuid4()),
            title="AI Engineer",
            description="AI engineer with Python, SQL, deep learning, AWS certification, and vector database experience.",
            required_skills=["python", "sql", "deep learning", "aws certificate", "vector database"],
            optional_skills=["pytorch"],
            seniority="mid",
        )
        candidate = Candidate(
            id=str(uuid.uuid4()),
            full_name="AI Candidate",
            email="ai-candidate@example.com",
            phone="+15550000004",
            skills=["aws", "pytorch", "vector database"],
            skills_detailed=[
                {
                    "name": "python",
                    "status": "learning",
                    "context": "Python (AI/ML/Deep Learning)",
                },
                {
                    "name": "deep learning",
                    "status": "learning",
                    "context": "Python (AI/ML/Deep Learning)",
                },
                {
                    "name": "aws",
                    "status": "has_experience",
                    "context": "AWS Cloud Practitioner Certified (CLF-C02)",
                },
            ],
            experience=["Built a FastAPI backend with SQLAlchemy ORM."],
            education=["Specialized in Python programming and Machine Learning."],
            projects=["Deep learning training pipeline with a vector database."],
            raw_text="Python AI/ML Deep Learning. AWS Cloud Practitioner Certified. SQLAlchemy ORM. Vector database. PyTorch.",
        )
        session.add_all([job, candidate])
        await session.commit()

        results = await rank_candidates(
            session,
            job,
            [0.0] * 384,
            top_k=1,
            candidates=[candidate],
            cross_encoder_top_k=0,
            use_hybrid=True,
        )

    assert results
    reasoning = results[0].reasoning
    assert reasoning["required_score"] == pytest.approx(0.72)
    assert set(reasoning["missing_required"]) == set()
    assert {skill.lower() for skill in reasoning["matched_required"]} == {
        "python",
        "sql",
        "deep learning",
        "aws certificate",
        "vector database",
    }


@pytest.mark.asyncio
async def test_matching_counts_active_learning_as_partial_skill_evidence() -> None:
    """
    Checks that matching gives active learning skills partial credit.
    """
    await init_db()
    async with SessionLocal() as session:
        job = Job(
            id=str(uuid.uuid4()),
            title="Platform Engineer",
            description="Platform engineer with Docker experience.",
            required_skills=["docker"],
            optional_skills=[],
            seniority="mid",
        )
        candidate = Candidate(
            id=str(uuid.uuid4()),
            full_name="Learning Candidate",
            email=f"learning-{uuid.uuid4().hex[:8]}@example.com",
            phone="+15550000005",
            skills=[],
            skills_detailed=[{
                "name": "docker",
                "status": "learning",
                "context": "I want to learn Docker next.",
            }],
            learning_skills=["docker"],
            experience=["Python backend engineer"],
            education=["BSc"],
            projects=["FastAPI service"],
            total_years_experience=4,
            raw_text="Python backend engineer. I want to learn Docker next.",
        )
        session.add_all([job, candidate])
        await session.commit()

        results = await rank_candidates(
            session,
            job,
            [0.0] * 384,
            top_k=1,
            candidates=[candidate],
            cross_encoder_top_k=0,
            use_hybrid=True,
        )

    assert results
    reasoning = results[0].reasoning
    assert reasoning["required_score"] == pytest.approx(0.60)
    assert reasoning["matched_required"] == ["docker"]
    assert reasoning["missing_required"] == []


@pytest.mark.asyncio
async def test_skill_filter_uses_exact_normalized_skill_names() -> None:
    """
    Checks that skill filter uses exact normalized skill names.
    """
    await init_db()
    async with SessionLocal() as session:
        cpp_candidate = Candidate(
            id=str(uuid.uuid4()),
            full_name="Cpp Candidate",
            email=f"cpp-{uuid.uuid4().hex[:8]}@example.com",
            phone="+15550000006",
            skills=["c++"],
            experience=[],
            education=[],
            projects=[],
            raw_text="C++ developer.",
        )
        c_candidate = Candidate(
            id=str(uuid.uuid4()),
            full_name="C Candidate",
            email=f"c-{uuid.uuid4().hex[:8]}@example.com",
            phone="+15550000007",
            skills=["c"],
            experience=[],
            education=[],
            projects=[],
            raw_text="C developer.",
        )
        session.add_all([cpp_candidate, c_candidate])
        await session.commit()

        filtered = await _filter_candidates(session, skills="c", skill_logic="and")

    assert [candidate.id for candidate in filtered] == [c_candidate.id]


@pytest.mark.asyncio
async def test_filtered_match_run_preserves_existing_match_rows() -> None:
    """
    Checks that filtered match run preserves existing match rows.
    """
    from sqlalchemy import select

    await init_db()
    async with SessionLocal() as session:
        job = Job(
            id=str(uuid.uuid4()),
            title="Backend Engineer",
            description="Backend engineer with Python and SQL.",
            required_skills=["python"],
            optional_skills=["sql"],
            seniority="mid",
        )
        kept = Candidate(
            id=str(uuid.uuid4()),
            full_name="Kept Candidate",
            email=f"kept-{uuid.uuid4().hex[:8]}@example.com",
            phone="+1",
            skills=["python"],
            experience=["Backend"],
            education=["BSc"],
            projects=[],
            raw_text="Python backend engineer.",
        )
        untouched = Candidate(
            id=str(uuid.uuid4()),
            full_name="Untouched Candidate",
            email=f"untouched-{uuid.uuid4().hex[:8]}@example.com",
            phone="+2",
            skills=["python", "sql"],
            experience=["Backend"],
            education=["BSc"],
            projects=[],
            raw_text="Python SQL backend engineer.",
        )
        session.add_all([job, kept, untouched])
        await session.commit()

        await rank_candidates(
            session,
            job,
            [0.0] * 384,
            top_k=2,
            candidates=[kept, untouched],
            cross_encoder_top_k=0,
            use_hybrid=True,
        )
        await rank_candidates(
            session,
            job,
            [0.0] * 384,
            top_k=1,
            candidates=[kept],
            cross_encoder_top_k=0,
            use_hybrid=True,
        )

        result = await session.execute(select(MatchResult).where(MatchResult.job_id == job.id))
        candidate_ids = {match.candidate_id for match in result.scalars().all()}

    assert kept.id in candidate_ids
    assert untouched.id in candidate_ids


@pytest.mark.asyncio
async def test_cached_candidate_embedding_requires_matching_source_metadata() -> None:
    """
    Checks that cached candidate embedding requires matching source metadata.
    """
    await init_db()
    async with SessionLocal() as session:
        candidate = Candidate(
            id=str(uuid.uuid4()),
            full_name="Stale Vector Candidate",
            email=f"stale-vector-{uuid.uuid4().hex[:8]}@example.com",
            phone="+1",
            skills=["python"],
            experience=["Backend"],
            education=["BSc"],
            projects=[],
            raw_text="Python backend engineer.",
        )
        session.add(candidate)
        session.add(Embedding(
            entity_type="candidate",
            entity_id=candidate.id,
            provider="hash",
            model_name="hash",
            source_hash="not-the-current-source",
            embedding_json=[1.0] + [0.0] * 383,
            embedding_vector=[1.0] + [0.0] * 383,
        ))
        await session.commit()

        cached = await HybridMatchingEngine()._get_cached_embedding(VectorStore(session), candidate)

    assert cached is None


def test_matching_api_returns_candidate_details() -> None:
    """
    Checks that matching API returns candidate details.
    """
    import asyncio

    async def _seed() -> tuple[str, str, dict[str, str]]:
        """
        Seeds database rows used by the surrounding test.
        """
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
            return job.id, candidate.id, {"email": user.email, "password": "password123"}

    job_id, candidate_id, credentials = asyncio.run(_seed())
    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json=credentials)
        token = login.json()["access_token"]
        response = client.post(
            f"/api/v1/jobs/{job_id}/match",
            params={"cross_encoder_top_k": 0, "top_k": 100},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    results = response.json()["results"]
    visible = next(item for item in results if item["candidate_id"] == candidate_id)
    assert visible["candidate_name"] == "Visible Candidate"
    assert visible["candidate_email"] == "visible@example.com"
    assert "python" in visible["candidate_skills"]
    assert visible["reasoning"]["scoring_formula"]
    assert visible["reasoning"]["score_contributions"]


def test_saved_matches_api_returns_persisted_results() -> None:
    """
    Checks that saved matches API returns persisted results.
    """
    import asyncio

    async def _seed() -> tuple[str, str, dict[str, str]]:
        """
        Seeds database rows used by the surrounding test.
        """
        await init_db()
        async with SessionLocal() as session:
            user = User(
                id=str(uuid.uuid4()),
                email=f"recruiter-saved-match-{uuid.uuid4().hex[:8]}@example.com",
                password_hash=hash_password("password123"),
                full_name="Recruiter Saved Match",
                role="recruiter",
            )
            job = Job(
                id=str(uuid.uuid4()),
                title="Saved FastAPI Engineer",
                description="FastAPI engineer with Python and PostgreSQL.",
                required_skills=["python", "fastapi", "postgresql"],
                optional_skills=["docker"],
                seniority="mid",
            )
            candidate = Candidate(
                id=str(uuid.uuid4()),
                full_name="Saved Candidate",
                email=f"saved-candidate-{uuid.uuid4().hex[:8]}@example.com",
                phone="+15550000008",
                skills=["python", "fastapi", "postgresql", "docker"],
                experience=["Backend Engineer"],
                education=["BSc"],
                projects=["API"],
                total_years_experience=4,
                raw_text="Python FastAPI PostgreSQL Docker",
            )
            session.add_all([user, job, candidate])
            await session.commit()
            return job.id, candidate.id, {"email": user.email, "password": "password123"}

    job_id, candidate_id, credentials = asyncio.run(_seed())
    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json=credentials)
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        match_response = client.post(
            f"/api/v1/jobs/{job_id}/match",
            params={"cross_encoder_top_k": 0, "top_k": 100},
            headers=headers,
        )
        saved_response = client.get(
            f"/api/v1/jobs/{job_id}/matches",
            headers=headers,
        )

    assert match_response.status_code == 200, match_response.text
    assert saved_response.status_code == 200, saved_response.text
    saved_results = saved_response.json()["results"]
    saved = next(item for item in saved_results if item["candidate_id"] == candidate_id)
    assert saved["candidate_name"] == "Saved Candidate"
    assert saved["candidate_email"].startswith("saved-candidate-")
    assert "python" in saved["candidate_skills"]


def test_saved_matches_api_refreshes_stale_scores() -> None:
    """
    Checks that saved matches API refreshes stale scores.
    """
    import asyncio

    async def _seed() -> tuple[str, str, dict[str, str]]:
        """
        Seeds database rows used by the surrounding test.
        """
        await init_db()
        async with SessionLocal() as session:
            user = User(
                id=str(uuid.uuid4()),
                email=f"recruiter-stale-match-{uuid.uuid4().hex[:8]}@example.com",
                password_hash=hash_password("password123"),
                full_name="Recruiter Stale Match",
                role="recruiter",
            )
            job = Job(
                id=str(uuid.uuid4()),
                title="Stale Python Engineer",
                description="Python engineer.",
                required_skills=["python"],
                optional_skills=[],
                seniority="mid",
            )
            candidate = Candidate(
                id=str(uuid.uuid4()),
                full_name="Stale Score Candidate",
                email=f"stale-score-{uuid.uuid4().hex[:8]}@example.com",
                phone="+15550000009",
                skills=["python"],
                experience=["Built Python services."],
                education=["BSc"],
                projects=[],
                raw_text="Python service experience.",
            )
            session.add_all([user, job, candidate])
            session.add(MatchResult(
                job_id=job.id,
                candidate_id=candidate.id,
                score=0.1,
                reasoning={"scoring_model": "hybrid", "semantic_score": 0.0},
            ))
            await session.commit()
            return job.id, candidate.id, {"email": user.email, "password": "password123"}

    job_id, candidate_id, credentials = asyncio.run(_seed())
    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json=credentials)
        token = login.json()["access_token"]
        saved_response = client.get(
            f"/api/v1/jobs/{job_id}/matches",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert saved_response.status_code == 200, saved_response.text
    saved = next(item for item in saved_response.json()["results"] if item["candidate_id"] == candidate_id)
    assert saved["score"] == 0.575
    assert saved["reasoning"]["scoring_model"] == "hybrid_v2"
    assert saved["reasoning"]["score_trace"]["refreshed_from_stale_match"] is True
