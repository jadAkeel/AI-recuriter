from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.deps import ensure_candidate_access, require_any_role
from app.core.config import settings
from app.models.embedding import Embedding
from app.models.interview import InterviewSession
from app.models.match_result import MatchResult
from app.models.report import Report
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
from app.services.hybrid_matcher import (
    HybridMatchingEngine,
    is_current_scoring_reasoning,
    is_interview_blended_reasoning,
    semantic_score_from_reasoning,
)
from app.services.interview_analysis import analyze_completed_interview

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
    evaluation_status: str = "completed"
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


class DashboardInterviewResult(BaseModel):
    session_id: str | None = None
    report_id: str | None = None
    candidate_id: str
    candidate_name: str | None = None
    job_id: str
    job_title: str | None = None
    status: str
    analysis_status: str
    interview_score: float
    match_score: float | None = None
    report_score: float | None = None
    answered_questions: int
    total_questions: int


async def _get_interview_or_404(db_session: AsyncSession, session_id: str) -> InterviewSession:
    """
    Loads an interview session or raises a 404 API error.
    """
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
    """
    Loads an interview and verifies candidate access rules.
    """
    interview = await _get_interview_or_404(db_session, session_id)
    await ensure_candidate_access(db_session, current_user, interview.candidate_id)
    return interview


def _candidate_question_item(question: dict) -> QuestionItem:
    """
    Builds the candidate-safe question item from stored question data.
    """
    return QuestionItem(
        id=question["id"],
        skill=question.get("skill", "general"),
        question=question["question"],
        difficulty=question.get("difficulty", "medium"),
        category=question.get("category", "Technical"),
    )


def _candidate_question_items(questions: list[dict]) -> list[QuestionItem]:
    """
    Builds candidate-safe question items from stored questions.
    """
    return [_candidate_question_item(q) for q in questions]


def _questions_for_user(current_user: User, questions: list[dict]) -> list[QuestionItem]:
    """
    Hides questions from staff until the candidate-facing flow should show them.
    """
    if current_user.role.lower() in STAFF_ROLES:
        return []
    return _candidate_question_items(questions)


def _status_questions_for_user(current_user: User, interview: InterviewSession) -> list[QuestionItem]:
    """
    Returns the question list allowed for the current user and interview status.
    """
    if current_user.role.lower() in STAFF_ROLES:
        is_complete = interview.status in ("completed", "evaluated", "analyzing") or (
            len(interview.answers or []) >= len(interview.questions or []) > 0
        )
        return _candidate_question_items(interview.questions or []) if is_complete else []
    return _candidate_question_items(interview.questions or [])


def _public_question_payload(question: dict) -> dict:
    """
    Builds the public interview question payload without evaluator-only fields.
    """
    return _candidate_question_item(question).model_dump(
        exclude={"expected_answer_hint", "evaluation_criteria", "tags"},
        exclude_none=True,
    )


def _public_evaluation_payload(interview: InterviewSession) -> dict:
    """
    Builds the public completion payload for an interview session.
    """
    evaluations = interview.evaluations or []
    questions = [QuestionItem(**q) for q in (interview.questions or [])]
    scores = [e.get("score", 0) for e in evaluations]
    overall_score = round(sum(scores) / len(scores), 4) if scores else 0
    analysis_status = _analysis_status(interview)

    skill_scores: dict[str, list[float]] = {}
    for question, evaluation in zip(questions, evaluations):
        skill_scores.setdefault(question.skill, []).append(evaluation.get("score", 0))
    skill_avgs = {skill: round(sum(values) / len(values), 4) for skill, values in skill_scores.items()}

    strengths = sorted([skill for skill, score in skill_avgs.items() if score >= 0.7])
    weaknesses = sorted([skill for skill, score in skill_avgs.items() if score < 0.5])

    return {
        "session_id": interview.id,
        "status": interview.status,
        "analysis_status": analysis_status,
        "evaluation_status": "completed" if analysis_status == "ready" else "provisional",
        "is_completed": True,
        "overall_score": overall_score,
        "skill_scores": skill_avgs,
        "feedback": (
            "Interview analysis complete."
            if analysis_status == "ready"
            else "Interview answers are saved; full analysis is still pending."
        ),
        "strengths": strengths,
        "weaknesses": weaknesses,
        "languages_used": sorted({e.get("language_detected", "english") for e in evaluations}),
        "total_questions": len(questions),
        "answered_questions": len(interview.answers or []),
    }


