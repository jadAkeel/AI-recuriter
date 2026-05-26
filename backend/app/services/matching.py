from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.job import Job
from app.models.match_result import MatchResult
from app.services.ai_metadata import current_ai_provider_metadata, scoring_version_from_reasoning
from app.services.hybrid_matcher import (
    CROSS_ENCODER_SCORING_FORMULA,
    DEFAULT_WEIGHTS,
    HybridMatchingEngine,
    SENIORITY_YEARS,
    clamp_score,
    compute_cross_encoder_adjusted_score,
    compute_explainable_score,
    compute_seniority_score,
    required_skill_score_cap_from_coverage,
    required_skill_score_cap_reason_from_coverage,
)
from app.services.skill_catalog import SYNONYM_MAP, is_job_skill_name, normalize_skill_name
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)

# Keep legacy functions for backwards compatibility
YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")
LEGACY_QUICK_WEIGHTS = {
    "skill_required": 0.70,
    "skill_optional": 0.20,
    "semantic": 0.0,
    "experience": 0.05,
    "seniority_match": 0.05,
}


def _estimate_years_experience(experience_entries: list[str]) -> float:
    """
    Estimates years of experience from date ranges in parsed CV entries.
    """
    total = 0.0
    for entry in experience_entries:
        found = YEAR_PATTERN.findall(entry)
        if len(found) >= 2:
            start = min(int(y) for y in found)
            end = max(int(y) for y in found)
            total += max(0, end - start)
    return total


def _expand_skills_with_synonyms(skills: list[str]) -> set[str]:
    """
    Expands candidate skills with curated synonyms for legacy matching.
    """
    expanded: set[str] = set()
    for skill in skills:
        skill_lower = normalize_skill_name(skill)
        expanded.add(skill_lower)
        related = SYNONYM_MAP.get(skill_lower, set())
        expanded.update(related)
    return expanded


def _skill_matches_required(
    required_skill: str,
    candidate_set: set[str],
    candidate_expanded: set[str],
) -> bool:
    """
    Checks whether a candidate skill set satisfies one required skill.
    """
    skill_lower = normalize_skill_name(required_skill)
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
    """
    Calculates required and optional skill coverage for candidate-job matching.
    """
    required_skills = _dedupe_skills(required_skills)
    optional_skills = [s for s in _dedupe_skills(optional_skills) if normalize_skill_name(s) not in {normalize_skill_name(r) for r in required_skills}]
    candidate_skills = _dedupe_skills(candidate_skills)
    required_set = {normalize_skill_name(skill) for skill in required_skills}
    optional_set = {normalize_skill_name(skill) for skill in optional_skills}
    candidate_set = {normalize_skill_name(skill) for skill in candidate_skills}
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


def _dedupe_skills(skills: list[str]) -> list[str]:
    """
    Normalizes, filters, and de-duplicates job skill names.
    """
    deduped: list[str] = []
    seen: set[str] = set()
    for skill in skills or []:
        normalized = normalize_skill_name(skill)
        if normalized and normalized not in seen and is_job_skill_name(normalized):
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


def _required_score_cap(required_score: float, has_required_skills: bool) -> float:
    """
    Returns the score cap for a required-skill coverage value.
    """
    return required_skill_score_cap_from_coverage(required_score, has_required_skills)


