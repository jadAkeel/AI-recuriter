from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.match_result import MatchResult
from app.models.report import Report
from app.schemas.report import (
    CandidateReportResponse,
    ComparisonItem,
    ComparisonResponse,
    ScoreBreakdown,
    SkillGapAnalysis,
    SkillGapItem,
)
from app.services.hybrid_matcher import (
    BASE_SCORING_FORMULA,
    HybridMatchingEngine,
    compute_explainable_score,
    compute_seniority_score,
    is_current_scoring_reasoning,
    is_interview_blended_reasoning,
)
from app.services.matching import SYNONYM_MAP, _expand_skills_with_synonyms, _skill_matches_required, compute_skill_score
from app.services.project_semantic import compute_junior_project_semantic_bonus
from app.services.skill_catalog import is_job_skill_name, normalize_skill_name, skill_in_text
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)


ACTIVE_LEARNING_PATTERN = re.compile(
    r"(?<!deep\s)(?<!machine\s)(?<!reinforcement\s)(?<!transfer\s)"
    r"(?:currently\s+learning|learning|studying|want(?:ing)?\s+to\s+learn|"
    r"wish(?:ing)?\s+to\s+learn|trying\s+to\s+learn)",
    re.IGNORECASE,
)


def _semantic_similarity_from_match(match: MatchResult | None) -> float | None:
    """
    Reads semantic similarity from a saved match reasoning payload.
    """
    if match is None or not isinstance(match.reasoning, dict):
        return None

    reasoning = match.reasoning
    if "semantic_score" in reasoning and reasoning["semantic_score"] is not None:
        return float(reasoning["semantic_score"])
    if "similarity" in reasoning and reasoning["similarity"] is not None:
        return float(reasoning["similarity"])

    score_breakdown = reasoning.get("score_breakdown")
    if isinstance(score_breakdown, dict) and score_breakdown.get("semantic") is not None:
        return float(score_breakdown["semantic"])
    return None