def _answered_question_ids(interview: InterviewSession) -> list[str]:
    """
    Returns IDs for questions that already have saved answers.
    """
    questions = interview.questions or []
    answers_count = len(interview.answers or [])
    return [q.get("id", "") for q in questions[:answers_count] if q.get("id")]


def _interview_error(exc: ValueError) -> HTTPException:
    """
    Maps interview service errors to API HTTP errors.
    """
    message = str(exc)
    if "not found" in message.lower():
        return HTTPException(status_code=404, detail=message)
    if "completed" in message.lower() or "current question" in message.lower():
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return HTTPException(status_code=400, detail=message)


def _email_configuration_error() -> str | None:
    """
    Returns a user-facing SMTP configuration problem when email cannot be sent.
    """
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
        description="Use LLM for intelligent answer evaluation",
    ),
) -> StartInterviewResponse:
    """
    Creates an interview session for a candidate and job.
    """
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
    """
    Creates an interview session and sends the invitation email when configured.
    """
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
    """
    Returns public interview questions or completion results.
    """
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
    is_completed = interview.status in ("completed", "evaluated", "analyzing") or (
        bool(questions_list) and answers_count >= len(questions_list)
    )
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
        "questions": [_public_question_payload(q) for q in questions_list],
        "total_questions": len(questions_list),
        "answered_count": answers_count,
        "answered_question_ids": _answered_question_ids(interview),
        "current_question_id": (
            questions_list[answers_count].get("id")
            if answers_count < len(questions_list)
            else None
        ),
    }


async def _submit_public_answer(
    session_id: str,
    request: PublicAnswerRequest,
    session: AsyncSession,
    background_tasks: BackgroundTasks | None = None,
) -> ChatAnswerResponse:
    """
    Saves a public interview answer and schedules final analysis when complete.
    """
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
            use_llm=False,
        )
    except ValueError as exc:
        raise _interview_error(exc) from exc

    await session.refresh(interview)
    answers_count = len(interview.answers or [])
    next_question = (
        _candidate_question_item(interview.questions[answers_count])
        if answers_count < len(interview.questions or [])
        else None
    )

    if next_question is None and background_tasks is not None:
        background_tasks.add_task(analyze_completed_interview, session_id)

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
        evaluation_status=result.get("evaluation_status", "quick"),
        next_question=next_question,
    )


@router.post("/interviews/public/{session_id}/answer", response_model=ChatAnswerResponse)
async def public_chat_answer(
    session_id: str,
    request: PublicAnswerRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
) -> ChatAnswerResponse:
    """
    Submits a typed answer from the public interview page.
    """
    return await _submit_public_answer(session_id, request, session, background_tasks)


@router.post("/interviews/public/{session_id}/voice-answer", response_model=ChatAnswerResponse)
async def public_voice_answer(
    session_id: str,
    background_tasks: BackgroundTasks,
    question_id: str = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
) -> ChatAnswerResponse:
    """
    Transcribes and submits a voice answer from the public interview page.
    """
    audio_bytes = await file.read()
    if len(audio_bytes) > settings.max_audio_upload_bytes:
        max_mb = settings.max_audio_upload_bytes // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"Audio file is too large. Maximum size is {max_mb}MB.")
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
        background_tasks,
    )


@router.post("/interviews/public/{session_id}/evaluate", response_model=EnhancedEvaluateResponse)
async def public_evaluate(
    session_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> EnhancedEvaluateResponse:
    """
    Returns the public evaluation summary after all answers are complete.
    """
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
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
    use_llm: bool = Query(
        default=False,
        description="Deprecated. Answer saving always uses quick evaluation; full LLM analysis runs in the background.",
    ),
) -> AnswerResponse:
    """
    Saves an authenticated interview answer and schedules background analysis.
    """
    try:
        await _ensure_interview_access(session, current_user, request.session_id)
        interview_service = get_enhanced_interview_service()
        result = await interview_service.submit_answer(
            session, request.session_id, request.question_id, request.answer, use_llm=False
        )
        interview = await _get_interview_or_404(session, request.session_id)
        if len(interview.answers or []) >= len(interview.questions or []):
            background_tasks.add_task(analyze_completed_interview, request.session_id)
        return AnswerResponse(
            question_id=result["question_id"],
            skill=result["skill"],
            answer=result["answer"],
            score=result["score"],
            feedback=result["feedback"],
        )
    except ValueError as exc:
        raise _interview_error(exc) from exc


