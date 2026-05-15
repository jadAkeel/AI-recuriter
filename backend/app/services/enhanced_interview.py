from __future__ import annotations

import logging
import random
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
    GENERAL_QUESTIONS,
    _get_questions_for_skill,
)
from app.services.skill_catalog import SKILL_CATEGORIES

logger = logging.getLogger(__name__)


def _skill_to_category(skill: str) -> str:
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
    return [
        f"Understanding of {skill} concepts",
        f"Practical experience with {skill}",
        f"Ability to explain {skill} trade-offs",
        "Communication clarity",
    ]


def _get_tags(skill: str) -> list[str]:
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
        self.use_llm = use_llm
        self._llm_service = None

    def _get_llm_service(self) -> Any:
        if self._llm_service is None and self.use_llm:
            self._llm_service = get_bilingual_llm_service()
        return self._llm_service

    async def generate_questions(
        self,
        session: AsyncSession,
        candidate_id: str,
        job_id: str,
    ) -> tuple[list[QuestionItem], Candidate, Job]:
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

        job_seniority = job.seniority or "mid"

        # Build candidate skill level map from detailed parsing
        candidate_skill_levels: dict[str, str] = {}
        if candidate.skills_detailed:
            for sd in candidate.skills_detailed:
                if isinstance(sd, dict):
                    name = sd.get("name", "").lower()
                    level = sd.get("level", "mid")
                    if name:
                        candidate_skill_levels[name] = level

        all_skills = list(set(candidate.skills + job.required_skills))
        required_set = set(s.lower() for s in (job.required_skills or []))

        questions: list[QuestionItem] = []
        seen_questions: set[str] = set()

        for skill in all_skills:
            # Determine difficulty: job-required skills use job seniority,
            # candidate's own skills use their detected level (or job seniority as fallback)
            skill_lower = skill.lower()
            if skill_lower in required_set:
                difficulty_level = job_seniority
            else:
                difficulty_level = candidate_skill_levels.get(skill_lower, job_seniority)

            skill_qs = _get_questions_for_skill(skill, difficulty_level)
            for q in skill_qs:
                if q["question"] not in seen_questions:
                    category = _skill_to_category(skill)
                    difficulty = q.get("difficulty", difficulty_level)
                    questions.append(QuestionItem(
                        id=str(uuid.uuid4()),
                        skill=skill,
                        question=q["question"],
                        difficulty=difficulty,
                        category=category,
                        expected_answer_hint=_get_hint_for_skill(skill, difficulty),
                        evaluation_criteria=_get_evaluation_criteria(skill),
                        tags=_get_tags(skill),
                    ))
                    seen_questions.add(q["question"])

        random.shuffle(questions)
        questions = questions[:8]

        if len(questions) < 3:
            remaining = 5 - len(questions)
            for q in GENERAL_QUESTIONS[:remaining]:
                questions.append(QuestionItem(
                    id=str(uuid.uuid4()),
                    skill="general",
                    question=q["question"],
                    difficulty=q.get("difficulty", job_seniority),
                    category="Behavioral",
                    expected_answer_hint="Provide a specific example from your experience.",
                    evaluation_criteria=["Relevance of example", "Communication clarity", "Self-awareness"],
                    tags=["behavioral", "soft-skills"],
                ))

        return questions, candidate, job

    async def create_session(
        self,
        session: AsyncSession,
        job_id: str,
        candidate_id: str,
    ) -> tuple[InterviewSessionModel, str | None, str | None]:
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

            return {
                "score": evaluation.get("score", 0.5),
                "feedback": evaluation.get("feedback", "Evaluation complete"),
                "language_detected": evaluation.get("language_detected", "english"),
                "strengths": evaluation.get("strengths", []),
                "weaknesses": evaluation.get("weaknesses", []),
                "technical_accuracy": evaluation.get("technical_accuracy", 0.5),
                "completeness": evaluation.get("completeness", 0.5),
                "clarity": evaluation.get("clarity", 0.5),
                "using_llm": True,
            }
        except Exception as e:
            logger.error(f"LLM evaluation failed: {e}")
            return self._evaluate_rule_based(question, answer, skill)

    def _evaluate_rule_based(
        self, question: str, answer: str, skill: str
    ) -> dict[str, Any]:
        if not answer or len(answer.strip()) < 10:
            return {
                "score": 0.1,
                "feedback": f"الإجابة قصيرة جداً. يرجى تقديم مزيد من التفاصيل حول {skill}.",
                "language_detected": "arabic",
                "strengths": [],
                "weaknesses": ["الإجابة غير كافية"],
                "technical_accuracy": 0.1,
                "completeness": 0.1,
                "clarity": 0.3,
                "using_llm": False,
            }

        answer_lower = answer.lower()
        words = answer_lower.split()
        word_count = len(words)

        has_arabic = any("\u0600" <= c <= "\u06FF" for c in answer)

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

        language = "arabic" if has_arabic else "english"

        if score >= 0.85:
            feedback = (
                f"ممتاز! فهم قوي جداً لـ {skill}. الإجابة واضحة ودقيقة."
                if has_arabic
                else f"Excellent! Strong understanding of {skill}. Clear and accurate explanation."
            )
        elif score >= 0.65:
            feedback = (
                f"جيد! معرفة جيدة بـ {skill}. يمكنك إضافة المزيد من التفاصيل."
                if has_arabic
                else f"Good! Solid knowledge of {skill}. Could expand on some details."
            )
        elif score >= 0.45:
            feedback = (
                f"متوسط. فهم أساسي لـ {skill}. تحتاج إلى تعميق المعرفة التقنية."
                if has_arabic
                else f"Average. Basic understanding of {skill}. Needs to deepen technical knowledge."
            )
        else:
            feedback = (
                f"ضعيف. فهم محدود لـ {skill}. يُنصح بمزيد من الدراسة."
                if has_arabic
                else f"Weak. Limited understanding of {skill}. Recommend further study."
            )

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
    ) -> dict[str, Any]:
        stmt = select(InterviewSessionModel).where(InterviewSessionModel.id == session_id)
        result = await session.execute(stmt)
        interview = result.scalar_one_or_none()
        if interview is None:
            raise ValueError("Interview session not found")

        questions = [QuestionItem(**q) for q in interview.questions]
        question_item = next((q for q in questions if q.id == question_id), None)
        if question_item is None:
            raise ValueError("Question not found")

        evaluation = await self.evaluate_answer_with_llm(
            question=question_item.question,
            answer=answer,
            skill=question_item.skill,
            difficulty=question_item.difficulty,
        )

        answers = list(interview.answers or [])
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
        }

    async def generate_followup(
        self,
        question: str,
        answer: str,
        skill: str,
        score: float,
    ) -> dict[str, Any]:
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

        is_arabic = "arabic" in languages_used

        if overall_score >= 0.8:
            feedback = (
                "أداء ممتاز! معرفة تقنية قوية في معظم المجالات."
                if is_arabic
                else "Excellent performance! Strong technical knowledge across most areas."
            )
        elif overall_score >= 0.6:
            feedback = (
                "أداء جيد. أساس تقني متين مع بعض المجالات التي تحتاج تحسين."
                if is_arabic
                else "Good performance. Solid technical foundation with some areas for improvement."
            )
        elif overall_score >= 0.4:
            feedback = (
                "أداء متوسط. يحتاج إلى تحسين في عدة مجالات تقنية."
                if is_arabic
                else "Average performance. Needs improvement in several technical areas."
            )
        else:
            feedback = (
                "أداء دون المتوسط. فجوات كبيرة في المعرفة التقنية."
                if is_arabic
                else "Below average performance. Significant gaps in technical knowledge."
            )

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
    return EnhancedInterviewService(use_llm=True)


def get_simple_interview_service() -> EnhancedInterviewService:
    return EnhancedInterviewService(use_llm=False)
