import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal, init_db
from app.core.config import settings
from app.main import create_app
from app.models.candidate import Candidate
from app.models.interview import InterviewSession
from app.models.job import Job
from app.models.user import User
from app.services.auth import hash_password
from app.services.interview import (
    build_grounded_question_items,
    create_interview_session,
    evaluate_interview,
    submit_answer,
)


@pytest.mark.asyncio
async def test_interview_full_flow() -> None:
    """
    Checks that interview full flow.
    """
    await init_db()

    async with SessionLocal() as session:
        job_id = str(uuid.uuid4())
        session.add(Job(
            id=job_id, title="ML Engineer",
            description="ML Engineer with Python and NLP skills.",
            required_skills=["python", "nlp"],
            optional_skills=["docker"], seniority="mid",
        ))
        cand_id = str(uuid.uuid4())
        session.add(Candidate(
            id=cand_id, full_name="Alice", email="alice@test.com",
            phone="+123", skills=["python", "nlp", "machine learning"],
            experience=["ML Engineer"], education=["MSc"],
            projects=["NLP pipeline"],
            raw_text="Alice is an ML engineer with NLP experience.",
        ))
        await session.commit()

        interview, candidate_name, job_title = await create_interview_session(session, job_id, cand_id)
        assert interview.id
        assert candidate_name == "Alice"
        assert len(interview.questions) > 0

        q_id = interview.questions[0]["id"]
        result = await submit_answer(
            session, interview.id, q_id,
            "I have extensive experience with these concepts. I've built several production systems.",
        )
        assert result.score > 0
        assert result.feedback

        eval_result = await evaluate_interview(session, interview.id)
        assert eval_result["overall_score"] > 0
        assert "strengths" in eval_result
        assert "weaknesses" in eval_result


