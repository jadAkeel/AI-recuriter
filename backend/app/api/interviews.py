from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.deps import ensure_candidate_access, require_any_role
from app.core.config import settings
from app.models.interview import InterviewSession
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.user import User
from app.schemas.interview import (
    AnswerRequest,
    AnswerResponse,
    EvaluateRequest,
    InterviewSessionStatus,
    QuestionItem,
    StartInterviewRequest,
    StartInterviewResponse,
)
from app.services.enhanced_interview import (
    get_enhanced_interview_service,
    get_simple_interview_service,
)

logger = logging.getLogger(__name__)

router = APIRouter()
STAFF_ROLES = {"owner", "admin", "recruiter"}


class ChatAnswerRequest(BaseModel):
    session_id: str
    question_id: str
    answer: str


class PublicAnswerRequest(BaseModel):
    question_id: str
    answer: str


class InviteResponse(BaseModel):
    session_id: str
    candidate_name: str | None = None
    job_title: str | None = None
    email_sent: bool
    email_to: str | None = None
    email_error: str | None = None
    interview_link: str
    status: str
    total_questions: int


class ChatAnswerResponse(BaseModel):
    question_id: str
    skill: str
    question: str
    answer: str
    score: float
    feedback: str
    language_detected: str
    strengths: list[str]
    weaknesses: list[str]
    using_llm: bool
    next_question: QuestionItem | None = None


class FollowupRequest(BaseModel):
    session_id: str
    question_id: str
    answer: str
    score: float
    question: str | None = None
    skill: str | None = None


class FollowupResponse(BaseModel):
    followup_question: str
    reason: str
    expected_topic: str


class EnhancedEvaluateResponse(BaseModel):
    session_id: str
    overall_score: float
    skill_scores: dict[str, float]
    feedback: str
    strengths: list[str]
    weaknesses: list[str]
    languages_used: list[str]
    total_questions: int
    answered_questions: int


async def _get_interview_or_404(db_session: AsyncSession, session_id: str) -> InterviewSession:
    stmt = select(InterviewSession).where(InterviewSession.id == session_id)
    result = await db_session.execute(stmt)
    interview = result.scalar_one_or_none()
    if interview is None:
        raise HTTPException(status_code=404, detail="Interview session not found")
    return interview


async def _ensure_interview_access(
    db_session: AsyncSession,
    current_user: User,
    session_id: str,
) -> InterviewSession:
    interview = await _get_interview_or_404(db_session, session_id)
    await ensure_candidate_access(db_session, current_user, interview.candidate_id)
    return interview


def _candidate_question_item(question: dict) -> QuestionItem:
    return QuestionItem(
        id=question["id"],
        skill=question.get("skill", "general"),
        question=question["question"],
        difficulty=question.get("difficulty", "medium"),
        category=question.get("category", "Technical"),
    )


def _candidate_question_items(questions: list[dict]) -> list[QuestionItem]:
    return [_candidate_question_item(q) for q in questions]


def _questions_for_user(current_user: User, questions: list[dict]) -> list[QuestionItem]:
    if current_user.role.lower() in STAFF_ROLES:
        return []
    return _candidate_question_items(questions)


def _public_question_payload(question: dict) -> dict:
    return _candidate_question_item(question).model_dump(
        exclude={"expected_answer_hint", "evaluation_criteria", "tags"},
        exclude_none=True,
    )


def _public_evaluation_payload(interview: InterviewSession) -> dict:
    evaluations = interview.evaluations or []
    questions = [QuestionItem(**q) for q in (interview.questions or [])]
    scores = [e.get("score", 0) for e in evaluations]
    overall_score = round(sum(scores) / len(scores), 4) if scores else 0

    skill_scores: dict[str, list[float]] = {}
    for question, evaluation in zip(questions, evaluations):
        skill_scores.setdefault(question.skill, []).append(evaluation.get("score", 0))
    skill_avgs = {skill: round(sum(values) / len(values), 4) for skill, values in skill_scores.items()}

    strengths = sorted([skill for skill, score in skill_avgs.items() if score >= 0.7])
    weaknesses = sorted([skill for skill, score in skill_avgs.items() if score < 0.5])

    return {
        "session_id": interview.id,
        "status": interview.status,
        "is_completed": True,
        "overall_score": overall_score,
        "skill_scores": skill_avgs,
        "feedback": "Interview complete.",
        "strengths": strengths,
        "weaknesses": weaknesses,
        "total_questions": len(questions),
        "answered_questions": len(interview.answers or []),
    }


