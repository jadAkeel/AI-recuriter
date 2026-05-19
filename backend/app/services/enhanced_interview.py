from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.interview import InterviewSession as InterviewSessionModel
from app.models.job import Job
from app.schemas.interview import QuestionItem
from app.services.bilingual_llm import get_bilingual_llm_service
from app.services.interview import (
    build_grounded_question_items,
)
from app.services.skill_catalog import SKILL_CATEGORIES

logger = logging.getLogger(__name__)


def _skill_to_category(skill: str) -> str:
    """
    Maps a skill name to a broad interview category.
    """
    skill_lower = skill.lower().strip()
    if skill_lower in ("general", "behavioral", "communication", "teamwork", "leadership", "agile", "scrum"):
        return "Behavioral"
    if skill_lower in ("problem solving", "critical thinking", "debugging", "troubleshooting", "algorithm"):
        return "Problem Solving"
    nlp_ai = {"nlp", "transformers", "hugging face", "langchain", "rag", "llm", "openai",
              "prompt engineering", "machine learning", "deep learning", "pytorch", "tensorflow",
              "scikit-learn", "computer vision", "spacy", "nltk", "gensim"}
    if skill_lower in nlp_ai:
        return "NLP/AI"
    system_design = {"system design", "architecture", "microservices", "distributed systems",
                     "scalability", "performance", "design patterns", "api design", "rest api"}
    if skill_lower in system_design:
        return "System Design"
    return "Technical"


def _get_hint_for_skill(skill: str, difficulty: str) -> str:
    """
    Builds a short expected-answer hint for a skill and difficulty.
    """
    hints = {
        "python": "Discuss key language features, syntax, and common use cases.",
        "fastapi": "Focus on async patterns, dependency injection, and Pydantic integration.",
        "sql": "Mention joins, indexing, query optimization, and ACID properties.",
        "docker": "Talk about image layers, container lifecycle, and multi-stage builds.",
        "kubernetes": "Cover pods, deployments, services, and cluster management.",
        "react": "Discuss component lifecycle, hooks, state management, and virtual DOM.",
        "machine learning": "Talk about model training, evaluation metrics, and data preprocessing.",
        "nlp": "Discuss tokenization, embeddings, sequence models, and modern transformer architectures.",
        "aws": "Cover core services, security groups, IAM, and cost optimization.",
    }
    base = hints.get(skill.lower().strip(), f"Demonstrate practical knowledge of {skill}.")
    if difficulty == "junior":
        return f"{base} Focus on fundamentals."
    if difficulty == "senior":
        return f"{base} Include advanced patterns, trade-offs, and real-world experience."
    return base


def _get_evaluation_criteria(skill: str) -> list[str]:
    """
    Builds default evaluation criteria for a skill.
    """
    return [
        f"Understanding of {skill} concepts",
        f"Practical experience with {skill}",
        f"Ability to explain {skill} trade-offs",
        "Communication clarity",
    ]


def _get_tags(skill: str) -> list[str]:
    """
    Builds searchable tags for an interview question.
    """
    skill_lower = skill.lower().strip()
    tags = [skill_lower]
    for category, skills in SKILL_CATEGORIES.items():
        if skill_lower in skills:
            tags.append(category.lower().replace(" ", "-"))
            break
    tags.append("technical")
    return tags


