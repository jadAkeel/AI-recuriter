from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.interview import InterviewSession as InterviewSessionModel
from app.models.job import Job
from app.schemas.interview import AnswerResponse, QuestionItem
from app.services.skill_catalog import normalize_skill_name

logger = logging.getLogger(__name__)

QUESTION_TEMPLATES: dict[str, list[dict[str, str]]] = {
    "python": [
        {"question": "Explain the difference between a list and a tuple in Python.", "difficulty": "junior"},
        {"question": "How does Python's garbage collection work?", "difficulty": "mid"},
        {"question": "Explain decorators in Python and provide a use case.", "difficulty": "mid"},
        {"question": "What is the GIL in Python and how does it affect concurrency?", "difficulty": "senior"},
        {"question": "Describe how you would implement a singleton pattern in Python.", "difficulty": "mid"},
    ],
    "fastapi": [
        {"question": "What is dependency injection in FastAPI and how does it work?", "difficulty": "mid"},
        {"question": "How do you handle database sessions in FastAPI?", "difficulty": "mid"},
        {"question": "Explain FastAPI's background tasks and when to use them.", "difficulty": "senior"},
        {"question": "How does FastAPI handle validation using Pydantic models?", "difficulty": "junior"},
    ],
    "sql": [
        {"question": "Explain the difference between INNER JOIN and LEFT JOIN.", "difficulty": "junior"},
        {"question": "What is a window function in SQL? Provide an example.", "difficulty": "mid"},
        {"question": "How would you optimize a slow SQL query?", "difficulty": "senior"},
    ],
    "docker": [
        {"question": "What is the difference between a Docker image and a container?", "difficulty": "junior"},
        {"question": "Explain Docker multi-stage builds and their benefits.", "difficulty": "mid"},
        {"question": "How do you manage networking between multiple Docker containers?", "difficulty": "mid"},
    ],
    "kubernetes": [
        {"question": "What is a Kubernetes Pod and how does it differ from a Deployment?", "difficulty": "mid"},
        {"question": "Explain Kubernetes services and their types.", "difficulty": "mid"},
        {"question": "How does Kubernetes handle service discovery and load balancing?", "difficulty": "senior"},
    ],
    "aws": [
        {"question": "Explain the difference between S3 and EBS storage.", "difficulty": "junior"},
        {"question": "What is AWS Lambda and when would you use it?", "difficulty": "mid"},
        {"question": "How would you design a scalable architecture on AWS?", "difficulty": "senior"},
    ],
    "react": [
        {"question": "Explain the virtual DOM and how React uses it.", "difficulty": "junior"},
        {"question": "What is the purpose of useEffect hook in React?", "difficulty": "junior"},
        {"question": "Explain state management in React. When would you use Redux vs Context API?", "difficulty": "mid"},
    ],
    "machine learning": [
        {"question": "Explain the bias-variance tradeoff in machine learning.", "difficulty": "mid"},
        {"question": "What is overfitting and how do you prevent it?", "difficulty": "junior"},
        {"question": "Explain ensemble learning methods and their advantages.", "difficulty": "senior"},
    ],
    "nlp": [
        {"question": "Explain the difference between word embeddings and bag-of-words.", "difficulty": "mid"},
        {"question": "What is the Transformer architecture and why is it important?", "difficulty": "senior"},
        {"question": "How do you handle out-of-vocabulary words in NLP?", "difficulty": "mid"},
    ],
    "javascript": [
        {"question": "Explain closures in JavaScript with an example.", "difficulty": "mid"},
        {"question": "What is the event loop in JavaScript?", "difficulty": "mid"},
        {"question": "Explain promises and async/await in JavaScript.", "difficulty": "junior"},
    ],
    "typescript": [
        {"question": "What are the key benefits of TypeScript over JavaScript?", "difficulty": "junior"},
        {"question": "Explain generics in TypeScript with an example.", "difficulty": "mid"},
    ],
    "postgresql": [
        {"question": "What is a transaction in PostgreSQL and why is it important?", "difficulty": "junior"},
        {"question": "Explain the difference between indexes in PostgreSQL.", "difficulty": "mid"},
        {"question": "How does PostgreSQL handle full-text search?", "difficulty": "senior"},
    ],
    "git": [
        {"question": "Explain the difference between merge and rebase in Git.", "difficulty": "junior"},
        {"question": "What is a Git workflow you would recommend for a team?", "difficulty": "mid"},
    ],
    "ci/cd": [
        {"question": "What is CI/CD and why is it important?", "difficulty": "junior"},
        {"question": "Explain the difference between continuous delivery and continuous deployment.", "difficulty": "mid"},
    ],
    "data engineering": [
        {"question": "Explain the difference between ETL and ELT.", "difficulty": "mid"},
        {"question": "How would you design a data pipeline for real-time processing?", "difficulty": "senior"},
    ],
}