def _required_score_cap_reason(required_score: float, has_required_skills: bool) -> str:
    """
    Explains the score cap for required-skill coverage.
    """
    return required_skill_score_cap_reason_from_coverage(required_score, has_required_skills)


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
    sorted_hybrid_results = sorted(hybrid_results, key=lambda item: (-item.final_score, item.candidate_id))[:top_k]
    existing_by_candidate: dict[str, MatchResult] = {}
    selected_ids = [item.candidate_id for item in sorted_hybrid_results]
    if selected_ids:
        existing_result = await session.execute(
            select(MatchResult).where(
                MatchResult.job_id == job.id,
                MatchResult.candidate_id.in_(selected_ids),
            )
        )
        existing_by_candidate = {
            match.candidate_id: match for match in existing_result.scalars().all()
        }
    for rank, hybrid_result in enumerate(sorted_hybrid_results, start=1):
        reasoning = hybrid_result.to_dict()
        reasoning["rank"] = rank

        match = existing_by_candidate.get(hybrid_result.candidate_id)
        if match is None:
            match = MatchResult(
                job_id=job.id,
                candidate_id=hybrid_result.candidate_id,
                score=hybrid_result.final_score,
                reasoning=reasoning,
                scoring_version=scoring_version_from_reasoning(reasoning),
                provider_metadata=current_ai_provider_metadata(),
                is_stale=False,
            )
            session.add(match)
        else:
            match.score = hybrid_result.final_score
            match.reasoning = reasoning
            match.scoring_version = scoring_version_from_reasoning(reasoning)
            match.provider_metadata = current_ai_provider_metadata()
            match.is_stale = False
        results.append(match)
    
    await session.commit()
    sorted_results = sorted(results, key=lambda m: (-m.score, m.candidate_id))
    
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

        est_years = skill_data.get("estimated_years", 0) or 0
        years_score = min(1.0, max(0.0, est_years / 10))
        seniority_score = compute_seniority_score(job.seniority, est_years)
        total_required = len(job.required_skills)
        scoring = compute_explainable_score(
            required_score=skill_data["required_score"],
            optional_score=skill_data["optional_score"],
            semantic_score=0.0,
            years_score=years_score,
            seniority_score=seniority_score,
            has_required_skills=total_required > 0,
            weights=LEGACY_QUICK_WEIGHTS,
        )
        quick_score = scoring["final_score"]
        scored_pre.append((cand, skill_data, quick_score))

    scored_pre.sort(key=lambda x: (-x[2], x[0].id))

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
                if cs is not None:
                    cross_scores_map[cand.id] = cs
        except Exception:
            logger.warning("Cross-encoder failed, using quick scores for top candidates")

    # ── Step 3: Compute final scores ──
    staged_results: list[tuple[Candidate, float, dict[str, Any]]] = []
    for cand, skill_data, quick_score in scored_pre:
        est_years = skill_data.get("estimated_years", 0) or 0
        years_score = min(1.0, max(0.0, est_years / 10))
        seniority_score = compute_seniority_score(job.seniority, est_years)
        total_required = len(job.required_skills)
        base_scoring = compute_explainable_score(
            required_score=skill_data["required_score"],
            optional_score=skill_data["optional_score"],
            semantic_score=0.0,
            years_score=years_score,
            seniority_score=seniority_score,
            has_required_skills=total_required > 0,
            weights=LEGACY_QUICK_WEIGHTS,
        )

        cross_score = cross_scores_map.get(cand.id)
        if cross_score is not None:
            cross_weight = DEFAULT_WEIGHTS["cross_encoder"]
            cap = _required_score_cap(skill_data["required_score"], total_required > 0)
            cross_scoring = compute_cross_encoder_adjusted_score(
                base_score=base_scoring["final_score"],
                cross_score=cross_score,
                score_cap=cap,
                cross_weight=cross_weight,
            )
            pre_cap_score = cross_scoring["pre_cap_score"]
            final_score = cross_scoring["final_score"]
        else:
            cross_weight = 0.0
            cross_scoring = {}
            pre_cap_score = base_scoring["pre_cap_score"]
            cap = base_scoring["score_cap"]
            final_score = quick_score

        final_score = round(max(0.0, min(1.0, final_score)), 4)

        if cross_score is not None:
            score_weights = {
                **base_scoring["score_weights"],
                "cross_encoder_adjustment": cross_weight,
            }
            adjustment = cross_scoring["cross_encoder_adjustment"]
            score_contributions = dict(base_scoring["score_contributions"])
            score_penalties = {}
            if adjustment > 0:
                score_contributions["cross_encoder_adjustment"] = adjustment
            elif adjustment < 0:
                score_penalties["cross_encoder_adjustment"] = abs(adjustment)
            scoring_model = "legacy_cross_encoder_adjusted"
            scoring_formula = CROSS_ENCODER_SCORING_FORMULA
        else:
            score_weights = base_scoring["score_weights"]
            score_contributions = base_scoring["score_contributions"]
            score_penalties = base_scoring["score_penalties"]
            scoring_model = "legacy_quick"
            scoring_formula = (
                "0.70 required skills + 0.20 optional skills + 0.05 experience + 0.05 seniority; "
                "then capped by required-skill coverage"
            )
        score_trace = {
            **base_scoring["score_trace"],
            "job_id": job.id,
            "candidate_id": cand.id,
            "cross_encoder_score": round(clamp_score(cross_score), 4) if cross_score is not None else None,
            "cross_encoder_adjustment": cross_scoring.get("cross_encoder_adjustment"),
            "cross_encoder_max_adjustment": cross_scoring.get("cross_encoder_max_adjustment"),
            "pre_cap_score": round(pre_cap_score, 4),
            "score_cap": round(cap, 4),
            "cap_applied": pre_cap_score > cap,
            "final_score": final_score,
        }

        reasoning = {
            "scoring_model": scoring_model,
            "scoring_formula": scoring_formula,
            "score_weights": {k: round(v, 4) for k, v in score_weights.items()},
            "score_contributions": {k: round(v, 4) for k, v in score_contributions.items()},
            "score_penalties": {k: round(v, 4) for k, v in score_penalties.items()},
            "score_trace": score_trace,
            "pre_cap_score": round(pre_cap_score, 4),
            "score_cap": round(cap, 4),
            "score_cap_reason": _required_score_cap_reason(skill_data["required_score"], total_required > 0),
            "cross_encoder_score": round(cross_score, 4) if cross_score is not None else None,
            **skill_data,
            "final_score": final_score,
            "rank": 0,
            "years_score": round(years_score, 4),
            "missing_penalty": 0.0,
            "used_cross_encoder": cross_score is not None,
        }

        staged_results.append((cand, final_score, reasoning))

    staged_results.sort(key=lambda item: (-item[1], item[0].id))
    selected_results = staged_results[:top_k]
    results: list[MatchResult] = []
    existing_by_candidate: dict[str, MatchResult] = {}
    selected_ids = [cand.id for cand, _, _ in selected_results]
    if selected_ids:
        existing_result = await session.execute(
            select(MatchResult).where(
                MatchResult.job_id == job.id,
                MatchResult.candidate_id.in_(selected_ids),
            )
        )
        existing_by_candidate = {
            match.candidate_id: match for match in existing_result.scalars().all()
        }
    for rank, (cand, final_score, reasoning) in enumerate(selected_results, start=1):
        reasoning["rank"] = rank
        match = existing_by_candidate.get(cand.id)
        if match is None:
            match = MatchResult(
                job_id=job.id,
                candidate_id=cand.id,
                score=final_score,
                reasoning=reasoning,
                scoring_version=scoring_version_from_reasoning(reasoning),
                provider_metadata=current_ai_provider_metadata(),
                is_stale=False,
            )
            session.add(match)
        else:
            match.score = final_score
            match.reasoning = reasoning
            match.scoring_version = scoring_version_from_reasoning(reasoning)
            match.provider_metadata = current_ai_provider_metadata()
            match.is_stale = False
        results.append(match)
    await session.commit()
    sorted_results = sorted(results, key=lambda item: (-item.score, item.candidate_id))

    logger.info(
        "Legacy matching complete",
        extra={"job_id": job.id, "matches": len(sorted_results), "total_candidates": len(scored_pre), "cross_encoder_candidates": cross_encoder_count, "top_score": sorted_results[0].score if sorted_results else 0},
    )
    return sorted_results


async def _get_candidate(session: AsyncSession, candidate_id: str) -> Candidate | None:
    """
    Loads one candidate by ID from the database.
    """
    stmt = select(Candidate).where(Candidate.id == candidate_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _get_all_candidates(session: AsyncSession) -> list[Candidate]:
    """
    Loads all candidates available for matching.
    """
    stmt = select(Candidate)
    result = await session.execute(stmt)
    return list(result.scalars().all())