class EnhancedInterviewService:
    def __init__(self, use_llm: bool = True) -> None:
        """
        Initializes the enhanced interview service with optional LLM evaluation.
        """
        self.use_llm = use_llm
        self._llm_service = None

    def _get_llm_service(self) -> Any:
        """
        Lazily creates the LLM service for answer evaluation.
        """
        if self._llm_service is None and self.use_llm:
            self._llm_service = get_bilingual_llm_service()
        return self._llm_service

    async def generate_questions(
        self,
        session: AsyncSession,
        candidate_id: str,
        job_id: str,
    ) -> tuple[list[QuestionItem], Candidate, Job]:
        """
        Loads candidate and job records and enriches grounded interview questions.
        """
        cand_stmt = select(Candidate).where(Candidate.id == candidate_id)
        cand_result = await session.execute(cand_stmt)
        candidate = cand_result.scalar_one_or_none()
        if candidate is None:
            raise ValueError("Candidate not found")

        job_stmt = select(Job).where(Job.id == job_id)
        job_result = await session.execute(job_stmt)
        job = job_result.scalar_one_or_none()
        if job is None:
            raise ValueError("Job not found")

        questions = build_grounded_question_items(candidate, job, limit=8)
        for question in questions:
            question.category = _skill_to_category(question.skill)
            question.expected_answer_hint = question.expected_answer_hint or _get_hint_for_skill(
                question.skill,
                question.difficulty,
            )
            question.evaluation_criteria = question.evaluation_criteria or _get_evaluation_criteria(question.skill)
            question.tags = sorted(set(question.tags + _get_tags(question.skill)))

        return questions, candidate, job

    async def create_session(
        self,
        session: AsyncSession,
        job_id: str,
        candidate_id: str,
    ) -> tuple[InterviewSessionModel, str | None, str | None]:
        """
        Creates an interview session with enriched questions.
        """
        questions, candidate, job = await self.generate_questions(session, candidate_id, job_id)

        interview = InterviewSessionModel(
            id=str(uuid.uuid4()),
            job_id=job_id,
            candidate_id=candidate_id,
            questions=[q.model_dump() for q in questions],
            answers=[],
            evaluations=[],
            chat_history=[],
            status="pending",
        )
        session.add(interview)
        await session.commit()

        return interview, candidate.full_name, job.title

    async def evaluate_answer_with_llm(
        self,
        question: str,
        answer: str,
        skill: str,
        difficulty: str = "mid",
    ) -> dict[str, Any]:
        """
        Evaluates an answer with the LLM and falls back to rule-based scoring.
        """
        llm_service = self._get_llm_service()

        if llm_service is None or not self.use_llm:
            return self._evaluate_rule_based(question, answer, skill)

        try:
            evaluation = await llm_service.evaluate_answer(
                question=question,
                answer=answer,
                skill=skill,
                difficulty=difficulty,
            )
            score = max(0.0, min(1.0, float(evaluation.get("score", 0.5))))

            return {
                "score": score,
                "feedback": evaluation.get("feedback", "Evaluation complete"),
                "language_detected": evaluation.get("language_detected", "english"),
                "strengths": evaluation.get("strengths", []),
                "weaknesses": evaluation.get("weaknesses", []),
                "technical_accuracy": max(0.0, min(1.0, float(evaluation.get("technical_accuracy", 0.5)))),
                "completeness": max(0.0, min(1.0, float(evaluation.get("completeness", 0.5)))),
                "clarity": max(0.0, min(1.0, float(evaluation.get("clarity", 0.5)))),
                "using_llm": True,
            }
        except Exception as e:
            logger.error(f"LLM evaluation failed: {e}")
            return self._evaluate_rule_based(question, answer, skill)

    def _evaluate_rule_based(
        self, question: str, answer: str, skill: str
    ) -> dict[str, Any]:
        """
        Scores an interview answer with simple local heuristics.
        """
        if not answer or len(answer.strip()) < 10:
            return {
                "score": 0.1,
                "feedback": f"Answer is too short. Please provide more details about {skill}.",
                "language_detected": "english",
                "strengths": [],
                "weaknesses": ["Answer too short"],
                "technical_accuracy": 0.1,
                "completeness": 0.1,
                "clarity": 0.3,
                "using_llm": False,
            }

        answer_lower = answer.lower()
        words = answer_lower.split()
        word_count = len(words)

        skill_keywords = set(skill.lower().split())
        keyword_matches = sum(1 for kw in skill_keywords if kw in answer_lower)

        tech_terms = {
            "python",
            "fastapi",
            "api",
            "database",
            "sql",
            "algorithm",
            "data",
            "system",
            "design",
            "architecture",
            "framework",
            "library",
            "function",
            "class",
            "object",
            "method",
            "variable",
            "loop",
            "condition",
            "error",
            "exception",
            "testing",
            "deploy",
            "server",
            "client",
            "request",
            "response",
            "model",
            "train",
            "inference",
            "pipeline",
            "workflow",
            "implementation",
            "optimization",
            "performance",
            "security",
            "scalable",
        }
        tech_matches = sum(1 for t in tech_terms if t in answer_lower)

        length_score = min(0.3, word_count / 100 * 0.3)
        keyword_score = min(0.4, keyword_matches * 0.2)
        tech_score = min(0.3, tech_matches * 0.05)

        score = round(min(1.0, length_score + keyword_score + tech_score + 0.1), 4)

        language = "english"

        if score >= 0.85:
            feedback = f"Excellent! Strong understanding of {skill}. Clear and accurate explanation."
        elif score >= 0.65:
            feedback = f"Good! Solid knowledge of {skill}. Could expand on some details."
        elif score >= 0.45:
            feedback = f"Average. Basic understanding of {skill}. Needs to deepen technical knowledge."
        else:
            feedback = f"Weak. Limited understanding of {skill}. Recommend further study."

        return {
            "score": score,
            "feedback": feedback,
            "language_detected": language,
            "strengths": ["Good effort"] if score >= 0.5 else [],
            "weaknesses": ["Needs more detail"] if score < 0.7 else [],
            "technical_accuracy": min(1.0, keyword_score + 0.2),
            "completeness": min(1.0, length_score + 0.3),
            "clarity": 0.6,
            "using_llm": False,
        }

    async def submit_answer(
        self,
        session: AsyncSession,
        session_id: str,
        question_id: str,
        answer: str,
        use_llm: bool | None = None,
    ) -> dict[str, Any]:
        """
        Stores one answer, its evaluation, and updated chat history.
        """
        stmt = select(InterviewSessionModel).where(InterviewSessionModel.id == session_id)
        result = await session.execute(stmt)
        interview = result.scalar_one_or_none()
        if interview is None:
            raise ValueError("Interview session not found")

        questions = [QuestionItem(**q) for q in interview.questions]
        question_item = next((q for q in questions if q.id == question_id), None)
        if question_item is None:
            raise ValueError("Question not found")

        answers = list(interview.answers or [])
        if len(answers) >= len(questions):
            raise ValueError("Interview already completed")
        expected_question = questions[len(answers)]
        if expected_question.id != question_id:
            raise ValueError("Answer does not match the current question")

        should_use_llm = self.use_llm if use_llm is None else use_llm
        if should_use_llm:
            evaluation = await self.evaluate_answer_with_llm(
                question=question_item.question,
                answer=answer,
                skill=question_item.skill,
                difficulty=question_item.difficulty,
            )
        else:
            evaluation = self._evaluate_rule_based(
                question=question_item.question,
                answer=answer,
                skill=question_item.skill,
            )

        evaluations = list(interview.evaluations or [])
        chat_history = list(interview.chat_history or [])

        chat_entry = {
            "question_id": question_id,
            "question": question_item.question,
            "skill": question_item.skill,
            "answer": answer,
            "evaluation": evaluation,
            "timestamp": str(datetime.now()),
        }
        chat_history.append(chat_entry)
        answers.append(answer)
        evaluations.append(
            {
                "question_id": question_id,
                "score": evaluation["score"],
                "feedback": evaluation["feedback"],
                "language_detected": evaluation.get("language_detected", "english"),
                "strengths": evaluation.get("strengths", []),
                "weaknesses": evaluation.get("weaknesses", []),
                "using_llm": evaluation.get("using_llm", False),
                "evaluation_status": "completed" if should_use_llm else "quick",
            }
        )

        interview.chat_history = chat_history
        interview.answers = answers
        interview.evaluations = evaluations

        if len(answers) >= len(interview.questions):
            interview.status = "completed"
        else:
            interview.status = "in_progress"

        await session.commit()

        return {
            "question_id": question_id,
            "skill": question_item.skill,
            "question": question_item.question,
            "answer": answer,
            "score": evaluation["score"],
            "feedback": evaluation["feedback"],
            "language_detected": evaluation.get("language_detected", "english"),
            "strengths": evaluation.get("strengths", []),
            "weaknesses": evaluation.get("weaknesses", []),
            "using_llm": evaluation.get("using_llm", False),
            "evaluation_status": "completed" if should_use_llm else "quick",
        }

    async def generate_followup(
        self,
        question: str,
        answer: str,
        skill: str,
        score: float,
    ) -> dict[str, Any]:
        """
        Generates a follow-up question or a safe local fallback.
        """
        llm_service = self._get_llm_service()

        if llm_service is None or not self.use_llm:
            return {
                "followup_question": f"Can you tell me more about your practical experience with {skill}?",
                "reason": "To explore deeper understanding",
                "expected_topic": skill,
            }

        try:
            return await llm_service.generate_followup_question(
                question=question,
                answer=answer,
                skill=skill,
                score=score,
            )
        except Exception as e:
            logger.error(f"Follow-up generation failed: {e}")
            return {
                "followup_question": f"Can you elaborate on your experience with {skill}?",
                "reason": "Default follow-up",
                "expected_topic": skill,
            }

    async def evaluate_session(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> dict[str, Any]:
        """
        Aggregates all interview answer evaluations into a session summary.
        """
        stmt = select(InterviewSessionModel).where(InterviewSessionModel.id == session_id)
        result = await session.execute(stmt)
        interview = result.scalar_one_or_none()
        if interview is None:
            raise ValueError("Interview session not found")

        if not interview.evaluations:
            raise ValueError("No answers to evaluate")

        scores = [e["score"] for e in interview.evaluations]
        overall_score = round(sum(scores) / len(scores), 4)

        questions = [QuestionItem(**q) for q in interview.questions]
        skill_scores: dict[str, list[float]] = {}
        languages_used: set[str] = set()

        for q, ev in zip(questions, interview.evaluations):
            if q.skill not in skill_scores:
                skill_scores[q.skill] = []
            skill_scores[q.skill].append(ev["score"])

            if "language_detected" in ev:
                languages_used.add(ev["language_detected"])

        skill_avgs = {s: round(sum(v) / len(v), 4) for s, v in skill_scores.items()}

        strengths = sorted(
            [s for s, sc in skill_avgs.items() if sc >= 0.7],
            key=lambda s: skill_avgs[s],
            reverse=True,
        )
        weaknesses = sorted(
            [s for s, sc in skill_avgs.items() if sc < 0.5],
            key=lambda s: skill_avgs[s],
        )

        if overall_score >= 0.8:
            feedback = "Excellent performance! Strong technical knowledge across most areas."
        elif overall_score >= 0.6:
            feedback = "Good performance. Solid technical foundation with some areas for improvement."
        elif overall_score >= 0.4:
            feedback = "Average performance. Needs improvement in several technical areas."
        else:
            feedback = "Below average performance. Significant gaps in technical knowledge."

        if interview.status != "analyzing":
            interview.status = "evaluated"
        await session.commit()

        return {
            "session_id": session_id,
            "overall_score": overall_score,
            "skill_scores": skill_avgs,
            "feedback": feedback,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "languages_used": list(languages_used),
            "total_questions": len(questions),
            "answered_questions": len(interview.answers),
        }


def get_enhanced_interview_service() -> EnhancedInterviewService:
    """
    Creates an interview service with LLM evaluation enabled.
    """
    return EnhancedInterviewService(use_llm=True)


def get_simple_interview_service() -> EnhancedInterviewService:
    """
    Creates an interview service with LLM evaluation disabled.
    """
    return EnhancedInterviewService(use_llm=False)