def test_public_interview_answer_and_evaluate_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Checks that public interview answer and evaluate flow.
    """
    import asyncio
    from app.services.enhanced_interview import EnhancedInterviewService

    async def _fail_if_llm_is_used(*args, **kwargs):
        """
        Fails the test if the LLM path is called unexpectedly.
        """
        raise AssertionError("Public answer save should not wait for LLM evaluation")

    monkeypatch.setattr(EnhancedInterviewService, "evaluate_answer_with_llm", _fail_if_llm_is_used)

    async def _seed() -> tuple[str, list[str]]:
        """
        Seeds database rows used by the surrounding test.
        """
        await init_db()
        async with SessionLocal() as session:
            job_id = str(uuid.uuid4())
            candidate_id = str(uuid.uuid4())
            session_id = str(uuid.uuid4())
            question_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

            session.add(Job(
                id=job_id,
                title="Backend Engineer",
                description="Backend engineer with Python skills.",
                required_skills=["python"],
                optional_skills=[],
                seniority="mid",
            ))
            session.add(Candidate(
                id=candidate_id,
                full_name="Public Candidate",
                email="public-candidate@test.com",
                phone="+123",
                skills=["python"],
                experience=["Backend developer"],
                education=["BSc"],
                projects=["API"],
                raw_text="Python backend developer.",
            ))
            session.add(InterviewSession(
                id=session_id,
                job_id=job_id,
                candidate_id=candidate_id,
                questions=[
                    {
                        "id": question_ids[0],
                        "skill": "python",
                        "question": "Explain how you structure a production Python API.",
                        "difficulty": "mid",
                        "category": "Technical",
                        "expected_answer_hint": "Mention routing, validation, observability, and tests.",
                        "evaluation_criteria": ["Architecture", "Testing"],
                    },
                    {
                        "id": question_ids[1],
                        "skill": "fastapi",
                        "question": "How do you validate requests in FastAPI?",
                        "difficulty": "mid",
                        "category": "Technical",
                    },
                ],
                answers=[],
                evaluations=[],
                chat_history=[],
                status="pending",
            ))
            await session.commit()
            return session_id, question_ids

    async def _load_evaluations(session_id: str) -> list[dict]:
        """
        Loads saved interview evaluations for the surrounding test.
        """
        async with SessionLocal() as session:
            interview = await session.get(InterviewSession, session_id)
            assert interview is not None
            return list(interview.evaluations or [])

    session_id, question_ids = asyncio.run(_seed())
    app = create_app()
    with TestClient(app) as client:
        initial_public_resp = client.get(f"/api/v1/interviews/public/{session_id}")
        assert initial_public_resp.status_code == 200
        first_public_question = initial_public_resp.json()["questions"][0]
        assert first_public_question["id"] == question_ids[0]
        assert "expected_answer_hint" not in first_public_question
        assert "evaluation_criteria" not in first_public_question

        answer_resp = client.post(
            f"/api/v1/interviews/public/{session_id}/answer",
            json={
                "question_id": question_ids[0],
                "answer": "I structure production APIs with routing, validation, tests, observability, and clear service boundaries.",
            },
        )
        assert answer_resp.status_code == 200, answer_resp.text
        assert answer_resp.json()["question_id"] == question_ids[0]
        assert answer_resp.json()["evaluation_status"] == "quick"
        assert answer_resp.json()["using_llm"] is False
        assert answer_resp.json()["next_question"]["id"] == question_ids[1]
        stored_evaluations = asyncio.run(_load_evaluations(session_id))
        assert stored_evaluations[0]["using_llm"] is False
        assert stored_evaluations[0]["evaluation_status"] == "quick"

        resumed_public_resp = client.get(f"/api/v1/interviews/public/{session_id}")
        assert resumed_public_resp.status_code == 200
        resumed_data = resumed_public_resp.json()
        assert [q["id"] for q in resumed_data["questions"]] == question_ids
        assert resumed_data["answered_question_ids"] == [question_ids[0]]
        assert resumed_data["current_question_id"] == question_ids[1]

        second_answer_resp = client.post(
            f"/api/v1/interviews/public/{session_id}/answer",
            json={
                "question_id": question_ids[1],
                "answer": "I use Pydantic schemas, type hints, dependency validation, and error handling for request validation.",
            },
        )
        assert second_answer_resp.status_code == 200, second_answer_resp.text
        assert second_answer_resp.json()["question_id"] == question_ids[1]

        eval_resp = client.post(f"/api/v1/interviews/public/{session_id}/evaluate")
        assert eval_resp.status_code == 200, eval_resp.text
        assert eval_resp.json()["overall_score"] > 0
        assert eval_resp.json()["answered_questions"] == 2

        public_resp = client.get(f"/api/v1/interviews/public/{session_id}")
        assert public_resp.status_code == 200
        public_data = public_resp.json()
        assert public_data["is_completed"] is True
        assert "overall_score" in public_data
        assert public_data["analysis_status"] == "queued"
        assert public_data["evaluation_status"] == "provisional"


def test_staff_start_interview_does_not_return_questions() -> None:
    """
    Checks that staff start interview does not return questions.
    """
    import asyncio

    async def _seed() -> tuple[str, str, str, str]:
        """
        Seeds database rows used by the surrounding test.
        """
        await init_db()
        email = f"staff-interview-{uuid.uuid4().hex[:8]}@example.com"
        password = "password123"
        async with SessionLocal() as session:
            job_id = str(uuid.uuid4())
            candidate_id = str(uuid.uuid4())
            session.add(User(
                id=str(uuid.uuid4()),
                email=email,
                password_hash=hash_password(password),
                full_name="Staff User",
                role="recruiter",
            ))
            session.add(Job(
                id=job_id,
                title="Backend Engineer",
                description="Backend engineer with Python skills.",
                required_skills=["python"],
                optional_skills=[],
                seniority="mid",
            ))
            session.add(Candidate(
                id=candidate_id,
                full_name="Hidden Question Candidate",
                email=f"hidden-question-{uuid.uuid4().hex[:8]}@test.com",
                phone="+123",
                skills=["python"],
                experience=["Backend developer"],
                education=["BSc"],
                projects=["API"],
                raw_text="Python backend developer.",
            ))
            await session.commit()
            return email, password, job_id, candidate_id

    email, password, job_id, candidate_id = asyncio.run(_seed())
    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        token = login.json()["access_token"]
        response = client.post(
            "/api/v1/interviews/start",
            params={"use_llm": "false"},
            json={"job_id": job_id, "candidate_id": candidate_id},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["questions"] == []


def test_authenticated_answer_save_does_not_wait_for_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Checks that authenticated answer save does not wait for LLM.
    """
    import asyncio
    from app.services.enhanced_interview import EnhancedInterviewService

    async def _fail_if_llm_is_used(*args, **kwargs):
        """
        Fails the test if the LLM path is called unexpectedly.
        """
        raise AssertionError("Authenticated answer save should not wait for LLM evaluation")

    monkeypatch.setattr(EnhancedInterviewService, "evaluate_answer_with_llm", _fail_if_llm_is_used)

    async def _seed() -> tuple[str, str, str, str]:
        """
        Seeds database rows used by the surrounding test.
        """
        await init_db()
        email = f"answer-candidate-{uuid.uuid4().hex[:8]}@example.com"
        password = "password123"
        async with SessionLocal() as session:
            job_id = str(uuid.uuid4())
            candidate_id = str(uuid.uuid4())
            session_id = str(uuid.uuid4())
            question_id = str(uuid.uuid4())

            session.add(User(
                id=str(uuid.uuid4()),
                email=email,
                password_hash=hash_password(password),
                full_name="Answer Candidate",
                role="candidate",
            ))
            session.add(Job(
                id=job_id,
                title="Backend Engineer",
                description="Backend engineer with Python skills.",
                required_skills=["python"],
                optional_skills=[],
                seniority="mid",
            ))
            session.add(Candidate(
                id=candidate_id,
                full_name="Answer Candidate",
                email=email,
                phone="+123",
                skills=["python"],
                experience=["Backend developer"],
                education=["BSc"],
                projects=["API"],
                raw_text="Python backend developer.",
            ))
            session.add(InterviewSession(
                id=session_id,
                job_id=job_id,
                candidate_id=candidate_id,
                questions=[{
                    "id": question_id,
                    "skill": "python",
                    "question": "Explain how you debug a production Python issue.",
                    "difficulty": "mid",
                    "category": "Technical",
                }],
                answers=[],
                evaluations=[],
                chat_history=[],
                status="pending",
            ))
            await session.commit()
            return email, password, session_id, question_id

    async def _load_evaluations(session_id: str) -> list[dict]:
        """
        Loads saved interview evaluations for the surrounding test.
        """
        async with SessionLocal() as session:
            interview = await session.get(InterviewSession, session_id)
            assert interview is not None
            return list(interview.evaluations or [])

    email, password, session_id, question_id = asyncio.run(_seed())
    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        token = login.json()["access_token"]
        response = client.post(
            "/api/v1/interviews/answer",
            json={
                "session_id": session_id,
                "question_id": question_id,
                "answer": "I inspect logs, metrics, traces, and tests before shipping a targeted fix.",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    stored_evaluations = asyncio.run(_load_evaluations(session_id))
    assert stored_evaluations[0]["using_llm"] is False
    assert stored_evaluations[0]["evaluation_status"] == "quick"


def test_chat_answer_save_does_not_wait_for_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Checks that chat answer save does not wait for LLM.
    """
    import asyncio
    from app.services.enhanced_interview import EnhancedInterviewService

    async def _fail_if_llm_is_used(*args, **kwargs):
        """
        Fails the test if the LLM path is called unexpectedly.
        """
        raise AssertionError("Chat answer save should not wait for LLM evaluation")

    monkeypatch.setattr(EnhancedInterviewService, "evaluate_answer_with_llm", _fail_if_llm_is_used)

    async def _seed() -> tuple[str, str, str, str]:
        """
        Seeds database rows used by the surrounding test.
        """
        await init_db()
        email = f"chat-candidate-{uuid.uuid4().hex[:8]}@example.com"
        password = "password123"
        async with SessionLocal() as session:
            job_id = str(uuid.uuid4())
            candidate_id = str(uuid.uuid4())
            session_id = str(uuid.uuid4())
            question_id = str(uuid.uuid4())

            session.add(User(
                id=str(uuid.uuid4()),
                email=email,
                password_hash=hash_password(password),
                full_name="Chat Candidate",
                role="candidate",
            ))
            session.add(Job(
                id=job_id,
                title="Chat Engineer",
                description="Python API engineer.",
                required_skills=["python"],
                optional_skills=[],
                seniority="mid",
            ))
            session.add(Candidate(
                id=candidate_id,
                full_name="Chat Candidate",
                email=email,
                phone="+123",
                skills=["python"],
                experience=["Backend developer"],
                education=["BSc"],
                projects=["API"],
                raw_text="Python backend developer.",
            ))
            session.add(InterviewSession(
                id=session_id,
                job_id=job_id,
                candidate_id=candidate_id,
                questions=[{
                    "id": question_id,
                    "skill": "python",
                    "question": "How do you keep API services reliable?",
                    "difficulty": "mid",
                    "category": "Technical",
                }],
                answers=[],
                evaluations=[],
                chat_history=[],
                status="pending",
            ))
            await session.commit()
            return email, password, session_id, question_id

    email, password, session_id, question_id = asyncio.run(_seed())
    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        token = login.json()["access_token"]
        response = client.post(
            "/api/v1/interviews/chat-answer",
            json={
                "session_id": session_id,
                "question_id": question_id,
                "answer": "I use health checks, observability, tests, rollback plans, and measured deployments.",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["using_llm"] is False
    assert data["evaluation_status"] == "quick"


def test_completed_background_fallback_analysis_is_ready() -> None:
    """
    Checks that completed background fallback analysis is ready.
    """
    from app.api.interviews import _analysis_status

    interview = InterviewSession(
        id=str(uuid.uuid4()),
        job_id=str(uuid.uuid4()),
        candidate_id=str(uuid.uuid4()),
        questions=[{"id": str(uuid.uuid4()), "question": "Question?", "skill": "python"}],
        answers=["Answer"],
        evaluations=[{
            "question_id": str(uuid.uuid4()),
            "score": 0.5,
            "feedback": "Fallback complete.",
            "using_llm": False,
            "evaluation_status": "completed",
        }],
        chat_history=[],
        status="evaluated",
    )

    assert _analysis_status(interview) == "ready"


def test_invite_reports_email_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Checks that invite reports email configuration error.
    """
    import asyncio

    monkeypatch.setattr(settings, "smtp_host", "smtp.gmail.com")
    monkeypatch.setattr(settings, "smtp_username", "")
    monkeypatch.setattr(settings, "smtp_password", "")

    async def _seed() -> tuple[str, str, str, str, str]:
        """
        Seeds database rows used by the surrounding test.
        """
        await init_db()
        recruiter_email = f"invite-recruiter-{uuid.uuid4().hex[:8]}@example.com"
        candidate_email = f"invite-candidate-{uuid.uuid4().hex[:8]}@example.com"
        password = "password123"
        async with SessionLocal() as session:
            job_id = str(uuid.uuid4())
            candidate_id = str(uuid.uuid4())
            session.add(User(
                id=str(uuid.uuid4()),
                email=recruiter_email,
                password_hash=hash_password(password),
                full_name="Invite Recruiter",
                role="recruiter",
            ))
            session.add(Job(
                id=job_id,
                title="AI Engineer",
                description="AI engineer with NLP skills.",
                required_skills=["nlp"],
                optional_skills=[],
                seniority="mid",
            ))
            session.add(Candidate(
                id=candidate_id,
                full_name="Invite Candidate",
                email=candidate_email,
                phone="+123",
                skills=["nlp"],
                experience=["Built NLP systems"],
                education=["BSc"],
                projects=["NLP API"],
                raw_text="NLP engineer.",
            ))
            await session.commit()
            return recruiter_email, password, job_id, candidate_id, candidate_email

    recruiter_email, password, job_id, candidate_id, candidate_email = asyncio.run(_seed())
    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": recruiter_email, "password": password})
        token = login.json()["access_token"]
        response = client.post(
            "/api/v1/interviews/invite",
            json={"job_id": job_id, "candidate_id": candidate_id},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["email_sent"] is False
    assert data["email_to"] == candidate_email
    assert "SMTP_USERNAME" in data["email_error"]
    assert data["total_questions"] == 1


def test_interview_websocket_live_chat_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Checks that interview websocket live chat flow.
    """
    import asyncio
    from app.services.enhanced_interview import EnhancedInterviewService

    async def _fail_if_llm_is_used(*args, **kwargs):
        """
        Fails the test if the LLM path is called unexpectedly.
        """
        raise AssertionError("WebSocket answer save should not wait for LLM evaluation")

    monkeypatch.setattr(EnhancedInterviewService, "evaluate_answer_with_llm", _fail_if_llm_is_used)

    async def _seed() -> tuple[str, str]:
        """
        Seeds database rows used by the surrounding test.
        """
        await init_db()
        async with SessionLocal() as session:
            job_id = str(uuid.uuid4())
            candidate_id = str(uuid.uuid4())
            session_id = str(uuid.uuid4())
            question_id = str(uuid.uuid4())

            session.add(Job(
                id=job_id,
                title="Live Interview Engineer",
                description="Python API engineer.",
                required_skills=["python"],
                optional_skills=[],
                seniority="mid",
            ))
            session.add(Candidate(
                id=candidate_id,
                full_name="Live Candidate",
                email="live-candidate@test.com",
                phone="+123",
                skills=["python"],
                experience=["Backend developer"],
                education=["BSc"],
                projects=["API"],
                raw_text="Python developer.",
            ))
            session.add(InterviewSession(
                id=session_id,
                job_id=job_id,
                candidate_id=candidate_id,
                questions=[{
                    "id": question_id,
                    "skill": "python",
                    "question": "How do you debug a Python production issue?",
                    "difficulty": "mid",
                    "category": "Technical",
                    "expected_answer_hint": "Look for observability, reproduction, and tests.",
                }],
                answers=[],
                evaluations=[],
                chat_history=[],
                status="pending",
            ))
            await session.commit()
            return session_id, question_id

    session_id, question_id = asyncio.run(_seed())
    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/ws/interview/{session_id}") as websocket:
            first_message = websocket.receive_json()
            assert first_message["type"] == "question"
            assert first_message["question_id"] == question_id
            assert "hint" not in first_message

            websocket.send_json({
                "type": "answer",
                "question_id": question_id,
                "answer": "I inspect logs and metrics, reproduce the issue, add focused tests, and deploy a targeted fix.",
            })
            evaluation = websocket.receive_json()
            assert evaluation["type"] == "evaluation"
            assert evaluation["question_id"] == question_id

            complete = websocket.receive_json()
            assert complete["type"] == "complete"
            assert complete["answered"] == 1


@pytest.mark.asyncio
async def test_post_interview_analysis_updates_match_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Checks that post interview analysis updates match result.
    """
    from sqlalchemy import select

    from app.models.match_result import MatchResult
    from app.services.enhanced_interview import EnhancedInterviewService
    from app.services.interview_analysis import analyze_completed_interview_in_session

    await init_db()

    async def _fake_llm_eval(self, question: str, answer: str, skill: str, difficulty: str = "mid") -> dict:
        """
        Provides a fake implementation used by the surrounding test.
        """
        return {
            "score": 0.9,
            "feedback": "Strong answer.",
            "language_detected": "english",
            "strengths": [skill],
            "weaknesses": [],
            "technical_accuracy": 0.9,
            "completeness": 0.9,
            "clarity": 0.9,
            "using_llm": True,
        }

    monkeypatch.setattr(EnhancedInterviewService, "evaluate_answer_with_llm", _fake_llm_eval)

    async with SessionLocal() as session:
        job_id = str(uuid.uuid4())
        candidate_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        question_id = str(uuid.uuid4())

        session.add(Job(
            id=job_id,
            title="Interview Analysis Engineer",
            description="Python engineer.",
            required_skills=["python"],
            optional_skills=[],
            seniority="mid",
        ))
        session.add(Candidate(
            id=candidate_id,
            full_name="Analyzed Candidate",
            email=f"analyzed-{uuid.uuid4().hex[:8]}@test.com",
            phone="+123",
            skills=["python"],
            experience=["Python developer"],
            education=["BSc"],
            projects=["API"],
            raw_text="Python developer",
        ))
        session.add(InterviewSession(
            id=session_id,
            job_id=job_id,
            candidate_id=candidate_id,
            questions=[{
                "id": question_id,
                "skill": "python",
                "question": "How do you build reliable Python services?",
                "difficulty": "mid",
                "category": "Technical",
            }],
            answers=["I use tests, observability, typed boundaries, and safe deployment practices."],
            evaluations=[{
                "question_id": question_id,
                "score": 0.4,
                "feedback": "Quick evaluation.",
                "language_detected": "english",
                "using_llm": False,
            }],
            chat_history=[],
            status="completed",
        ))
        await session.commit()

        await analyze_completed_interview_in_session(session, session_id)

        refreshed = await session.get(InterviewSession, session_id)
        assert refreshed is not None
        assert refreshed.status == "evaluated"
        assert refreshed.evaluations[0]["using_llm"] is True
        assert refreshed.evaluations[0]["score"] == 0.9

        match_result = await session.execute(
            select(MatchResult).where(MatchResult.job_id == job_id, MatchResult.candidate_id == candidate_id)
        )
        match = match_result.scalar_one_or_none()
        assert match is not None
        assert match.reasoning["interview_score"] == 0.9
        assert match.reasoning["interview_analysis_status"] == "ready"
        first_score = match.score

        await analyze_completed_interview_in_session(session, session_id)
        match_result = await session.execute(
            select(MatchResult).where(MatchResult.job_id == job_id, MatchResult.candidate_id == candidate_id)
        )
        match = match_result.scalar_one()
        assert match.score == first_score


def test_interview_questions_do_not_treat_learning_context_as_cv_evidence() -> None:
    """
    Checks that interview questions do not treat learning context as CV evidence.
    """
    job = Job(
        id=str(uuid.uuid4()),
        title="Platform Engineer",
        description="Platform engineer with Docker.",
        required_skills=["docker"],
        optional_skills=[],
        seniority="mid",
    )
    candidate = Candidate(
        id=str(uuid.uuid4()),
        full_name="Learning Candidate",
        email=f"learning-interview-{uuid.uuid4().hex[:8]}@test.com",
        phone="+123",
        skills=[],
        skills_detailed=[{
            "name": "docker",
            "status": "learning",
            "context": "I am currently learning Docker.",
        }],
        experience=["Backend engineer"],
        education=["BSc"],
        projects=[],
        raw_text="Backend engineer. I am currently learning Docker.",
    )

    questions = build_grounded_question_items(candidate, job, limit=1)

    assert questions
    assert "was not found in the parsed CV" in questions[0].question
