from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.job import Job
from app.models.match_result import MatchResult
from app.services.hybrid_matcher import HybridMatchingEngine, SENIORITY_YEARS
from app.services.skill_catalog import SYNONYM_MAP
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)

# Keep legacy functions for backwards compatibility
YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")


def _estimate_years_experience(experience_entries: list[str]) -> float:
    total = 0.0
    for entry in experience_entries:
        found = YEAR_PATTERN.findall(entry)
        if len(found) >= 2:
            start = min(int(y) for y in found)
            end = max(int(y) for y in found)
            total += max(0, end - start)
    return total


def _expand_skills_with_synonyms(skills: list[str]) -> set[str]:
    expanded: set[str] = set()
    for skill in skills:
        skill_lower = skill.lower().strip()
        expanded.add(skill_lower)
        related = SYNONYM_MAP.get(skill_lower, set())
        expanded.update(related)
    return expanded


def _skill_matches_required(
    required_skill: str,
    candidate_set: set[str],
    candidate_expanded: set[str],
) -> bool:
    skill_lower = required_skill.lower().strip()
    if skill_lower in candidate_set:
        return True
    related = SYNONYM_MAP.get(skill_lower, set())
    return bool(related & candidate_expanded)


def compute_skill_score(
    required_skills: list[str],
    optional_skills: list[str],
    candidate_skills: list[str],
    candidate_experience: list[str] | None = None,
    job_seniority: str | None = None,
) -> dict[str, Any]:
    required_set = set(required_skills)
    optional_set = set(optional_skills)
    candidate_set = set(candidate_skills)
    candidate_expanded = _expand_skills_with_synonyms(candidate_skills)

    matched_required = sorted([
        s for s in required_skills
        if _skill_matches_required(s, candidate_set, candidate_expanded)
    ])
    missing_required = sorted([
        s for s in required_skills
        if not _skill_matches_required(s, candidate_set, candidate_expanded)
    ])
    matched_optional = sorted([
        s for s in optional_skills
        if _skill_matches_required(s, candidate_set, candidate_expanded)
    ])

    required_score = 1.0 if not required_set else len(matched_required) / len(required_set)
    optional_score = 0.0 if not optional_set else len(matched_optional) / len(optional_set)

    skill_score = 0.8 * required_score + 0.2 * optional_score

    result: dict[str, Any] = {
        "skill_score": round(skill_score, 4),
        "matched_required": matched_required,
        "missing_required": missing_required,
        "matched_optional": matched_optional,
        "required_score": round(required_score, 4),
        "optional_score": round(optional_score, 4),
    }

    if candidate_experience is not None and job_seniority:
        est_years = _estimate_years_experience(candidate_experience)
        max_expected = SENIORITY_YEARS.get(job_seniority.lower(), (0, 10))[1]
        result["estimated_years"] = est_years
        result["overqualified"] = est_years > max_expected + 2 if max_expected else False

    return result


async def rank_candidates(
    session: AsyncSession,
    job: Job,
    job_embedding: list[float],
    top_k: int = 10,
    candidates: list[Candidate] | None = None,
    cross_encoder_top_k: int = 20,
    use_hybrid: bool = True,
) -> list[MatchResult]:
    """
    Rank candidates for a job using hybrid matching.
    
    Args:
        session: Database session
        job: Job to match against
        job_embedding: Pre-computed job embedding (for legacy compatibility)
        top_k: Number of top results to return
        candidates: Optional pre-filtered candidates list
        cross_encoder_top_k: Number of candidates to re-rank with cross-encoder
        use_hybrid: Use new hybrid matching engine (recommended)
        
    Returns:
        List of MatchResult sorted by score descending
    """
    if candidates is None:
        candidates = await _get_all_candidates(session)
    if not candidates:
        return []

    if use_hybrid:
        return await _rank_with_hybrid_engine(
            session, job, candidates, top_k, cross_encoder_top_k
        )
    else:
        return await _rank_legacy(
            session, job, job_embedding, candidates, top_k, cross_encoder_top_k
        )


async def _rank_with_hybrid_engine(
    session: AsyncSession,
    job: Job,
    candidates: list[Candidate],
    top_k: int,
    cross_encoder_top_k: int,
) -> list[MatchResult]:
    """Use the new hybrid matching engine."""
    engine = HybridMatchingEngine()
    vector_store = VectorStore(session)
    
    hybrid_results = await engine.match(
        job=job,
        candidates=candidates,
        top_k=top_k,
        enable_cross_encoder=cross_encoder_top_k > 0,
        cross_encoder_top_k=cross_encoder_top_k,
        vector_store=vector_store,
    )
    
    results: list[MatchResult] = []
    from sqlalchemy import delete as sa_delete
    await session.execute(sa_delete(MatchResult).where(MatchResult.job_id == job.id))
    for hybrid_result in hybrid_results:
        reasoning = hybrid_result.to_dict()
        reasoning["rank"] = 0
        
        match = MatchResult(
            job_id=job.id,
            candidate_id=hybrid_result.candidate_id,
            score=hybrid_result.final_score,
            reasoning=reasoning,
        )
        session.add(match)
        results.append(match)
    
    await session.commit()
    
    # Set ranks
    sorted_results = sorted(results, key=lambda m: m.score, reverse=True)
    for i, m in enumerate(sorted_results):
        m.reasoning["rank"] = i + 1
    
    logger.info(
        "Hybrid matching complete",
        extra={
            "job_id": job.id,
            "matches": len(sorted_results),
            "total_candidates": len(candidates),
            "top_score": sorted_results[0].score if sorted_results else 0,
        },
    )
    
    return sorted_results


