from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.services.matching import SYNONYM_MAP, _expand_skills_with_synonyms, compute_skill_score
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)


def _analyze_skill_gap(
    required_skills: list[str],
    optional_skills: list[str],
    candidate_skills: list[str],
) -> SkillGapAnalysis:
    candidate_set = set(candidate_skills)
    candidate_expanded = _expand_skills_with_synonyms(candidate_skills)

    def skill_matches(skill: str) -> bool:
        skill_lower = skill.lower().strip()
        if skill_lower in candidate_set:
            return True
        related = SYNONYM_MAP.get(skill_lower, set())
        return bool(related & candidate_expanded)

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


def _generate_strengths_weaknesses(
    skill_gap: SkillGapAnalysis,
    candidate_skills: list[str],
) -> tuple[list[str], list[str]]:
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


async def generate_candidate_report(
    session: AsyncSession,
    job_id: str,
    candidate_id: str,
) -> CandidateReportResponse:
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

    if match is None:
        store = VectorStore(session)
        from app.services.embedding import get_embedding_service
        embedder = get_embedding_service()
        job_emb = (await embedder.embed([job.description]))[0]
        similar = await store.query_similar("candidate", job_emb, top_k=20)
        similarity = next((s for cid, s in similar if cid == candidate_id), 0.5)
    else:
        if isinstance(match.reasoning, dict):
            similarity = (
                match.reasoning.get("similarity")
                or match.reasoning.get("semantic_score")
                or match.reasoning.get("final_score")
                or 0.5
            )
        else:
            similarity = 0.5

    skill_data = compute_skill_score(
        job.required_skills, job.optional_skills, candidate.skills,
        candidate_experience=candidate.experience, job_seniority=job.seniority,
    )
    if candidate.total_years_experience is not None:
        skill_data["estimated_years"] = candidate.total_years_experience

    similarity_score = round(similarity, 4)
    required_score = round(skill_data["required_score"], 4)
    optional_score = round(skill_data["optional_score"], 4)
    est_years = skill_data.get("estimated_years", 0)
    overall_score = round(0.5 * similarity + 0.3 * skill_data["required_score"] + 0.15 * skill_data["optional_score"] + 0.05 * min(1.0, est_years / 10), 4)

    score_breakdown = ScoreBreakdown(
        similarity_score=similarity_score,
        required_skills_score=required_score,
        optional_skills_score=optional_score,
        overall_score=overall_score,
    )

    skill_gap = _analyze_skill_gap(job.required_skills, job.optional_skills, candidate.skills)

    strengths, weaknesses = _generate_strengths_weaknesses(skill_gap, candidate.skills)
    recommendation = _generate_recommendation(score_breakdown, skill_gap)

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
    job_stmt = select(Job).where(Job.id == job_id)
    job_result = await session.execute(job_stmt)
    job = job_result.scalar_one_or_none()
    if job is None:
        raise ValueError("Job not found")

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

    items: list[ComparisonItem] = []
    for cid in candidate_ids:
        candidate = candidates.get(cid)
        if candidate is None:
            continue

        similarity = sim_map.get(cid, 0.5)
        skill_data = compute_skill_score(
            job.required_skills, job.optional_skills, candidate.skills,
            candidate_experience=candidate.experience, job_seniority=job.seniority,
        )
        if candidate.total_years_experience is not None:
            skill_data["estimated_years"] = candidate.total_years_experience
        est_years = skill_data.get("estimated_years", 0)
        overall = round(0.5 * similarity + 0.3 * skill_data["required_score"] + 0.15 * skill_data["optional_score"] + 0.05 * min(1.0, est_years / 10), 4)

        items.append(ComparisonItem(
            candidate_id=cid,
            candidate_name=candidate.full_name,
            overall_score=overall,
            similarity_score=round(similarity, 4),
            skill_score=round(skill_data["skill_score"], 4),
            matched_skills=len(skill_data["matched_required"]) + len(skill_data["matched_optional"]),
            missing_skills=len(skill_data["missing_required"]),
        ))

    items.sort(key=lambda x: x.overall_score, reverse=True)

    return ComparisonResponse(job_id=job_id, job_title=job.title, candidates=items)