def _analysis_status(interview: InterviewSession) -> str:
    """
    Reports whether interview analysis is in progress, queued, ready, or incomplete.
    """
    evaluations = interview.evaluations or []
    if interview.status == "analyzing":
        return "analyzing"
    if evaluations and all(
        item.get("evaluation_status") == "completed" or item.get("using_llm")
        for item in evaluations
    ):
        return "ready"
    if len(interview.answers or []) >= len(interview.questions or []):
        return "queued"
    return "in_progress"


def _average_score(evaluations: list[dict]) -> float:
    """
    Calculates the average score from evaluation rows.
    """
    scores = [float(item.get("score", 0)) for item in evaluations if isinstance(item, dict)]
    return round(sum(scores) / len(scores), 4) if scores else 0.0


async def _refresh_stale_dashboard_matches(
    session: AsyncSession,
    matches: list[MatchResult],
    jobs: dict[str, Job],
    candidates: dict[str, Candidate],
) -> None:
    """
    Refreshes dashboard match scores that use outdated scoring logic.
    """
    engine = HybridMatchingEngine()
    refreshed = 0
    for match in matches:
        reasoning = match.reasoning if isinstance(match.reasoning, dict) else {}
        if is_current_scoring_reasoning(reasoning) or is_interview_blended_reasoning(reasoning):
            continue
        job = jobs.get(match.job_id)
        candidate = candidates.get(match.candidate_id)
        if job is None or candidate is None:
            continue
        semantic_score = semantic_score_from_reasoning(reasoning) or 0.0
        current = await engine._compute_match(job, candidate, semantic_score=semantic_score)
        if current is None:
            continue
        current.reasoning.score_trace["source"] = "dashboard_refresh_stale_match"
        current.reasoning.score_trace["previous_scoring_model"] = reasoning.get("scoring_model")
        match.score = current.final_score
        match.reasoning = current.to_dict()
        refreshed += 1
    if refreshed:
        await session.commit()
        logger.info(
            "Refreshed stale dashboard match scores",
            extra={"refreshed_count": refreshed},
        )


@router.get("/interviews/dashboard-results", response_model=list[DashboardInterviewResult])
async def interview_dashboard_results(
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
    session: AsyncSession = Depends(get_db_session),
) -> list[DashboardInterviewResult]:
    """
    Builds recruiter dashboard rows from interviews, reports, and saved matches.
    """
    stmt = select(InterviewSession)
    result = await session.execute(stmt)
    interviews = list(result.scalars().all())
    report_result = await session.execute(select(Report))
    reports = list(report_result.scalars().all())
    match_result = await session.execute(select(MatchResult))
    saved_matches = list(match_result.scalars().all())
    if not interviews and not reports and not saved_matches:
        return []

    candidate_ids = {interview.candidate_id for interview in interviews}
    candidate_ids.update(report.candidate_id for report in reports)
    candidate_ids.update(match.candidate_id for match in saved_matches)
    job_ids = {interview.job_id for interview in interviews}
    job_ids.update(report.job_id for report in reports)
    job_ids.update(match.job_id for match in saved_matches)

    cand_result = await session.execute(select(Candidate).where(Candidate.id.in_(candidate_ids)))
    candidates = {candidate.id: candidate for candidate in cand_result.scalars().all()}

    job_result = await session.execute(select(Job).where(Job.id.in_(job_ids)))
    jobs = {job.id: job for job in job_result.scalars().all()}

    try:
        await _refresh_stale_dashboard_matches(session, saved_matches, jobs, candidates)
    except Exception:
        logger.warning("Dashboard stale match refresh skipped", exc_info=True)
    matches = {(match.job_id, match.candidate_id): match for match in saved_matches}
    reports_by_pair = {(report.job_id, report.candidate_id): report for report in reports}

    rows: list[DashboardInterviewResult] = []
    rendered_pairs: set[tuple[str, str]] = set()
    for interview in interviews:
        answers_count = len(interview.answers or [])
        total_questions = len(interview.questions or [])
        if answers_count == 0:
            continue

        pair = (interview.job_id, interview.candidate_id)
        match = matches.get((interview.job_id, interview.candidate_id))
        report = reports_by_pair.get(pair)
        rows.append(DashboardInterviewResult(
            session_id=interview.id,
            report_id=report.id if report else None,
            candidate_id=interview.candidate_id,
            candidate_name=candidates.get(interview.candidate_id).full_name if interview.candidate_id in candidates else None,
            job_id=interview.job_id,
            job_title=jobs.get(interview.job_id).title if interview.job_id in jobs else None,
            status=interview.status,
            analysis_status=_analysis_status(interview),
            interview_score=_average_score(interview.evaluations or []),
            match_score=match.score if match else None,
            report_score=report.overall_score if report else None,
            answered_questions=answers_count,
            total_questions=total_questions,
        ))
        rendered_pairs.add(pair)

    for report in reports:
        pair = (report.job_id, report.candidate_id)
        if pair in rendered_pairs:
            continue

        match = matches.get(pair)
        rows.append(DashboardInterviewResult(
            session_id=None,
            report_id=report.id,
            candidate_id=report.candidate_id,
            candidate_name=candidates.get(report.candidate_id).full_name if report.candidate_id in candidates else None,
            job_id=report.job_id,
            job_title=jobs.get(report.job_id).title if report.job_id in jobs else None,
            status="report",
            analysis_status="ready",
            interview_score=0.0,
            match_score=match.score if match else None,
            report_score=report.overall_score,
            answered_questions=0,
            total_questions=0,
        ))
        rendered_pairs.add(pair)

    for match in saved_matches:
        pair = (match.job_id, match.candidate_id)
        if pair in rendered_pairs:
            continue

        rows.append(DashboardInterviewResult(
            session_id=None,
            report_id=None,
            candidate_id=match.candidate_id,
            candidate_name=candidates.get(match.candidate_id).full_name if match.candidate_id in candidates else None,
            job_id=match.job_id,
            job_title=jobs.get(match.job_id).title if match.job_id in jobs else None,
            status="match",
            analysis_status="saved",
            interview_score=0.0,
            match_score=match.score,
            report_score=None,
            answered_questions=0,
            total_questions=0,
        ))

    return rows