def _float_or_none(value) -> float | None:
    """
    Converts a value to float when possible.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_float(*values) -> float | None:
    """
    Returns the first value that can be parsed as a float.
    """
    for value in values:
        parsed = _float_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _report_breakdown_values_from_match(
    match: MatchResult | None,
    *,
    similarity_score: float,
    required_score: float,
    optional_score: float,
) -> tuple[float, float, float]:
    """
    Pulls report score breakdown values from saved match reasoning when available.
    """
    if match is None or not isinstance(match.reasoning, dict):
        return similarity_score, required_score, optional_score

    reasoning = match.reasoning
    score_breakdown = reasoning.get("score_breakdown")
    if not isinstance(score_breakdown, dict):
        score_breakdown = {}

    semantic = _first_float(
        reasoning.get("semantic_score"),
        reasoning.get("similarity"),
        score_breakdown.get("semantic"),
    )
    required = _first_float(
        reasoning.get("required_score"),
        score_breakdown.get("skill_required"),
        score_breakdown.get("required_score"),
    )
    optional = _first_float(
        reasoning.get("optional_score"),
        score_breakdown.get("skill_optional"),
        score_breakdown.get("optional_score"),
    )

    return (
        round(semantic, 4) if semantic is not None else similarity_score,
        round(required, 4) if required is not None else required_score,
        round(optional, 4) if optional is not None else optional_score,
    )


async def _fallback_semantic_similarity(
    session: AsyncSession,
    job: Job,
    candidate: Candidate,
    *,
    top_k: int,
) -> float:
    """
    Computes semantic similarity when no saved match score is available.
    """
    project_bonus = compute_junior_project_semantic_bonus(job, candidate)
    if settings.embedding_provider.lower() == "hash":
        return project_bonus

    store = VectorStore(session)
    from app.services.embedding import get_embedding_service

    embedder = get_embedding_service()
    job_emb = (await embedder.embed([job.description]))[0]
    similar = await store.query_similar("candidate", job_emb, top_k=top_k)
    vector_score = next((s for cid, s in similar if cid == candidate.id), 0.0)
    return max(vector_score, project_bonus)


def _context_confirms_active_learning(skill: str, context: str) -> bool:
    """
    Checks whether skill context really describes active learning.
    """
    text = " ".join(str(context or "").lower().split())
    if not text:
        return False

    normalized = normalize_skill_name(skill)
    variants = {skill, normalized, *SYNONYM_MAP.get(normalized, set())}
    variants = {variant for variant in variants if variant}
    for match in ACTIVE_LEARNING_PATTERN.finditer(text):
        window = text[max(0, match.start() - 80): match.end() + 80]
        if any(skill_in_text(variant, window) for variant in variants):
            return True
    return False


def _analyze_skill_gap(
    required_skills: list[str],
    optional_skills: list[str],
    candidate_skills: list[str],
) -> SkillGapAnalysis:
    """
    Builds matched and missing skill gaps for a candidate report.
    """
    required_skills = _filter_report_job_skills(required_skills)
    required_set = {normalize_skill_name(skill) for skill in required_skills}
    optional_skills = _filter_report_job_skills(optional_skills, exclude=required_set)
    candidate_set = {normalize_skill_name(skill) for skill in candidate_skills}
    candidate_expanded = _expand_skills_with_synonyms(candidate_skills)

    def skill_matches(skill: str) -> bool:
        """
        Checks whether one report skill is covered by candidate skills or synonyms.
        """
        return _skill_matches_required(skill, candidate_set, candidate_expanded)

    matched_required = sorted([s for s in required_skills if skill_matches(s)])
    missing_required = sorted([s for s in required_skills if not skill_matches(s)])
    matched_optional = sorted([s for s in optional_skills if skill_matches(s)])

    items: list[SkillGapItem] = []
    for skill in required_skills:
        items.append(SkillGapItem(skill=skill, required=True, matched=skill_matches(skill)))
    for skill in optional_skills:
        items.append(SkillGapItem(skill=skill, required=False, matched=skill_matches(skill)))

    return SkillGapAnalysis(
        matched_required=matched_required,
        missing_required=missing_required,
        matched_optional=matched_optional,
        items=items,
    )


def _filter_report_job_skills(skills: list[str], exclude: set[str] | None = None) -> list[str]:
    """
    Filters and de-duplicates job skills for report calculations.
    """
    result: list[str] = []
    seen: set[str] = set(exclude or set())
    for skill in skills or []:
        normalized = normalize_skill_name(skill)
        if not normalized or normalized in seen or not is_job_skill_name(normalized):
            continue
        seen.add(normalized)
        result.append(skill)
    return result


def _dedupe_report_skills(skills: list[str]) -> list[str]:
    """
    Normalizes and de-duplicates candidate skills for reports.
    """
    result: list[str] = []
    seen: set[str] = set()
    for skill in skills or []:
        normalized = normalize_skill_name(skill)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _candidate_report_skills(candidate: Candidate, job_skills: list[str]) -> list[str]:
    """
    Builds the positive candidate skill list used by reports.
    """
    negative_skills = {normalize_skill_name(skill) for skill in (candidate.negative_skills or [])}
    learning_skills = {normalize_skill_name(skill) for skill in (candidate.learning_skills or [])}
    active_learning_skills: set[str] = set()

    for detail in candidate.skills_detailed or []:
        if not isinstance(detail, dict):
            continue
        status = str(detail.get("status", "")).lower().strip()
        name = str(detail.get("name", "")).strip()
        context = str(detail.get("context", "") or "").strip()
        if status == "learning" and name and _context_confirms_active_learning(name, context):
            active_learning_skills.add(normalize_skill_name(name))

    skills = [
        skill
        for skill in (candidate.skills or [])
        if normalize_skill_name(skill) not in negative_skills
        and normalize_skill_name(skill) not in active_learning_skills
    ]

    for detail in candidate.skills_detailed or []:
        if not isinstance(detail, dict):
            continue
        status = str(detail.get("status", "")).lower().strip()
        name = str(detail.get("name", "")).strip()
        context = str(detail.get("context", "") or "").strip()
        normalized_name = normalize_skill_name(name)
        if (
            name
            and context
            and status != "no_experience"
            and normalized_name not in active_learning_skills
        ):
            skills.append(name)

    evidence_text = " ".join(
        list(candidate.experience or [])
        + list(candidate.projects or [])
        + list(candidate.education or [])
        + [candidate.raw_text or ""]
    ).lower()
    for skill in learning_skills:
        if _context_confirms_active_learning(skill, evidence_text):
            active_learning_skills.add(skill)
    skills = [skill for skill in skills if normalize_skill_name(skill) not in active_learning_skills]

    for skill in job_skills:
        normalized = normalize_skill_name(skill)
        if not normalized or normalized in negative_skills:
            continue
        if normalized in active_learning_skills:
            continue
        if normalized in learning_skills and _context_confirms_active_learning(normalized, evidence_text):
            continue
        evidence_candidates = {skill, normalized, *SYNONYM_MAP.get(normalized, set())}
        if any(skill_in_text(candidate_skill, evidence_text) for candidate_skill in evidence_candidates):
            skills.append(normalized)

    return _dedupe_report_skills(skills)


def _generate_strengths_weaknesses(
    skill_gap: SkillGapAnalysis,
    candidate_skills: list[str],
) -> tuple[list[str], list[str]]:
    """
    Summarizes report strengths and weaknesses from skill gaps.
    """
    strengths = list(skill_gap.matched_required)
    for skill in skill_gap.matched_optional:
        if len(strengths) < 5:
            strengths.append(skill)

    weaknesses = list(skill_gap.missing_required)

    return strengths[:5], weaknesses[:5]


def _generate_recommendation(
    score_breakdown: ScoreBreakdown,
    skill_gap: SkillGapAnalysis,
) -> str:
    """
    Creates the final recruiter recommendation from score and gap data.
    """
    overall = score_breakdown.overall_score

    if overall >= 0.8:
        base = "Highly recommended. Excellent match for the position."
    elif overall >= 0.6:
        base = "Recommended. Good overall fit with some areas for development."
    elif overall >= 0.4:
        base = "Consider with reservations. Candidate meets basic requirements but has notable gaps."
    else:
        base = "Not recommended at this time. Significant gaps in required qualifications."

    if skill_gap.missing_required:
        base += f" Missing key skills: {', '.join(skill_gap.missing_required[:3])}."

    return base


def _append_interview_explanation(recommendation: str, match: MatchResult | None) -> str:
    """
    Adds interview-blended scoring context to the recommendation text.
    """
    if match is None or not isinstance(match.reasoning, dict):
        return recommendation

    reasoning = match.reasoning
    if reasoning.get("interview_analysis_status") != "ready":
        return recommendation

    interview_score = reasoning.get("interview_score")
    cv_score = reasoning.get("cv_match_score")
    if interview_score is None:
        return recommendation

    try:
        interview_pct = round(float(interview_score) * 100)
        if cv_score is not None:
            cv_pct = round(float(cv_score) * 100)
            return (
                f"{recommendation} Overall score includes post-interview analysis "
                f"(CV/job match: {cv_pct}%, interview: {interview_pct}%)."
            )
        return f"{recommendation} Overall score includes post-interview analysis ({interview_pct}%)."
    except (TypeError, ValueError):
        return recommendation


async def generate_candidate_report(
    session: AsyncSession,
    job_id: str,
    candidate_id: str,
    *,
    use_match_score: bool = True,
) -> CandidateReportResponse:
    """
    Generates and stores an explainable report for one candidate and job.
    """
    job_stmt = select(Job).where(Job.id == job_id)
    job_result = await session.execute(job_stmt)
    job = job_result.scalar_one_or_none()

    cand_stmt = select(Candidate).where(Candidate.id == candidate_id)
    cand_result = await session.execute(cand_stmt)
    candidate = cand_result.scalar_one_or_none()

    if job is None or candidate is None:
        raise ValueError("Job or Candidate not found")

    match_stmt = select(MatchResult).where(
        MatchResult.job_id == job_id, MatchResult.candidate_id == candidate_id
    )
    match_result = await session.execute(match_stmt)
    match = match_result.scalar_one_or_none()

    project_bonus = compute_junior_project_semantic_bonus(job, candidate)
    similarity = _semantic_similarity_from_match(match)
    if similarity is None:
        similarity = await _fallback_semantic_similarity(session, job, candidate, top_k=20)
    else:
        similarity = max(similarity, project_bonus)

    candidate_report_skills = _candidate_report_skills(
        candidate,
        list(job.required_skills or []) + list(job.optional_skills or []),
    )

    skill_data = compute_skill_score(
        job.required_skills, job.optional_skills, candidate_report_skills,
        candidate_experience=candidate.experience, job_seniority=job.seniority,
    )
    if candidate.total_years_experience is not None:
        skill_data["estimated_years"] = candidate.total_years_experience

    similarity_score = round(similarity, 4)
    required_score = round(skill_data["required_score"], 4)
    optional_score = round(skill_data["optional_score"], 4)
    reasoning = match.reasoning if match is not None and isinstance(match.reasoning, dict) else {}
    match_is_interview_blended = is_interview_blended_reasoning(reasoning)
    match_is_current = match is not None and is_current_scoring_reasoning(reasoning)
    if match_is_current or match_is_interview_blended:
        similarity_score, required_score, optional_score = _report_breakdown_values_from_match(
            match,
            similarity_score=similarity_score,
            required_score=required_score,
            optional_score=optional_score,
        )
    similarity_score = max(similarity_score, round(project_bonus, 4))
    est_years = skill_data.get("estimated_years", 0) or 0
    years_score = min(1.0, max(0.0, est_years / 10))
    seniority_score = compute_seniority_score(job.seniority, est_years)
    total_required = len(skill_data.get("matched_required", [])) + len(skill_data.get("missing_required", []))
    fallback_scoring = compute_explainable_score(
        required_score=required_score,
        optional_score=optional_score,
        semantic_score=similarity_score,
        years_score=years_score,
        seniority_score=seniority_score,
        has_required_skills=total_required > 0,
    )

    if match is not None and not match_is_current and not match_is_interview_blended:
        previous_scoring_model = reasoning.get("scoring_model") if isinstance(reasoning, dict) else None
        current_match = await HybridMatchingEngine()._compute_match(
            job,
            candidate,
            semantic_score=similarity_score,
        )
        if current_match is not None:
            current_match.reasoning.score_trace["source"] = "report_refresh_stale_match"
            current_match.reasoning.score_trace["previous_scoring_model"] = previous_scoring_model
            match.score = current_match.final_score
            match.reasoning = current_match.to_dict()
            reasoning = match.reasoning
            match_is_current = True
            similarity_score = round(current_match.semantic_score, 4)
            required_score = round(current_match.skill_match.required_score, 4)
            optional_score = round(current_match.skill_match.optional_score, 4)
            logger.info(
                "Refreshed stale match before report generation",
                extra={
                    "job_id": job.id,
                    "candidate_id": candidate.id,
                    "previous_scoring_model": previous_scoring_model,
                    "current_score": current_match.final_score,
                },
            )

    if use_match_score and match is not None and (match_is_current or match_is_interview_blended):
        overall_score = round(float(match.score), 4)
        scoring_model = str(reasoning.get("scoring_model") or "persisted_match")
        scoring_formula = str(
            reasoning.get("scoring_formula")
            or "Overall score was loaded from a saved match result; rerun matching to generate a full formula trace."
        )
        score_weights = reasoning.get("score_weights") if isinstance(reasoning.get("score_weights"), dict) else {}
        score_contributions = (
            reasoning.get("score_contributions")
            if isinstance(reasoning.get("score_contributions"), dict)
            else {}
        )
        score_penalties = reasoning.get("score_penalties") if isinstance(reasoning.get("score_penalties"), dict) else {}
        pre_cap_score = _first_float(reasoning.get("pre_cap_score"))
        score_cap = _first_float(reasoning.get("score_cap"))
        score_cap_reason = reasoning.get("score_cap_reason") if isinstance(reasoning.get("score_cap_reason"), str) else None
        score_trace = reasoning.get("score_trace") if isinstance(reasoning.get("score_trace"), dict) else {}
    else:
        overall_score = fallback_scoring["final_score"]
        scoring_model = "report_fallback_hybrid_v2"
        scoring_formula = BASE_SCORING_FORMULA
        score_weights = fallback_scoring["score_weights"]
        score_contributions = fallback_scoring["score_contributions"]
        score_penalties = fallback_scoring["score_penalties"]
        pre_cap_score = fallback_scoring["pre_cap_score"]
        score_cap = fallback_scoring["score_cap"]
        score_cap_reason = fallback_scoring["score_cap_reason"]
        score_trace = {
            **fallback_scoring["score_trace"],
            "job_id": job.id,
            "candidate_id": candidate.id,
            "source": "report_fallback_no_saved_match",
        }

    score_breakdown = ScoreBreakdown(
        similarity_score=similarity_score,
        required_skills_score=required_score,
        optional_skills_score=optional_score,
        overall_score=overall_score,
        scoring_model=scoring_model,
        scoring_formula=scoring_formula,
        score_weights={k: round(float(v), 4) for k, v in score_weights.items()},
        score_contributions={k: round(float(v), 4) for k, v in score_contributions.items()},
        score_penalties={k: round(float(v), 4) for k, v in score_penalties.items()},
        pre_cap_score=round(pre_cap_score, 4) if pre_cap_score is not None else None,
        score_cap=round(score_cap, 4) if score_cap is not None else None,
        score_cap_reason=score_cap_reason,
        score_trace=score_trace,
    )

    skill_gap = _analyze_skill_gap(job.required_skills, job.optional_skills, candidate_report_skills)

    strengths, weaknesses = _generate_strengths_weaknesses(skill_gap, candidate_report_skills)
    recommendation = _generate_recommendation(score_breakdown, skill_gap)
    recommendation = _append_interview_explanation(recommendation, match)

    report_stmt = select(Report).where(Report.job_id == job_id, Report.candidate_id == candidate_id)
    report_result = await session.execute(report_stmt)
    report = report_result.scalar_one_or_none()
    if report is None:
        report = Report(id=str(uuid.uuid4()), job_id=job_id, candidate_id=candidate_id, overall_score=overall_score,
                        score_breakdown={}, skill_gap={}, strengths=[], weaknesses=[], recommendation="")
        session.add(report)
    report.overall_score = overall_score
    report.score_breakdown = score_breakdown.model_dump()
    report.skill_gap = skill_gap.model_dump()
    report.strengths = strengths
    report.weaknesses = weaknesses
    report.recommendation = recommendation
    await session.commit()

    return CandidateReportResponse(
        job_title=job.title,
        candidate_name=candidate.full_name,
        score_breakdown=score_breakdown,
        skill_gap=skill_gap,
        strengths=strengths,
        weaknesses=weaknesses,
        recommendation=recommendation,
    )


async def compare_candidates(
    session: AsyncSession,
    job_id: str,
    candidate_ids: list[str],
) -> ComparisonResponse:
    """
    Builds a score comparison for selected candidates on one job.
    """
    job_stmt = select(Job).where(Job.id == job_id)
    job_result = await session.execute(job_stmt)
    job = job_result.scalar_one_or_none()
    if job is None:
        raise ValueError("Job not found")

    if settings.embedding_provider.lower() == "hash":
        sim_map: dict[str, float] = {}
    else:
        from app.services.embedding import get_embedding_service

        embedder = get_embedding_service()
        store = VectorStore(session)
        job_emb = (await embedder.embed([job.description]))[0]
        similar = await store.query_similar("candidate", job_emb, top_k=50)
        sim_map = dict(similar)

    if not candidate_ids:
        return ComparisonResponse(job_id=job_id, job_title=job.title, candidates=[])

    cand_stmt = select(Candidate).where(Candidate.id.in_(candidate_ids))
    cand_result = await session.execute(cand_stmt)
    candidates = {candidate.id: candidate for candidate in cand_result.scalars().all()}

    match_result = await session.execute(
        select(MatchResult).where(
            MatchResult.job_id == job_id,
            MatchResult.candidate_id.in_(candidate_ids),
        )
    )
    matches = {match.candidate_id: match for match in match_result.scalars().all()}

    items: list[ComparisonItem] = []
    for cid in candidate_ids:
        candidate = candidates.get(cid)
        if candidate is None:
            continue

        similarity = max(sim_map.get(cid, 0.0), compute_junior_project_semantic_bonus(job, candidate))
        candidate_report_skills = _candidate_report_skills(
            candidate,
            list(job.required_skills or []) + list(job.optional_skills or []),
        )
        skill_data = compute_skill_score(
            job.required_skills, job.optional_skills, candidate_report_skills,
            candidate_experience=candidate.experience, job_seniority=job.seniority,
        )
        if candidate.total_years_experience is not None:
            skill_data["estimated_years"] = candidate.total_years_experience
        est_years = skill_data.get("estimated_years", 0) or 0
        years_score = min(1.0, max(0.0, est_years / 10))
        seniority_score = compute_seniority_score(job.seniority, est_years)
        total_required = len(skill_data.get("matched_required", [])) + len(skill_data.get("missing_required", []))
        fallback_scoring = compute_explainable_score(
            required_score=skill_data["required_score"],
            optional_score=skill_data["optional_score"],
            semantic_score=similarity,
            years_score=years_score,
            seniority_score=seniority_score,
            has_required_skills=total_required > 0,
        )
        overall = fallback_scoring["final_score"]
        match = matches.get(cid)
        if match is not None:
            reasoning = match.reasoning if isinstance(match.reasoning, dict) else {}
            if not is_current_scoring_reasoning(reasoning) and not is_interview_blended_reasoning(reasoning):
                previous_scoring_model = reasoning.get("scoring_model") if isinstance(reasoning, dict) else None
                current_match = await HybridMatchingEngine()._compute_match(
                    job,
                    candidate,
                    semantic_score=similarity,
                )
                if current_match is not None:
                    current_match.reasoning.score_trace["source"] = "compare_refresh_stale_match"
                    current_match.reasoning.score_trace["previous_scoring_model"] = previous_scoring_model
                    match.score = current_match.final_score
                    match.reasoning = current_match.to_dict()
                    reasoning = match.reasoning
                    similarity = round(current_match.semantic_score, 4)
                    skill_data["skill_score"] = current_match.skill_match.skill_score
                    skill_data["matched_required"] = [m.skill for m in current_match.skill_match.matched_required]
                    skill_data["matched_optional"] = [m.skill for m in current_match.skill_match.matched_optional]
                    skill_data["missing_required"] = current_match.skill_match.missing_required
                    logger.info(
                        "Refreshed stale match before comparison",
                        extra={
                            "job_id": job.id,
                            "candidate_id": candidate.id,
                            "previous_scoring_model": previous_scoring_model,
                            "current_score": current_match.final_score,
                        },
                    )
            overall = round(float(match.score), 4)
            persisted_similarity = _semantic_similarity_from_match(match)
            if persisted_similarity is not None:
                similarity = persisted_similarity
            matched_required = reasoning.get("matched_required")
            matched_optional = reasoning.get("matched_optional")
            missing_required = reasoning.get("missing_required")
            if isinstance(matched_required, list) and isinstance(matched_optional, list):
                matched_count = len(matched_required) + len(matched_optional)
            else:
                matched_count = len(skill_data["matched_required"]) + len(skill_data["matched_optional"])
            if isinstance(missing_required, list):
                missing_count = len(missing_required)
            else:
                missing_count = len(skill_data["missing_required"])
            skill_score = _float_or_none(reasoning.get("skill_score"))
            if skill_score is None:
                skill_score = skill_data["skill_score"]
        else:
            matched_count = len(skill_data["matched_required"]) + len(skill_data["matched_optional"])
            missing_count = len(skill_data["missing_required"])
            skill_score = skill_data["skill_score"]

        items.append(ComparisonItem(
            candidate_id=cid,
            candidate_name=candidate.full_name,
            overall_score=overall,
            similarity_score=round(similarity, 4),
            skill_score=round(skill_score, 4),
            matched_skills=matched_count,
            missing_skills=missing_count,
        ))

    items.sort(key=lambda x: x.overall_score, reverse=True)
    if any(match is not None for match in matches.values()):
        await session.commit()

    return ComparisonResponse(job_id=job_id, job_title=job.title, candidates=items)