def _interview_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    if "not found" in message.lower():
        return HTTPException(status_code=404, detail=message)
    if "completed" in message.lower() or "current question" in message.lower():
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return HTTPException(status_code=400, detail=message)


def _email_configuration_error() -> str | None:
    if not settings.smtp_host:
        return "SMTP is not configured. Set SMTP_HOST, SMTP_USERNAME, and SMTP_PASSWORD in backend/.env."
    if not settings.smtp_username:
        return "SMTP_USERNAME is missing in backend/.env."
    if not settings.smtp_password:
        return "SMTP_PASSWORD is missing in backend/.env. For Gmail, use a 16-character Google App Password."
    return None


@router.post("/interviews/start", response_model=StartInterviewResponse)
async def start_interview(
    request: StartInterviewRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
    use_llm: bool = Query(
        default=True,
        description="Use LLM for intelligent answer evaluation (supports Arabic + English)",
    ),
) -> StartInterviewResponse:
    try:
        await ensure_candidate_access(session, current_user, request.candidate_id)
        interview_service = (
            get_enhanced_interview_service() if use_llm else get_simple_interview_service()
        )
        interview, candidate_name, job_title = await interview_service.create_session(
            session, request.job_id, request.candidate_id
        )
        return StartInterviewResponse(
            session_id=interview.id,
            candidate_name=candidate_name,
            job_title=job_title,
            questions=_questions_for_user(current_user, interview.questions or []),
            status=interview.status,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/interviews/invite", response_model=InviteResponse)
async def invite_candidate(
    request: StartInterviewRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
) -> dict:
    try:
        interview_service = get_enhanced_interview_service()
        interview, candidate_name, job_title = await interview_service.create_session(
            session, request.job_id, request.candidate_id
        )

        cand_stmt = select(Candidate).where(Candidate.id == request.candidate_id)
        cand_result = await session.execute(cand_stmt)
        candidate = cand_result.scalar_one_or_none()

        job_stmt = select(Job).where(Job.id == request.job_id)
        job_result = await session.execute(job_stmt)
        job = job_result.scalar_one_or_none()

        email = candidate.email if candidate else None
        job_title_str = job.title if job else job_title

        email_error = None
        from app.services.email import send_interview_invitation
        if email:
            email_error = _email_configuration_error()
            if email_error:
                email_sent = False
            else:
                email_sent = await send_interview_invitation(
                    to_email=email,
                    candidate_name=candidate_name or "Candidate",
                    job_title=job_title_str or "Position",
                    session_id=interview.id,
                    base_url=settings.app_base_url,
                )
                if not email_sent:
                    email_error = "SMTP send failed. Check Gmail App Password / SMTP settings and backend logs."
        else:
            email_sent = False
            email_error = "Candidate has no email address."

        base_url = settings.app_base_url.rstrip("/")
        interview_link = f"{base_url}/interview/{interview.id}" if base_url else f"/interview/{interview.id}"

        return {
            "session_id": interview.id,
            "candidate_name": candidate_name,
            "job_title": job_title_str,
            "email_sent": email_sent,
            "email_to": email,
            "email_error": email_error,
            "interview_link": interview_link,
            "status": "invited",
            "total_questions": len(interview.questions or []),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/interviews/public/{session_id}")
async def get_public_interview(
    session_id: str,
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    stmt = select(InterviewSession).where(InterviewSession.id == session_id)
    result = await db_session.execute(stmt)
    interview = result.scalar_one_or_none()
    if interview is None:
        raise HTTPException(status_code=404, detail="Interview not found")

    cand_stmt = select(Candidate).where(Candidate.id == interview.candidate_id)
    cand_result = await db_session.execute(cand_stmt)
    candidate = cand_result.scalar_one_or_none()

    job_stmt = select(Job).where(Job.id == interview.job_id)
    job_result = await db_session.execute(job_stmt)
    job = job_result.scalar_one_or_none()

    questions_list = interview.questions or []
    answers_count = len(interview.answers or [])
    is_completed = interview.status in ("completed", "evaluated")
    if is_completed:
        payload = _public_evaluation_payload(interview)
        payload.update({
            "candidate_name": candidate.full_name if candidate else None,
            "job_title": job.title if job else None,
        })
        return payload

    return {
        "session_id": interview.id,
        "candidate_name": candidate.full_name if candidate else None,
        "job_title": job.title if job else None,
        "status": interview.status,
        "is_completed": is_completed,
        "questions": [_public_question_payload(q) for q in questions_list[answers_count:]],
        "total_questions": len(questions_list),
        "answered_count": answers_count,
    }


async def _submit_public_answer(
    session_id: str,
    request: PublicAnswerRequest,
    session: AsyncSession,
) -> ChatAnswerResponse:
    interview = await _get_interview_or_404(session, session_id)
    questions = [QuestionItem(**q) for q in (interview.questions or [])]
    answers_count = len(interview.answers or [])

    if not request.answer.strip():
        raise HTTPException(status_code=400, detail="Answer cannot be empty")
    if answers_count >= len(questions):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Interview already completed")

    expected_question = questions[answers_count]
    if expected_question.id != request.question_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Answer does not match the current question",
        )

    interview_service = get_enhanced_interview_service()
    try:
        result = await interview_service.submit_answer(
            session,
            session_id,
            request.question_id,
            request.answer,
        )
    except ValueError as exc:
        raise _interview_error(exc) from exc

    answers_count = len(interview.answers or [])
    next_question = (
        _candidate_question_item(interview.questions[answers_count])
        if answers_count < len(interview.questions or [])
        else None
    )

    return ChatAnswerResponse(
        question_id=result["question_id"],
        skill=result["skill"],
        question=result.get("question", ""),
        answer=result["answer"],
        score=result["score"],
        feedback=result["feedback"],
        language_detected=result.get("language_detected", "english"),
        strengths=result.get("strengths", []),
        weaknesses=result.get("weaknesses", []),
        using_llm=result.get("using_llm", False),
        next_question=next_question,
    )


@router.post("/interviews/public/{session_id}/answer", response_model=ChatAnswerResponse)
async def public_chat_answer(
    session_id: str,
    request: PublicAnswerRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ChatAnswerResponse:
    return await _submit_public_answer(session_id, request, session)


@router.post("/interviews/public/{session_id}/voice-answer", response_model=ChatAnswerResponse)
async def public_voice_answer(
    session_id: str,
    question_id: str = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
) -> ChatAnswerResponse:
    audio_bytes = await file.read()
    try:
        from app.services.voice_service import get_voice_service

        transcript = await get_voice_service().transcribe_audio(audio_bytes)
    except Exception as exc:
        logger.exception("Voice transcription failed")
        raise HTTPException(status_code=500, detail="Voice transcription failed") from exc

    if not transcript.strip():
        raise HTTPException(status_code=400, detail="Could not transcribe an answer")

    return await _submit_public_answer(
        session_id,
        PublicAnswerRequest(question_id=question_id, answer=transcript),
        session,
    )


@router.post("/interviews/public/{session_id}/evaluate", response_model=EnhancedEvaluateResponse)
async def public_evaluate(
    session_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> EnhancedEvaluateResponse:
    interview = await _get_interview_or_404(session, session_id)
    if len(interview.answers or []) < len(interview.questions or []):
        raise HTTPException(status_code=400, detail="Interview is not complete")

    try:
        interview_service = get_enhanced_interview_service()
        result = await interview_service.evaluate_session(session, session_id)
        return EnhancedEvaluateResponse(**result)
    except ValueError as exc:
        raise _interview_error(exc) from exc


@router.post("/interviews/answer", response_model=AnswerResponse)
async def answer_question(
    request: AnswerRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
    use_llm: bool = Query(
        default=True,
        description="Use LLM for intelligent answer evaluation (supports Arabic + English)",
    ),
) -> AnswerResponse:
    try:
        await _ensure_interview_access(session, current_user, request.session_id)
        interview_service = (
            get_enhanced_interview_service() if use_llm else get_simple_interview_service()
        )
        result = await interview_service.submit_answer(
            session, request.session_id, request.question_id, request.answer
        )
        return AnswerResponse(
            question_id=result["question_id"],
            skill=result["skill"],
            answer=result["answer"],
            score=result["score"],
            feedback=result["feedback"],
        )
    except ValueError as exc:
        raise _interview_error(exc) from exc


@router.post("/interviews/chat-answer", response_model=ChatAnswerResponse)
async def chat_answer(
    request: ChatAnswerRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
) -> ChatAnswerResponse:
    try:
        await _ensure_interview_access(session, current_user, request.session_id)
        interview_service = get_enhanced_interview_service()
        result = await interview_service.submit_answer(
            session, request.session_id, request.question_id, request.answer
        )

        stmt = select(InterviewSession).where(InterviewSession.id == request.session_id)
        db_result = await session.execute(stmt)
        interview = db_result.scalar_one_or_none()

        next_question = None
        if interview:
            questions = [QuestionItem(**q) for q in interview.questions]
            answers_count = len(interview.answers or [])
            if answers_count < len(questions):
                next_question = questions[answers_count]

        return ChatAnswerResponse(
            question_id=result["question_id"],
            skill=result["skill"],
            question=result.get("question", ""),
            answer=result["answer"],
            score=result["score"],
            feedback=result["feedback"],
            language_detected=result.get("language_detected", "english"),
            strengths=result.get("strengths", []),
            weaknesses=result.get("weaknesses", []),
            using_llm=result.get("using_llm", False),
            next_question=next_question,
        )
    except ValueError as exc:
        raise _interview_error(exc) from exc


@router.post("/interviews/followup", response_model=FollowupResponse)
async def get_followup_question(
    request: FollowupRequest,
    current_user: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
    session: AsyncSession = Depends(get_db_session),
    use_llm: bool = Query(default=True),
) -> FollowupResponse:
    try:
        await _ensure_interview_access(session, current_user, request.session_id)
        interview_service = (
            get_enhanced_interview_service() if use_llm else get_simple_interview_service()
        )
        result = await interview_service.generate_followup(
            question=request.question or "",
            answer=request.answer,
            skill=request.skill or "general",
            score=request.score,
        )
        return FollowupResponse(**result)
    except Exception as exc:
        logger.exception("Follow-up generation failed")
        raise HTTPException(status_code=500, detail="Follow-up generation failed") from exc


@router.get("/interviews/{session_id}", response_model=InterviewSessionStatus)
async def get_interview_status(
    session_id: str,
    current_user: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
    db_session: AsyncSession = Depends(get_db_session),
) -> InterviewSessionStatus:
    interview = await _ensure_interview_access(db_session, current_user, session_id)

    scores = [e["score"] for e in (interview.evaluations or [])]
    avg_score = round(sum(scores) / len(scores), 4) if scores else None

    answers_list = interview.answers or []
    questions_list = interview.questions or []
    evaluations_list = interview.evaluations or []
    safe_answers = []
    for i in range(len(answers_list)):
        q = questions_list[i] if i < len(questions_list) else {}
        ev = evaluations_list[i] if i < len(evaluations_list) else {"score": 0, "feedback": ""}
        safe_answers.append(AnswerResponse(
            question_id=q.get("id", ""),
            skill=q.get("skill", ""),
            answer=answers_list[i],
            score=ev.get("score", 0),
            feedback=ev.get("feedback", ""),
        ))

    return InterviewSessionStatus(
        session_id=interview.id,
        job_id=interview.job_id,
        candidate_id=interview.candidate_id,
        status=interview.status,
        answers_count=len(answers_list),
        questions=_questions_for_user(current_user, questions_list),
        answers=safe_answers,
        average_score=avg_score,
    )


@router.post("/interviews/evaluate", response_model=EnhancedEvaluateResponse)
async def evaluate(
    request: EvaluateRequest,
    current_user: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
    session: AsyncSession = Depends(get_db_session),
) -> EnhancedEvaluateResponse:
    try:
        await _ensure_interview_access(session, current_user, request.session_id)
        interview_service = get_enhanced_interview_service()
        result = await interview_service.evaluate_session(session, request.session_id)
        return EnhancedEvaluateResponse(**result)
    except ValueError as exc:
        raise _interview_error(exc) from exc