@router.post("/interviews/chat-answer", response_model=ChatAnswerResponse)
async def chat_answer(
    request: ChatAnswerRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
) -> ChatAnswerResponse:
    """
    Saves an authenticated chat answer and returns the next question when available.
    """
    try:
        await _ensure_interview_access(session, current_user, request.session_id)
        interview_service = get_enhanced_interview_service()
        result = await interview_service.submit_answer(
            session, request.session_id, request.question_id, request.answer, use_llm=False
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
            else:
                background_tasks.add_task(analyze_completed_interview, request.session_id)

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
            evaluation_status=result.get("evaluation_status", "quick"),
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
    """
    Generates a follow-up interview question for a saved answer.
    """
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
    """
    Returns status, visible questions, answers, and average score for an interview.
    """
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
        questions=_status_questions_for_user(current_user, interview),
        answers=safe_answers,
        average_score=avg_score,
    )


@router.delete("/interviews/{session_id}")
async def delete_interview(
    session_id: str,
    _: User = Depends(require_any_role("owner", "admin", "recruiter")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    """
    Deletes an interview and its dependent match, report, and embedding rows.
    """
    interview = await _get_interview_or_404(session, session_id)

    await session.execute(
        delete(MatchResult).where(
            MatchResult.job_id == interview.job_id,
            MatchResult.candidate_id == interview.candidate_id,
        )
    )
    await session.execute(
        delete(Report).where(
            Report.job_id == interview.job_id,
            Report.candidate_id == interview.candidate_id,
        )
    )
    await session.execute(
        delete(Embedding).where(
            Embedding.entity_type.in_(["interview_session", "interview"]),
            Embedding.entity_id == interview.id,
        )
    )
    await session.execute(delete(InterviewSession).where(InterviewSession.id == session_id))
    await session.commit()

    return {"status": "deleted", "session_id": session_id}


@router.post("/interviews/evaluate", response_model=EnhancedEvaluateResponse)
async def evaluate(
    request: EvaluateRequest,
    current_user: User = Depends(require_any_role("owner", "admin", "recruiter", "candidate")),
    session: AsyncSession = Depends(get_db_session),
) -> EnhancedEvaluateResponse:
    """
    Returns the aggregate evaluation for an interview session.
    """
    try:
        await _ensure_interview_access(session, current_user, request.session_id)
        interview_service = get_enhanced_interview_service()
        result = await interview_service.evaluate_session(session, request.session_id)
        return EnhancedEvaluateResponse(**result)
    except ValueError as exc:
        raise _interview_error(exc) from exc