GENERAL_QUESTIONS = [
    {"question": "Describe a challenging technical project you worked on and how you overcame obstacles.", "difficulty": "mid"},
    {"question": "How do you stay up to date with new technologies and industry trends?", "difficulty": "junior"},
    {"question": "Tell me about a time you had to collaborate with a cross-functional team.", "difficulty": "mid"},
    {"question": "How do you approach debugging a complex issue in production?", "difficulty": "senior"},
    {"question": "What is your experience with agile development methodologies?", "difficulty": "junior"},
]

SCORE_THRESHOLDS = {
    "excellent": 0.85,
    "good": 0.65,
    "average": 0.45,
    "weak": 0.0,
}

FEEDBACK_TEMPLATES = {
    "excellent": "Strong understanding of {skill}. Provided clear and accurate explanation.",
    "good": "Good knowledge of {skill}. Some details could be expanded.",
    "average": "Basic understanding of {skill}. Needs to deepen technical knowledge.",
    "weak": "Limited understanding of {skill}. Recommend further study.",
}


def _get_questions_for_skill(skill: str, seniority: str) -> list[dict[str, str]]:
    """
    Selects template questions that match a skill and seniority level.
    """
    templates = QUESTION_TEMPLATES.get(skill, [])
    if not templates:
        return []

    seniority_order = {"junior": 0, "mid": 1, "senior": 2}
    target = seniority_order.get(seniority, 1)

    matching = [q for q in templates if seniority_order.get(q["difficulty"], 1) <= target]
    if not matching:
        matching = templates[:2]

    return matching[:2]


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    """
    Normalizes skill names while preserving first-seen order.
    """
    result: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        normalized = normalize_skill_name(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _stable_question_id(candidate_id: str, job_id: str, skill: str, question: str) -> str:
    """
    Builds a deterministic question ID from candidate, job, skill, and text.
    """
    key = f"{candidate_id}:{job_id}:{skill.lower().strip()}:{question}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def _candidate_evidence_for_skill(candidate: Candidate, skill: str) -> str | None:
    """
    Finds CV evidence that supports asking about a specific skill.
    """
    skill_lower = skill.lower().strip()
    for detail in candidate.skills_detailed or []:
        if not isinstance(detail, dict):
            continue
        name = str(detail.get("name", "")).lower().strip()
        context = str(detail.get("context", "")).strip()
        status = str(detail.get("status", "")).lower().strip()
        if name == skill_lower and context and status in {"has_experience", "unknown"}:
            return context[:220]

    for line in list(candidate.experience or []) + list(candidate.projects or []) + list(candidate.education or []):
        if skill_lower in str(line).lower():
            return str(line).strip()[:220]
    return None


def _evaluation_criteria_for_skill(skill: str, grounded: bool) -> list[str]:
    """
    Builds evaluation criteria for a skill question.
    """
    criteria = [
        f"Accurate understanding of {skill}",
        "Practical example grounded in the candidate's own experience",
        "Clear trade-offs, constraints, or failure modes",
        "Communication clarity",
    ]
    if not grounded:
        criteria[1] = "Honest handling of missing CV evidence; says not found if no experience exists"
    return criteria


def _question_for_skill(
    candidate: Candidate,
    job: Job,
    skill: str,
    difficulty: str,
    required: bool,
) -> QuestionItem:
    """
    Creates one grounded interview question for a job skill.
    """
    evidence = _candidate_evidence_for_skill(candidate, skill)
    role = job.title or "this role"
    if evidence:
        question = (
            f"Your CV mentions: \"{evidence}\". For the {role} role, how did you use {skill}, "
            "what trade-offs did you make, and how did you validate the result?"
        )
        hint = f"Look for a specific {skill} example tied to the cited CV evidence."
    elif required:
        question = (
            f"The job requires {skill}, but it was not found in the parsed CV. "
            "Describe directly relevant experience if you have it; otherwise say not found."
        )
        hint = "Look for honest gap handling and any transferable evidence."
    else:
        templates = _get_questions_for_skill(skill, difficulty)
        if templates:
            question = templates[0]["question"]
            difficulty = templates[0].get("difficulty", difficulty)
        else:
            question = f"How would you apply {skill} in a practical {role} project?"
        hint = f"Look for practical, role-relevant {skill} knowledge."

    return QuestionItem(
        id=_stable_question_id(candidate.id, job.id, skill, question),
        skill=skill,
        question=question,
        difficulty=difficulty,
        expected_answer_hint=hint,
        evaluation_criteria=_evaluation_criteria_for_skill(skill, evidence is not None),
        tags=[skill.lower().strip(), "grounded" if evidence else "requirement-gap" if required else "job-skill"],
    )


def build_grounded_question_items(candidate: Candidate, job: Job, limit: int = 8) -> list[QuestionItem]:
    """
    Builds interview questions from job requirements and candidate evidence.
    """
    seniority = (job.seniority or "mid").lower()
    required_skills = _dedupe_preserve_order(job.required_skills or [])
    optional_skills = [
        skill for skill in _dedupe_preserve_order(job.optional_skills or [])
        if skill.lower().strip() not in {req.lower().strip() for req in required_skills}
    ]

    questions: list[QuestionItem] = []
    seen_questions: set[str] = set()

    for skill in required_skills + optional_skills:
        required = skill.lower().strip() in {req.lower().strip() for req in required_skills}
        item = _question_for_skill(candidate, job, skill, seniority, required)
        if item.question not in seen_questions:
            questions.append(item)
            seen_questions.add(item.question)
        if len(questions) >= limit:
            return questions

    if questions:
        return questions

    role = job.title or "the role"
    for index, q in enumerate(GENERAL_QUESTIONS[: min(3, limit)]):
        question = f"For {role}, {q['question'][0].lower() + q['question'][1:]}"
        questions.append(QuestionItem(
            id=_stable_question_id(candidate.id, job.id, "general", f"{index}:{question}"),
            skill="general",
            question=question,
            difficulty=q.get("difficulty", seniority),
            category="Behavioral",
            expected_answer_hint="Look for a specific example from the CV or candidate's actual experience.",
            evaluation_criteria=["Specificity", "Role relevance", "Communication clarity"],
            tags=["behavioral", "fallback"],
        ))
    return questions


async def generate_interview_questions(
    session: AsyncSession,
    candidate_id: str,
    job_id: str,
) -> tuple[list[QuestionItem], Candidate, Job]:
    """
    Loads candidate and job records and generates interview questions.
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

    return questions, candidate, job


def _evaluate_single_answer(question: str, answer: str, skill: str) -> tuple[float, str]:
    """
    Scores one answer with a lightweight rule-based heuristic.
    """
    if not answer or len(answer.strip()) < 10:
        return 0.1, FEEDBACK_TEMPLATES["weak"].format(skill=skill)

    answer_lower = answer.lower()
    words = answer_lower.split()
    word_count = len(words)

    skill_keywords = set(skill.lower().split())
    keyword_matches = sum(1 for kw in skill_keywords if kw in answer_lower)

    tech_terms = {
        "python", "fastapi", "api", "database", "sql", "algorithm", "data",
        "system", "design", "architecture", "framework", "library", "function",
        "class", "object", "method", "variable", "loop", "condition", "error",
        "exception", "testing", "deploy", "server", "client", "request",
        "response", "model", "train", "inference", "pipeline", "workflow",
        "implementation", "optimization", "performance", "security", "scalable",
    }
    tech_matches = sum(1 for t in tech_terms if t in answer_lower)

    length_score = min(0.3, word_count / 100 * 0.3)
    keyword_score = min(0.4, keyword_matches * 0.2)
    tech_score = min(0.3, tech_matches * 0.05)

    score = round(min(1.0, length_score + keyword_score + tech_score + 0.1), 4)

    if score >= SCORE_THRESHOLDS["excellent"]:
        level = "excellent"
    elif score >= SCORE_THRESHOLDS["good"]:
        level = "good"
    elif score >= SCORE_THRESHOLDS["average"]:
        level = "average"
    else:
        level = "weak"

    return score, FEEDBACK_TEMPLATES[level].format(skill=skill)


async def create_interview_session(
    session: AsyncSession,
    job_id: str,
    candidate_id: str,
) -> tuple[InterviewSessionModel, str | None, str | None]:
    """
    Creates and stores a new interview session.
    """
    questions, candidate, job = await generate_interview_questions(session, candidate_id, job_id)

    interview = InterviewSessionModel(
        id=str(uuid.uuid4()),
        job_id=job_id,
        candidate_id=candidate_id,
        questions=[q.model_dump() for q in questions],
        answers=[],
        evaluations=[],
        status="pending",
    )
    session.add(interview)
    await session.commit()

    return interview, candidate.full_name, job.title


async def submit_answer(
    session: AsyncSession,
    session_id: str,
    question_id: str,
    answer: str,
) -> AnswerResponse:
    """
    Saves one answer, evaluates it, and advances interview status.
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

    score, feedback = _evaluate_single_answer(question_item.question, answer, question_item.skill)

    evaluations = list(interview.evaluations or [])
    answers.append(answer)
    evaluations.append({"question_id": question_id, "score": score, "feedback": feedback})

    interview.answers = answers
    interview.evaluations = evaluations

    if len(answers) >= len(interview.questions):
        interview.status = "completed"
    else:
        interview.status = "in_progress"

    await session.commit()

    return AnswerResponse(
        question_id=question_id,
        skill=question_item.skill,
        answer=answer,
        score=score,
        feedback=feedback,
    )


async def evaluate_interview(
    session: AsyncSession,
    session_id: str,
) -> dict[str, Any]:
    """
    Aggregates saved answer evaluations into an interview summary.
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
    for q, ev in zip(questions, interview.evaluations):
        if q.skill not in skill_scores:
            skill_scores[q.skill] = []
        skill_scores[q.skill].append(ev["score"])

    skill_avgs = {s: round(sum(v) / len(v), 4) for s, v in skill_scores.items()}

    strengths = sorted([s for s, sc in skill_avgs.items() if sc >= 0.7], key=lambda s: skill_avgs[s], reverse=True)
    weaknesses = sorted([s for s, sc in skill_avgs.items() if sc < 0.5], key=lambda s: skill_avgs[s])

    if overall_score >= 0.8:
        feedback = "Excellent performance! Strong technical knowledge across most areas."
    elif overall_score >= 0.6:
        feedback = "Good performance. Solid technical foundation with some areas for improvement."
    elif overall_score >= 0.4:
        feedback = "Average performance. Needs improvement in several technical areas."
    else:
        feedback = "Below average performance. Significant gaps in technical knowledge."

    interview.status = "evaluated"
    await session.commit()

    return {
        "session_id": session_id,
        "overall_score": overall_score,
        "skill_scores": skill_avgs,
        "feedback": feedback,
        "strengths": strengths,
        "weaknesses": weaknesses,
    }
