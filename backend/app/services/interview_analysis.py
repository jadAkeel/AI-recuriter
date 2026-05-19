from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.models.interview import InterviewSession as InterviewSessionModel
from app.models.match_result import MatchResult
from app.schemas.interview import QuestionItem
from app.services.enhanced_interview import get_enhanced_interview_service

logger = logging.getLogger(__name__)


def _average_score(evaluations: list[dict[str, Any]]) -> float:
    """
    Calculates the average score from interview evaluation rows.
    """
    scores = [float(item.get("score", 0)) for item in evaluations if isinstance(item, dict)]
    return round(sum(scores) / len(scores), 4) if scores else 0.0


async def analyze_completed_interview(session_id: str) -> None:
    """Run slow post-interview LLM analysis outside the candidate request path."""

    try:
        async with SessionLocal() as session:
            await analyze_completed_interview_in_session(session, session_id)
    except Exception:
        logger.exception("Post-interview analysis failed", extra={"session_id": session_id})


async def analyze_completed_interview_in_session(session: AsyncSession, session_id: str) -> None:
    """
    Re-evaluates completed interview answers and stores the final analysis.
    """
    stmt = select(InterviewSessionModel).where(InterviewSessionModel.id == session_id)
    result = await session.execute(stmt)
    interview = result.scalar_one_or_none()
    if interview is None:
        return

    questions = [QuestionItem(**item) for item in (interview.questions or [])]
    answers = list(interview.answers or [])
    if not questions or len(answers) < len(questions):
        return

    existing_evaluations = list(interview.evaluations or [])
    if existing_evaluations and all(item.get("using_llm") for item in existing_evaluations):
        await upsert_interview_match_result(session, interview, existing_evaluations)
        return

    interview.status = "analyzing"
    await session.commit()

    service = get_enhanced_interview_service()
    evaluations: list[dict[str, Any]] = []
    chat_history: list[dict[str, Any]] = []

    try:
        for question, answer in zip(questions, answers):
            evaluation = await service.evaluate_answer_with_llm(
                question=question.question,
                answer=answer,
                skill=question.skill,
                difficulty=question.difficulty,
            )
            evaluations.append({
                "question_id": question.id,
                "score": evaluation["score"],
                "feedback": evaluation["feedback"],
                "language_detected": evaluation.get("language_detected", "english"),
                "strengths": evaluation.get("strengths", []),
                "weaknesses": evaluation.get("weaknesses", []),
                "using_llm": evaluation.get("using_llm", False),
                "evaluation_status": "completed",
            })
            chat_history.append({
                "question_id": question.id,
                "question": question.question,
                "skill": question.skill,
                "answer": answer,
                "evaluation": evaluation,
                "timestamp": datetime.now().isoformat(),
            })
    except Exception:
        interview.status = "completed"
        await session.commit()
        raise

    interview.evaluations = evaluations
    interview.chat_history = chat_history
    interview.status = "evaluated"
    await session.commit()

    await upsert_interview_match_result(session, interview, evaluations)


async def upsert_interview_match_result(
    session: AsyncSession,
    interview: InterviewSessionModel,
    evaluations: list[dict[str, Any]],
) -> None:
    """
    Creates or updates the match score blended with interview analysis.
    """
    interview_score = _average_score(evaluations)

    stmt = select(MatchResult).where(
        MatchResult.job_id == interview.job_id,
        MatchResult.candidate_id == interview.candidate_id,
    )
    result = await session.execute(stmt)
    match = result.scalar_one_or_none()

    cv_score: float
    previous_reasoning = match.reasoning if match is not None and isinstance(match.reasoning, dict) else {}
    if isinstance(previous_reasoning.get("cv_match_score"), (int, float)):
        cv_score = float(previous_reasoning["cv_match_score"])
    elif match is not None and previous_reasoning.get("scoring_model") != "cv_interview_blend":
        cv_score = float(match.score)
    else:
        try:
            from app.services.explainability import generate_candidate_report

            report = await generate_candidate_report(
                session,
                interview.job_id,
                interview.candidate_id,
                use_match_score=False,
            )
            cv_score = report.score_breakdown.overall_score
        except Exception:
            logger.warning(
                "Could not generate CV report for interview-adjusted match",
                extra={"session_id": interview.id},
                exc_info=True,
            )
            cv_score = 0.5

    final_score = round((0.65 * cv_score) + (0.35 * interview_score), 4)
    reasoning = {
        "scoring_model": "cv_interview_blend",
        "scoring_formula": "0.65 CV/job match + 0.35 post-interview answer analysis",
        "cv_match_score": round(cv_score, 4),
        "interview_score": interview_score,
        "final_score": final_score,
        "interview_session_id": interview.id,
        "interview_analysis_status": "ready",
        "answer_scores": [
            {
                "question_id": item.get("question_id"),
                "score": item.get("score", 0),
                "feedback": item.get("feedback", ""),
            }
            for item in evaluations
        ],
    }
    if match is None:
        match = MatchResult(
            job_id=interview.job_id,
            candidate_id=interview.candidate_id,
            score=final_score,
            reasoning=reasoning,
        )
        session.add(match)
    else:
        match.score = final_score
        match.reasoning = {**previous_reasoning, **reasoning}

    await session.commit()