async def _rank_legacy(
    session: AsyncSession,
    job: Job,
    job_embedding: list[float],
    candidates: list[Candidate],
    top_k: int,
    cross_encoder_top_k: int,
) -> list[MatchResult]:
    """Legacy ranking method for backwards compatibility."""
    # ── Step 1: Compute quick skill + vector score for ALL candidates ──
    scored_pre: list[tuple[Candidate, dict, float]] = []
    for cand in candidates:
        try:
            skill_data = compute_skill_score(
                job.required_skills, job.optional_skills, cand.skills,
                candidate_experience=cand.experience, job_seniority=job.seniority,
            )
        except Exception:
            logger.exception("Skill score computation failed", extra={"candidate_id": cand.id})
            continue

        if cand.total_years_experience is not None:
            skill_data["estimated_years"] = cand.total_years_experience

        years_score = min(1.0, (skill_data.get("estimated_years", 0) / 10))
        missing_penalty = 0.0
        total_required = len(job.required_skills)
        if total_required > 0:
            missing_count = len(skill_data.get("missing_required", []))
            missing_penalty = 0.30 * (missing_count / total_required)

        quick_score = round(
            0.35 * skill_data["required_score"]
            + 0.20 * skill_data["optional_score"]
            + 0.10 * years_score
            - missing_penalty,
            4,
        )
        quick_score = max(0.0, min(1.0, quick_score))
        scored_pre.append((cand, skill_data, quick_score))

    scored_pre.sort(key=lambda x: x[2], reverse=True)

    # ── Step 2: Only run cross-encoder on top candidates ──
    cross_encoder_count = min(cross_encoder_top_k, len(scored_pre)) if cross_encoder_top_k > 0 else 0
    cross_scores_map: dict[str, float] = {}

    if cross_encoder_count > 0:
        top_n = scored_pre[:cross_encoder_count]
        candidate_texts = []
        for cand, _, _ in top_n:
            text_parts = []
            if cand.skills:
                text_parts.append(f"Skills: {', '.join(cand.skills)}")
            if cand.experience:
                text_parts.append(f"Experience: {' '.join(cand.experience[:10])}")
            if cand.education:
                text_parts.append(f"Education: {' '.join(cand.education[:5])}")
            if cand.projects:
                text_parts.append(f"Projects: {' '.join(cand.projects[:5])}")
            candidate_texts.append(". ".join(text_parts) if text_parts else cand.raw_text)

        try:
            from app.services.ollama_cross_encoder import get_ollama_cross_encoder
            cross_encoder = get_ollama_cross_encoder()
            pairs = [(job.description, text) for text in candidate_texts]
            cross_scores = await cross_encoder.predict(pairs)
            for (cand, _, _), cs in zip(top_n, cross_scores):
                cross_scores_map[cand.id] = cs
        except Exception:
            logger.warning("Cross-encoder failed, using quick scores for top candidates")

    # ── Step 3: Compute final scores ──
    results: list[MatchResult] = []
    from sqlalchemy import delete as sa_delete
    await session.execute(sa_delete(MatchResult).where(MatchResult.job_id == job.id))
    for cand, skill_data, quick_score in scored_pre:
        years_score = min(1.0, (skill_data.get("estimated_years", 0) / 10))
        missing_penalty = 0.0
        total_required = len(job.required_skills)
        if total_required > 0:
            missing_count = len(skill_data.get("missing_required", []))
            missing_penalty = 0.30 * (missing_count / total_required)

        cross_score = cross_scores_map.get(cand.id)
        if cross_score is not None:
            final_score = round(
                0.60 * cross_score
                + 0.25 * skill_data["required_score"]
                + 0.10 * skill_data["optional_score"]
                + 0.05 * years_score
                - missing_penalty,
                4,
            )
        else:
            final_score = quick_score

        final_score = max(0.0, min(1.0, final_score))

        reasoning = {
            "cross_encoder_score": round(cross_score, 4) if cross_score is not None else None,
            **skill_data,
            "final_score": final_score,
            "rank": 0,
            "years_score": round(years_score, 4),
            "missing_penalty": round(missing_penalty, 4),
            "used_cross_encoder": cross_score is not None,
        }

        match = MatchResult(
            job_id=job.id,
            candidate_id=cand.id,
            score=final_score,
            reasoning=reasoning,
        )
        session.add(match)
        results.append(match)

    await session.commit()

    sorted_results = sorted(results, key=lambda item: item.score, reverse=True)[:top_k]
    for i, m in enumerate(sorted_results):
        m.reasoning["rank"] = i + 1

    logger.info(
        "Legacy matching complete",
        extra={"job_id": job.id, "matches": len(sorted_results), "total_candidates": len(scored_pre), "cross_encoder_candidates": cross_encoder_count, "top_score": sorted_results[0].score if sorted_results else 0},
    )
    return sorted_results


async def _get_candidate(session: AsyncSession, candidate_id: str) -> Candidate | None:
    stmt = select(Candidate).where(Candidate.id == candidate_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _get_all_candidates(session: AsyncSession) -> list[Candidate]:
    stmt = select(Candidate)
    result = await session.execute(stmt)
    return list(result.scalars().all())
