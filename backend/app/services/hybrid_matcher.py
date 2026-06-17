"""
Hybrid Matching Engine for CV-to-Job matching.

This module provides a sophisticated matching system that combines:
- ESCO-based skill matching with semantic understanding
- Vector embeddings for semantic similarity
- Structured scoring (experience, education, seniority)
- Cross-encoder re-ranking for top candidates
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.job import Job
from app.services.candidate_text import build_candidate_embedding_text_from_candidate
from app.services.esco_service import ESCOSkillService, get_esco_service, NormalizedSkill
from app.services.embedding import (
    EmbeddingProvider,
    embedding_metadata_for_text,
    get_embedding_service,
    is_embedding_quality_text,
    validate_embedding_vector,
)
from app.services.skill_catalog import (
    SYNONYM_MAP,
    build_skill_pattern,
    is_job_skill_name,
    normalize_skill_name,
)
from app.services.project_semantic import (
    compute_junior_evidence_year_credit,
    compute_junior_project_semantic_bonus,
    is_junior_job,
)
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)

BASE_SCORE_KEYS = (
    "skill_required",
    "skill_optional",
    "semantic",
    "experience",
    "seniority_match",
)

CURRENT_SCORING_MODEL = "hybrid_v2"
CURRENT_CROSS_ENCODER_SCORING_MODEL = "hybrid_v2_cross_encoder_adjusted"
CURRENT_SCORING_MODELS = {
    CURRENT_SCORING_MODEL,
    CURRENT_CROSS_ENCODER_SCORING_MODEL,
}
SCORING_VERSION = "2026-05-19"
# Keep the LLM reranker advisory: current regression data uses it only as a
# bounded score adjustment, not as a replacement for deterministic skill fit.
CROSS_ENCODER_MAX_ADJUSTMENT = 0.05

# Score weights for hybrid matching. Base weights intentionally sum to 1.0 so
# the final score is directly explainable as weighted evidence.
DEFAULT_WEIGHTS = {
    "skill_required": 0.55,
    "skill_optional": 0.20,
    "semantic": 0.15,
    "experience": 0.05,
    "seniority_match": 0.05,
    "cross_encoder": 0.25,  # Optional reranker; it should not dominate skills.
}

BASE_SCORING_FORMULA = (
    "0.55 required skills + 0.20 optional skills + 0.15 semantic fit "
    "+ 0.05 experience + 0.05 seniority; then capped by required-skill coverage"
)
CROSS_ENCODER_SCORING_FORMULA = (
    f"{BASE_SCORING_FORMULA}; optional LLM rerank applies only a bounded "
    f"+/-{CROSS_ENCODER_MAX_ADJUSTMENT * 100:.0f} point adjustment"
)


def clamp_score(value: float | int | None) -> float:
    """
    Bounds a score-like value to the 0.0 to 1.0 range.
    """
    try:
        parsed = float(value if value is not None else 0.0)
    except (TypeError, ValueError):
        parsed = 0.0
    return max(0.0, min(1.0, parsed))


def normalized_base_score_weights(weights: dict[str, float] | None = None) -> dict[str, float]:
    """
    Normalizes the base matching weights so scoring contributions add up cleanly.
    """
    source = {**DEFAULT_WEIGHTS, **(weights or {})}
    raw = {key: max(0.0, float(source.get(key, 0.0))) for key in BASE_SCORE_KEYS}
    total = sum(raw.values())
    if total <= 0.0:
        raw = {key: DEFAULT_WEIGHTS[key] for key in BASE_SCORE_KEYS}
        total = sum(raw.values())
    return {key: raw[key] / total for key in BASE_SCORE_KEYS}


def required_skill_score_cap_from_coverage(required_score: float, has_required_skills: bool) -> float:
    """
    Chooses the maximum allowed score from required-skill coverage.
    """
    required_score = clamp_score(required_score)
    if not has_required_skills:
        return 1.0
    return 0.3 + 0.7 * required_score


def required_skill_score_cap_reason_from_coverage(required_score: float, has_required_skills: bool) -> str:
    """
    Explains why a required-skill coverage cap was applied.
    """
    required_score = clamp_score(required_score)
    if not has_required_skills:
        return "No required skills were defined for this job."
    if required_score >= 1.0:
        return "Required-skill coverage is complete, so no required-skill cap was applied."
    cap_pct = round((0.3 + 0.7 * required_score) * 100)
    req_pct = round(required_score * 100)
    return f"Required-skill coverage is {req_pct}%, so the overall score is capped at {cap_pct}%."


def is_interview_blended_reasoning(reasoning: dict[str, Any] | None) -> bool:
    """
    Checks whether saved match reasoning already includes interview blending.
    """
    if not isinstance(reasoning, dict):
        return False
    return (
        reasoning.get("interview_analysis_status") == "ready"
        and reasoning.get("interview_score") is not None
    )


def is_current_scoring_reasoning(reasoning: dict[str, Any] | None) -> bool:
    """
    Checks whether saved match reasoning matches the current scoring model and weights.
    """
    if not isinstance(reasoning, dict):
        return False
    if is_interview_blended_reasoning(reasoning):
        return True
    if reasoning.get("scoring_model") not in CURRENT_SCORING_MODELS:
        return False

    weights = reasoning.get("score_weights")
    if not isinstance(weights, dict):
        return False

    expected = normalized_base_score_weights(DEFAULT_WEIGHTS)
    for key, expected_value in expected.items():
        try:
            actual = float(weights.get(key))
        except (TypeError, ValueError):
            return False
        if abs(actual - expected_value) > 0.0001:
            return False
    return True


def semantic_score_from_reasoning(reasoning: dict[str, Any] | None) -> float | None:
    """
    Reads the semantic similarity score from old or current reasoning payloads.
    """
    if not isinstance(reasoning, dict):
        return None
    for key in ("semantic_score", "similarity"):
        if reasoning.get(key) is not None:
            return clamp_score(reasoning[key])
    score_breakdown = reasoning.get("score_breakdown")
    if isinstance(score_breakdown, dict) and score_breakdown.get("semantic") is not None:
        return clamp_score(score_breakdown["semantic"])
    return None


def compute_cross_encoder_adjusted_score(
    *,
    base_score: float,
    cross_score: float,
    score_cap: float,
    cross_weight: float | None = None,
) -> dict[str, float]:
    """
    Applies a small bounded cross-encoder adjustment to the base match score.
    """
    safe_base = clamp_score(base_score)
    safe_cross = clamp_score(cross_score)
    safe_cap = clamp_score(score_cap)
    weight = clamp_score(cross_weight if cross_weight is not None else DEFAULT_WEIGHTS["cross_encoder"])
    weighted_delta = weight * (safe_cross - safe_base)
    adjustment = max(-CROSS_ENCODER_MAX_ADJUSTMENT, min(CROSS_ENCODER_MAX_ADJUSTMENT, weighted_delta))
    pre_cap_score = max(0.0, min(1.0, safe_base + adjustment))
    final_score = min(pre_cap_score, safe_cap)
    return {
        "base_score": round(safe_base, 4),
        "cross_encoder_score": round(safe_cross, 4),
        "cross_encoder_weight": round(weight, 4),
        "cross_encoder_weighted_delta": round(weighted_delta, 4),
        "cross_encoder_adjustment": round(adjustment, 4),
        "cross_encoder_max_adjustment": CROSS_ENCODER_MAX_ADJUSTMENT,
        "pre_cap_score": round(pre_cap_score, 4),
        "score_cap": round(safe_cap, 4),
        "final_score": round(final_score, 4),
    }


def compute_seniority_score(job_seniority: str | None, candidate_years: float | None) -> float:
    """
    Scores how well candidate experience fits the job seniority level.
    """
    job_seniority = (job_seniority or "").lower()
    if not job_seniority:
        return 0.5
    if candidate_years is None:
        return 0.5

    expected_range = SENIORITY_YEARS.get(job_seniority, (0, 10))
    min_years, max_years = expected_range

    if min_years <= candidate_years <= max_years:
        return 1.0
    if candidate_years < min_years:
        ratio = candidate_years / min_years if min_years > 0 else 0.5
        return max(0.0, min(0.5, ratio * 0.5))

    excess = candidate_years - max_years
    penalty = min(0.15, excess * 0.05)
    return max(0.5, 1.0 - penalty)


def compute_explainable_score(
    *,
    required_score: float,
    optional_score: float,
    semantic_score: float,
    years_score: float,
    seniority_score: float,
    has_required_skills: bool,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Combines skill, semantic, experience, and seniority signals into an explainable
    score.
    """
    normalized_weights = normalized_base_score_weights(weights)
    raw_scores = {
        "skill_required": clamp_score(required_score),
        "skill_optional": clamp_score(optional_score),
        "semantic": clamp_score(semantic_score),
        "experience": clamp_score(years_score),
        "seniority_match": clamp_score(seniority_score),
    }
    contributions = {
        key: normalized_weights[key] * raw_scores[key]
        for key in BASE_SCORE_KEYS
    }
    pre_cap_score = sum(contributions.values())
    cap = required_skill_score_cap_from_coverage(raw_scores["skill_required"], has_required_skills)
    final_score = min(pre_cap_score, cap)
    return {
        "final_score": round(final_score, 4),
        "pre_cap_score": round(pre_cap_score, 4),
        "score_cap": round(cap, 4),
        "score_cap_reason": required_skill_score_cap_reason_from_coverage(
            raw_scores["skill_required"], has_required_skills
        ),
        "score_weights": {key: round(value, 4) for key, value in normalized_weights.items()},
        "score_contributions": {key: round(value, 4) for key, value in contributions.items()},
        "score_penalties": {},
        "score_trace": {
            "scoring_model": CURRENT_SCORING_MODEL,
            "scoring_version": SCORING_VERSION,
            "raw_scores": {key: round(value, 4) for key, value in raw_scores.items()},
            "weights_total": round(sum(normalized_weights.values()), 4),
            "pre_cap_score": round(pre_cap_score, 4),
            "score_cap": round(cap, 4),
            "cap_applied": pre_cap_score > cap,
            "final_score": round(final_score, 4),
            "rounding": "Scores are rounded to 4 decimals before API serialization.",
        },
    }

# Seniority level to years mapping
SENIORITY_YEARS = {
    "junior": (0, 2),
    "mid": (2, 5),
    "senior": (5, 10),
    "lead": (8, 15),
    "principal": (10, 20),
    "staff": (10, 20),
}

HARD_NEGATION_SKILL_CONTEXT = re.compile(
    r"(?:don't\s+know|do\s+not\s+know|no\s+experience|not\s+experienced|never\s+used|"
    r"haven't\s+used|not\s+familiar|don't\s+have|do\s+not\s+have|no\s+knowledge)",
    re.IGNORECASE,
)

NON_EVIDENCE_SKILL_CONTEXT = re.compile(
    r"(?:don't\s+know|do\s+not\s+know|no\s+experience|not\s+experienced|never\s+used|"
    r"haven't\s+used|not\s+familiar|don't\s+have|do\s+not\s+have|no\s+knowledge|"
    r"currently\s+learning|want(?:ing)?\s+to\s+learn|wish(?:ing)?\s+to\s+learn|"
    r"trying\s+to\s+learn|studying)",
    re.IGNORECASE,
)

BROAD_SKILL_TERMS = {
    "api",
    "automation",
    "backend",
    "backend api",
    "c# backend",
    "cloud computing",
    "container orchestration",
    "containerization",
    "containers",
    "frontend",
    "infrastructure as code",
    "java backend",
    "javascript runtime",
    "mobile development",
    "nosql",
    "python web",
    "rdbms",
    "relational database",
    "rest api",
    "rest apis",
    "restful api",
    "restful apis",
    "restful api development",
    "ui development",
    "web development",
}


@dataclass
class SkillMatch:
    """Represents a matched skill with details."""
    skill: str
    normalized: NormalizedSkill | None = None
    match_type: str = "exact"  # exact, synonym, related, cluster
    confidence: float = 1.0
    years: float | None = None
    level: str | None = None


@dataclass
class SkillMatchResult:
    """Result of skill matching between job and candidate."""
    matched_required: list[SkillMatch] = field(default_factory=list)
    matched_optional: list[SkillMatch] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    skill_score: float = 0.0
    required_score: float = 0.0
    optional_score: float = 0.0
    esco_coverage: float = 0.0  # % of skills found in ESCO
    rag_matched_count: int = 0
    rag_enriched_skills: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        """
        Serializes this object into a plain dictionary.
        """
        return {
            "matched_required": [
                {"skill": m.skill, "match_type": m.match_type, "confidence": m.confidence}
                for m in self.matched_required
            ],
            "matched_optional": [
                {"skill": m.skill, "match_type": m.match_type, "confidence": m.confidence}
                for m in self.matched_optional
            ],
            "missing_required": self.missing_required,
            "skill_score": round(self.skill_score, 4),
            "required_score": round(self.required_score, 4),
            "optional_score": round(self.optional_score, 4),
            "esco_coverage": round(self.esco_coverage, 4),
            "rag_matched_count": self.rag_matched_count,
            "rag_enriched_skills": self.rag_enriched_skills,
        }


@dataclass
class MatchReasoning:
    """Detailed reasoning for a match result."""
    scoring_model: str = "hybrid"
    scoring_formula: str = ""
    score_breakdown: dict[str, float] = field(default_factory=dict)
    score_weights: dict[str, float] = field(default_factory=dict)
    score_contributions: dict[str, float] = field(default_factory=dict)
    score_penalties: dict[str, float] = field(default_factory=dict)
    score_trace: dict[str, Any] = field(default_factory=dict)
    pre_cap_score: float = 0.0
    score_cap: float = 1.0
    score_cap_reason: str = ""
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    rag_matched_count: int = 0
    rag_enriched_skills: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    overqualified: bool = False
    seniority_match: str = "unknown"  # exact, under, over
    recommendations: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        """
        Serializes this object into a plain dictionary.
        """
        return {
            "scoring_model": self.scoring_model,
            "scoring_formula": self.scoring_formula,
            "score_breakdown": {k: round(v, 4) for k, v in self.score_breakdown.items()},
            "score_weights": {k: round(v, 4) for k, v in self.score_weights.items()},
            "score_contributions": {k: round(v, 4) for k, v in self.score_contributions.items()},
            "score_penalties": {k: round(v, 4) for k, v in self.score_penalties.items()},
            "score_trace": self.score_trace,
            "pre_cap_score": round(self.pre_cap_score, 4),
            "score_cap": round(self.score_cap, 4),
            "score_cap_reason": self.score_cap_reason,
            "matched_skills": self.matched_skills,
            "missing_skills": self.missing_skills,
            "rag_matched_count": self.rag_matched_count,
            "rag_enriched_skills": self.rag_enriched_skills,
            "strengths": self.strengths,
            "gaps": self.gaps,
            "overqualified": self.overqualified,
            "seniority_match": self.seniority_match,
            "recommendations": self.recommendations,
        }


@dataclass
class HybridMatchResult:
    """Complete match result from hybrid matching engine."""
    candidate_id: str
    final_score: float
    skill_match: SkillMatchResult
    semantic_score: float
    cross_encoder_score: float | None
    reasoning: MatchReasoning
    estimated_years: float | None = None
    years_score: float = 0.0
    
    def to_dict(self) -> dict[str, Any]:
        """
        Serializes this object into a plain dictionary.
        """
        sm = self.skill_match
        reas = self.reasoning
        return {
            "candidate_id": self.candidate_id,
            "final_score": round(self.final_score, 4),
            "skill_score": round(sm.skill_score, 4),
            "required_score": round(sm.required_score, 4),
            "optional_score": round(sm.optional_score, 4),
            "matched_required": [m.skill for m in sm.matched_required],
            "missing_required": sm.missing_required,
            "matched_optional": [m.skill for m in sm.matched_optional],
            "cross_encoder_score": round(self.cross_encoder_score, 4) if self.cross_encoder_score is not None else None,
            "semantic_score": round(self.semantic_score, 4),
            "esco_coverage": round(sm.esco_coverage, 4),
            "scoring_model": reas.scoring_model,
            "scoring_formula": reas.scoring_formula,
            "score_breakdown": {k: round(v, 4) for k, v in reas.score_breakdown.items()},
            "score_weights": {k: round(v, 4) for k, v in reas.score_weights.items()},
            "score_contributions": {k: round(v, 4) for k, v in reas.score_contributions.items()},
            "score_penalties": {k: round(v, 4) for k, v in reas.score_penalties.items()},
            "score_trace": reas.score_trace,
            "pre_cap_score": round(reas.pre_cap_score, 4),
            "score_cap": round(reas.score_cap, 4),
            "score_cap_reason": reas.score_cap_reason,
            "matched_skills": reas.matched_skills,
            "missing_skills": reas.missing_skills,
            "rag_matched_count": reas.rag_matched_count,
            "rag_enriched_skills": reas.rag_enriched_skills,
            "strengths": reas.strengths,
            "gaps": reas.gaps,
            "overqualified": reas.overqualified,
            "seniority_match": reas.seniority_match,
            "recommendations": reas.recommendations,
            "used_cross_encoder": self.cross_encoder_score is not None,
            "estimated_years": self.estimated_years,
            "years_score": round(self.years_score, 4),
            "rank": 0,
        }


class HybridMatchingEngine:
    """
    Main matching orchestrator with hybrid scoring.
    
    Combines multiple signals:
    - ESCO-based skill matching
    - Semantic similarity via embeddings
    - Structured factors (experience, education, seniority)
    - Cross-encoder re-ranking
    """
    
    def __init__(
        self,
        esco_service: ESCOSkillService | None = None,
        embedding_service: EmbeddingProvider | None = None,
        weights: dict[str, float] | None = None,
    ):
        """
        Initializes the hybrid matching engine with ESCO, embeddings, and weights.
        """
        self.esco = esco_service or get_esco_service()
        self.embedder = embedding_service or get_embedding_service()
        self.weights = {**DEFAULT_WEIGHTS, **(weights or {})}
        self._historical_feedback: set[tuple[str, str]] = set()
    
    async def match(
        self,
        job: Job,
        candidates: list[Candidate],
        top_k: int = 10,
        enable_cross_encoder: bool = True,
        cross_encoder_top_k: int = 0,
        vector_store: VectorStore | None = None,
        rag_session: AsyncSession | None = None,
    ) -> list[HybridMatchResult]:
        """
        Execute full matching pipeline.
        
        Args:
            job: Job to match against
            candidates: List of candidates to evaluate
            top_k: Number of top results to return
            enable_cross_encoder: Whether to use cross-encoder re-ranking
            cross_encoder_top_k: How many top candidates to re-rank
            vector_store: Optional VectorStore for cached embeddings
            
        Returns:
            List of HybridMatchResult sorted by final_score descending
        """
        if not candidates:
            logger.info("No candidates to match")
            return []
        
        logger.info(
            "Matching pipeline started",
            extra={
                "job_id": job.id,
                "job_title": job.title,
                "candidate_count": len(candidates),
                "cross_encoder": enable_cross_encoder,
            },
        )
        
        rag_session = rag_session or (vector_store.session if vector_store is not None else None)
        await self._load_historical_feedback(job, candidates, rag_session)

        # Step 1: Pre-compute job embedding once (not per candidate)
        job_text = f"{job.title or ''} {job.description}"
        logger.info("Step 1/4: Computing job embedding...")
        semantic_enabled = settings.embedding_provider.lower() != "hash"
        if not semantic_enabled:
            job_embedding_vec = None
            logger.info("Semantic scoring disabled for hash embedding provider")
        elif not is_embedding_quality_text(job_text):
            job_embedding_vec = None
            logger.warning("Job text too short for semantic embedding", extra={"job_id": job.id})
        else:
            try:
                job_embedding_vec = (await self.embedder.embed([job_text]))[0]
                validate_embedding_vector(job_embedding_vec)
                logger.info("Job embedding computed", extra={"dimension": len(job_embedding_vec)})
            except Exception as e:
                logger.warning("Job embedding failed; semantic score disabled", extra={"error_type": type(e).__name__})
                job_embedding_vec = None

        # Step 2: Batch-compute candidate embeddings with caching
        logger.info("Step 2/4: Computing candidate embeddings (batch)...")
        candidate_texts = [self._build_candidate_text(c) for c in candidates]
        
        # Try to load cached embeddings from vector store
        candidate_embeddings: list[list[float] | None] = [None] * len(candidates)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []
        
        if vector_store is not None:
            for i, candidate in enumerate(candidates):
                emb = await self._get_cached_embedding(vector_store, candidate)
                if emb is not None:
                    candidate_embeddings[i] = emb
                else:
                    if is_embedding_quality_text(candidate_texts[i]):
                        uncached_indices.append(i)
                        uncached_texts.append(candidate_texts[i])
            if uncached_indices:
                logger.info("Cache miss for %d/%d candidates, computing embeddings...",
                            len(uncached_indices), len(candidates))
        else:
            for i, text in enumerate(candidate_texts):
                if is_embedding_quality_text(text):
                    uncached_indices.append(i)
                    uncached_texts.append(text)

        if job_embedding_vec is not None and uncached_texts:
            try:
                batch_embeddings = await self.embedder.embed(uncached_texts)
                for idx, emb in zip(uncached_indices, batch_embeddings):
                    candidate_embeddings[idx] = emb
                # Batch-store embeddings in vector store (single commit)
                if vector_store is not None:
                    for idx, emb in zip(uncached_indices, batch_embeddings):
                        await vector_store.upsert_embedding(
                            entity_type="candidate",
                            entity_id=candidates[idx].id,
                            embedding=emb,
                            metadata=embedding_metadata_for_text(candidate_texts[idx]),
                            commit=False,
                        )
                    await vector_store.session.commit()
                logger.info("Candidate embeddings computed", extra={"count": len(batch_embeddings)})
            except Exception as e:
                logger.warning("Batch embedding failed", extra={"error": str(e)})
                for idx in uncached_indices:
                    candidate_embeddings[idx] = None
        
        # Step 3: Compute skill and semantic scores for all candidates (vectorized)
        import numpy as np
        results: list[HybridMatchResult] = []
        
        logger.info("Step 3/4: Computing skill & semantic scores for %d candidates...", len(candidates))
        
        if job_embedding_vec is not None:
            job_vec = np.array(job_embedding_vec, dtype=np.float32)
            job_norm = np.linalg.norm(job_vec)
            if job_norm == 0:
                job_norm = 1.0
            
            # Vectorized cosine similarity across all candidates at once
            valid_indices: list[int] = []
            valid_vectors: list[np.ndarray] = []
            for i, emb in enumerate(candidate_embeddings):
                if emb is not None and len(emb) == len(job_embedding_vec):
                    valid_indices.append(i)
                    valid_vectors.append(np.array(emb, dtype=np.float32))
            
            if valid_vectors:
                vectors = np.stack(valid_vectors)
                norms = np.linalg.norm(vectors, axis=1)
                norms[norms == 0] = 1.0
                similarities = np.dot(vectors, job_vec) / (job_norm * norms)
                similarities = np.clip(similarities, 0.0, 1.0)
                
                semantic_scores: dict[int, float] = {}
                for v, sim in zip(valid_indices, similarities):
                    semantic_scores[v] = float(sim)
            else:
                semantic_scores = {}
        else:
            semantic_scores = {}

        for i, candidate in enumerate(candidates):
            semantic_score = semantic_scores.get(i, 0.0)
            result = await self._compute_match(job, candidate, semantic_score, rag_session=rag_session)
            if result:
                results.append(result)
        
        # Sort by initial score
        results.sort(key=lambda r: (-r.final_score, r.candidate_id))
        
        # Cross-encoder re-ranking for top candidates
        if enable_cross_encoder and cross_encoder_top_k > 0:
            top_n = min(cross_encoder_top_k, len(results))
            logger.info("Step 4/4: Cross-encoder re-ranking top %d candidates...", top_n)
            cross_scores = await self._cross_encoder_rerank(job, [r.candidate_id for r in results[:top_n]], candidates)
            
            for result in results[:top_n]:
                if result.candidate_id in cross_scores:
                    cross_score = cross_scores[result.candidate_id]
                    base_score = result.final_score
                    result.cross_encoder_score = cross_score
                    
                    # Recompute final score with cross-encoder
                    result.final_score = self._compute_final_score_with_cross_encoder(
                        result, cross_score
                    )
                    self._apply_cross_encoder_explanation(result, cross_score, base_score)
                    logger.info(
                        "Cross-encoder adjustment applied",
                        extra={
                            "job_id": job.id,
                            "candidate_id": result.candidate_id,
                            "base_score": round(base_score, 4),
                            "cross_encoder_score": round(clamp_score(cross_score), 4),
                            "adjustment": result.reasoning.score_trace.get("cross_encoder_adjustment"),
                            "final_score": result.final_score,
                        },
                    )
        
        # Final sort
        results.sort(key=lambda r: (-r.final_score, r.candidate_id))
        
        top_results = results[:top_k]
        if top_results:
            logger.info(
                "Matching complete",
                extra={
                    "job_id": job.id,
                    "top_score": top_results[0].final_score,
                    "top_candidate": top_results[0].candidate_id,
                    "results_count": len(top_results),
                    "cross_encoder_used": enable_cross_encoder and cross_encoder_top_k > 0,
                },
            )
        else:
            logger.warning("Matching complete â€” no candidates scored above zero")
        
        return top_results
    
    async def _compute_match(
        self,
        job: Job,
        candidate: Candidate,
        semantic_score: float = 0.0,
        rag_session: AsyncSession | None = None,
    ) -> HybridMatchResult | None:
        """Compute match between a job and candidate."""
        try:
            if rag_session is not None and not self._historical_feedback:
                await self._load_historical_feedback(job, [candidate], rag_session)
            # Skill matching
            skill_result = await self._compute_skill_match(job, candidate, rag_session=rag_session)
            
            # Estimated years for frontend compatibility
            estimated_years = candidate.total_years_experience
            junior_evidence_year_credit, junior_evidence_signals = self._compute_junior_evidence_year_credit(
                job,
                candidate,
            )
            actual_years = max(0.0, float(estimated_years or 0.0))
            effective_years = max(actual_years, junior_evidence_year_credit)
            years_score = min(1.0, effective_years / 10.0)

            # Experience/seniority matching
            seniority_years = effective_years if estimated_years is not None or junior_evidence_year_credit > 0 else None
            seniority_score = compute_seniority_score(job.seniority, seniority_years)
            
            project_semantic_bonus = self._compute_junior_project_semantic_bonus(job, candidate)
            effective_semantic_score = max(semantic_score, project_semantic_bonus)

            # Build reasoning
            reasoning = self._build_reasoning(
                job,
                candidate,
                skill_result,
                effective_semantic_score,
                seniority_score,
                years_score,
                raw_semantic_score=semantic_score,
                project_semantic_bonus=project_semantic_bonus,
                junior_evidence_year_credit=junior_evidence_year_credit,
                junior_evidence_signals=junior_evidence_signals,
            )
            
            # Compute final score
            final_score = self._compute_final_score(
                skill_result, effective_semantic_score, seniority_score, years_score
            )
            
            # Ensure score is bounded [0, 1]
            final_score = round(max(0.0, min(1.0, final_score)), 4)
            reasoning.score_trace["final_score"] = final_score
            logger.debug(
                "Candidate match score computed",
                extra={
                    "job_id": job.id,
                    "candidate_id": candidate.id,
                    "final_score": final_score,
                    "required_score": round(skill_result.required_score, 4),
                    "optional_score": round(skill_result.optional_score, 4),
                    "semantic_score": round(effective_semantic_score, 4),
                    "pre_cap_score": reasoning.pre_cap_score,
                    "score_cap": reasoning.score_cap,
                    "scoring_model": reasoning.scoring_model,
                },
            )
            
            return HybridMatchResult(
                candidate_id=candidate.id,
                final_score=final_score,
                skill_match=skill_result,
                semantic_score=effective_semantic_score,
                cross_encoder_score=None,  # Will be set during re-ranking
                reasoning=reasoning,
                estimated_years=estimated_years,
                years_score=years_score,
            )
        except Exception as e:
            logger.error(f"Match computation failed for candidate {candidate.id}: {e}")
            return None

    def _is_junior_job(self, job: Job) -> bool:
        """
        Checks whether a job should use junior-project semantic support.
        """
        return is_junior_job(job)

    def _compute_junior_project_semantic_bonus(self, job: Job, candidate: Candidate) -> float:
        """
        Computes the capped semantic bonus from relevant junior project evidence.
        """
        return compute_junior_project_semantic_bonus(job, candidate)

    def _compute_junior_evidence_year_credit(self, job: Job, candidate: Candidate) -> tuple[float, list[str]]:
        """
        Computes junior experience credit from internships and certificates.
        """
        return compute_junior_evidence_year_credit(job, candidate)
    
    def _evidence_text(self, candidate: Candidate) -> str:
        """Build evidence text from candidate fields for skill matching."""
        return " ".join(
            list(candidate.experience or [])
            + list(candidate.projects or [])
            + list(candidate.education or [])
            + [candidate.raw_text or ""]
        ).lower()

    async def _compute_skill_match(
        self,
        job: Job,
        candidate: Candidate,
        rag_session: AsyncSession | None = None,
    ) -> SkillMatchResult:
        """Compute ESCO-aware skill matching."""
        result = SkillMatchResult()
        
        required_skills = self._dedupe_skills(job.required_skills or [])
        optional_skills = [
            skill for skill in self._dedupe_skills(job.optional_skills or [])
                if normalize_skill_name(skill) not in {normalize_skill_name(s) for s in required_skills}
        ]
        candidate_skills = self._candidate_skill_names(candidate)
        
        if not required_skills and not optional_skills:
            result.required_score = 1.0
            result.skill_score = 0.5  # Neutral score when no requirements
            return result
        
        # Build candidate skill set with ESCO normalization
        candidate_normalized: dict[str, NormalizedSkill] = {}
        for skill in candidate_skills:
            norm = self.esco.normalize_skill(skill)
            if norm:
                candidate_normalized[skill.lower()] = norm
        
        # Match required skills
        esco_matches = 0
        matched_count = 0
        missing_count = 0
        
        for req_skill in required_skills:
            match = self._match_single_skill(req_skill, candidate_skills, candidate_normalized, candidate)
            if match:
                result.matched_required.append(match)
                matched_count += 1
                if match.normalized:
                    esco_matches += 1
            else:
                result.missing_required.append(req_skill)
                missing_count += 1
        
        # Match optional skills
        for opt_skill in optional_skills:
            match = self._match_single_skill(opt_skill, candidate_skills, candidate_normalized, candidate)
            if match:
                result.matched_optional.append(match)
                if match.normalized:
                    esco_matches += 1

        # Fallback: check evidence text for required skills not found in structured fields
        if result.missing_required:
            evidence_text = self._evidence_text(candidate)
            still_missing: list[str] = []
            for skill in result.missing_required:
                if self._text_has_positive_skill(skill, evidence_text):
                    result.matched_required.append(SkillMatch(
                        skill=skill, match_type="text", confidence=0.80,
                    ))
                    matched_count += 1
                else:
                    still_missing.append(skill)
            result.missing_required = still_missing

        if result.missing_required and rag_session is not None:
            await self._apply_rag_enrichment(result, candidate, rag_session)

        # Compute scores
        total_required = len(required_skills)
        total_optional = len(optional_skills)
        
        result.required_score = (
            sum(match.confidence for match in result.matched_required) / total_required
            if total_required > 0 else 1.0
        )
        result.optional_score = (
            sum(match.confidence for match in result.matched_optional) / total_optional
            if total_optional > 0 else 0.0
        )
        
        # Weighted skill score: required skills weighted higher
        result.skill_score = (
            0.8 * result.required_score + 0.2 * result.optional_score
        )
        
        # ESCO coverage
        total_skills = total_required + total_optional
        result.esco_coverage = esco_matches / total_skills if total_skills > 0 else 0.0
        
        return result

    async def _load_historical_feedback(
        self,
        job: Job,
        candidates: list[Candidate],
        session: AsyncSession | None,
    ) -> None:
        """
        Preloads accepted recruiter feedback so skill matching can reuse it cheaply.
        """
        self._historical_feedback = set()
        if session is None or not candidates:
            return
        try:
            from app.models.skill_feedback import SkillFeedback

            candidate_ids = [candidate.id for candidate in candidates]
            result = await session.execute(
                select(SkillFeedback).where(
                    SkillFeedback.job_id == job.id,
                    SkillFeedback.candidate_id.in_(candidate_ids),
                    SkillFeedback.correct_match.is_(True),
                )
            )
            self._historical_feedback = {
                (feedback.candidate_id, normalize_skill_name(feedback.skill_name))
                for feedback in result.scalars().all()
            }
        except Exception:
            logger.debug("Historical feedback unavailable for matching", exc_info=True)

    async def _apply_rag_enrichment(
        self,
        result: SkillMatchResult,
        candidate: Candidate,
        session: AsyncSession,
    ) -> None:
        """
        Uses RAG skill definitions to create weak matches for otherwise missing skills.
        """
        try:
            from app.services.rag import get_skill_definitions

            definitions = await get_skill_definitions(result.missing_required, session=session)
        except Exception:
            logger.debug("RAG skill definitions unavailable for matching", exc_info=True)
            return

        still_missing: list[str] = []
        for skill in result.missing_required:
            definition = definitions.get(normalize_skill_name(skill))
            if not definition:
                still_missing.append(skill)
                continue
            similarity = await self._rag_similarity_for_skill(definition, candidate)
            if similarity > 0.75:
                result.matched_required.append(SkillMatch(
                    skill=skill,
                    match_type="rag",
                    confidence=0.60,
                ))
                result.rag_matched_count += 1
                result.rag_enriched_skills.append(skill)
                logger.info(
                    "RAG weak skill match applied",
                    extra={"candidate_id": candidate.id, "skill": skill, "similarity": round(similarity, 4)},
                )
            else:
                still_missing.append(skill)
        result.missing_required = still_missing

    async def _rag_similarity_for_skill(self, definition: str, candidate: Candidate) -> float:
        """
        Scores whether candidate evidence semantically aligns with a RAG skill definition.
        """
        candidate_text = self._build_candidate_text(candidate)
        if not is_embedding_quality_text(definition) or not is_embedding_quality_text(candidate_text):
            return 0.0
        if settings.embedding_provider.lower() != "hash":
            try:
                import numpy as np

                definition_embedding, candidate_embedding = await self.embedder.embed([definition, candidate_text])
                if len(definition_embedding) == len(candidate_embedding):
                    left = np.array(definition_embedding, dtype=np.float32)
                    right = np.array(candidate_embedding, dtype=np.float32)
                    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
                    if denom:
                        return float(np.dot(left, right) / denom)
            except Exception:
                logger.debug("RAG embedding similarity failed; using lexical fallback", exc_info=True)

        definition_tokens = self._content_tokens(definition)
        candidate_tokens = self._content_tokens(candidate_text)
        if not definition_tokens or not candidate_tokens:
            return 0.0
        overlap = len(definition_tokens & candidate_tokens) / len(definition_tokens)
        return min(1.0, overlap * 2.0)

    @staticmethod
    def _content_tokens(text: str) -> set[str]:
        stopwords = {
            "and", "are", "for", "from", "into", "that", "the", "this", "with",
            "skill", "skills", "using", "used", "use", "key", "known",
        }
        return {
            token
            for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]{2,}", (text or "").lower())
            if token not in stopwords
        }

    def _candidate_skill_names(self, candidate: Candidate) -> list[str]:
        """
        Collects positive candidate skills while excluding negated or no-experience skills.
        """
        skills = [
            skill for skill in list(candidate.skills or [])
            if not self._candidate_skill_is_negated(skill, candidate, allow_learning=True)
        ]
        for detail in candidate.skills_detailed or []:
            if not isinstance(detail, dict):
                continue
            status = str(detail.get("status", "")).lower().strip()
            name = str(detail.get("name", "")).strip()
            if (
                name
                and status != "no_experience"
                and not self._candidate_skill_is_negated(name, candidate, allow_learning=True)
            ):
                skills.append(name)
        return self._dedupe_skills(skills)

    @staticmethod
    def _dedupe_skills(skills: list[str]) -> list[str]:
        """
        Normalizes and de-duplicates skill names while keeping job-valid skills only.
        """
        deduped: list[str] = []
        seen: set[str] = set()
        for skill in skills:
            normalized = normalize_skill_name(skill)
            if not normalized or normalized in seen or not is_job_skill_name(normalized):
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped
    
    def _match_single_skill(
        self,
        required_skill: str,
        candidate_skills: list[str],
        candidate_normalized: dict[str, NormalizedSkill],
        candidate: Candidate,
    ) -> SkillMatch | None:
        """Match a single required skill against candidate skills."""
        req_lower = normalize_skill_name(required_skill)
        if self._candidate_skill_is_negated(req_lower, candidate, allow_learning=True):
            logger.debug("Required skill '%s' is explicitly negated by candidate evidence", required_skill)
            return None
        
        # Direct match - normalize both sides for comparison
        candidate_skills_lower = [normalize_skill_name(s) for s in candidate_skills]
        
        # Debug logging
        logger.debug(
            f"Matching skill '{required_skill}' (normalized: '{req_lower}') against candidate skills: {candidate_skills_lower[:10]}..."
        )
        
        if req_lower in candidate_skills_lower:
            logger.debug(f"âœ“ Direct match found for '{required_skill}'")
            confidence = self._evidence_adjusted_confidence(required_skill, candidate, 1.0)
            return SkillMatch(
                skill=required_skill,
                normalized=candidate_normalized.get(req_lower),
                match_type="exact",
                confidence=confidence,
            )

        # Curated synonym matching. Keep this narrow: broad category matches
        # like "python" <-> "java" are not acceptable for job-fit ranking.
        req_synonyms = SYNONYM_MAP.get(req_lower, set())
        for cand_skill in candidate_skills:
            cand_lower = normalize_skill_name(cand_skill)
            if self._is_broad_to_specific_match(req_lower, cand_lower):
                continue
            cand_synonyms = SYNONYM_MAP.get(cand_lower, set())
            if cand_lower in req_synonyms or req_lower in cand_synonyms:
                logger.debug(f"âœ“ Synonym match found for '{required_skill}' via '{cand_skill}'")
                confidence = self._evidence_adjusted_confidence(required_skill, candidate, 0.85)
                return SkillMatch(
                    skill=required_skill,
                    normalized=candidate_normalized.get(cand_lower),
                    match_type="related" if self._is_broad_skill_term(req_lower) else "synonym",
                    confidence=confidence,
                )
        
        # ESCO-based matching
        req_norm = self.esco.normalize_skill(required_skill)
        if req_norm:
            # Check if any candidate skill matches via ESCO
            for cand_skill, cand_norm in candidate_normalized.items():
                # Same ESCO URI
                if cand_norm and cand_norm.esco_uri == req_norm.esco_uri:
                    logger.debug(f"âœ“ ESCO match found for '{required_skill}' via '{cand_skill}'")
                    confidence = self._evidence_adjusted_confidence(required_skill, candidate, 0.95)
                    return SkillMatch(
                        skill=required_skill,
                        normalized=cand_norm,
                        match_type="synonym",
                        confidence=confidence,
                    )
            
            # Check related skills
            related = self.esco.get_related_skills(required_skill, depth=1)
            for rel in related:
                for cand_skill, cand_norm in candidate_normalized.items():
                    if cand_norm and cand_norm.esco_uri == rel.skill.esco_uri:
                        logger.debug(f"âœ“ ESCO related match for '{required_skill}' via '{cand_skill}'")
                        confidence = self._evidence_adjusted_confidence(required_skill, candidate, rel.similarity_score)
                        return SkillMatch(
                            skill=required_skill,
                            normalized=cand_norm,
                            match_type="related",
                            confidence=confidence,
                        )

        # Additional detected skills are grounded but outside the catalog, so keep
        # them as weak evidence rather than treating them as exact catalog matches.
        uncatalogued = {normalize_skill_name(skill) for skill in (candidate.uncatalogued_skills or [])}
        if req_lower in uncatalogued:
            return SkillMatch(
                skill=required_skill,
                normalized=req_norm,
                match_type="uncatalogued",
                confidence=0.40,
            )
        
        # Final fallback: match token-safe mentions in the raw CV text, including
        # curated synonyms such as SQLAlchemy -> SQL and AWS certified -> AWS certificate.
        raw_candidates = [required_skill, *sorted(SYNONYM_MAP.get(req_lower, set()))]
        for raw_skill in raw_candidates:
            raw_lower = raw_skill.lower().strip()
            if self._is_broad_to_specific_match(req_lower, raw_lower):
                continue
            if self._raw_text_has_non_stuffed_skill(raw_lower, candidate):
                confidence = 0.80 if raw_lower == req_lower else 0.75
                return SkillMatch(
                    skill=required_skill,
                    normalized=req_norm,
                    match_type="text",
                    confidence=confidence,
                )

        if (candidate.id, req_lower) in self._historical_feedback:
            logger.info(
                "Matched via historical feedback",
                extra={"candidate_id": candidate.id, "skill": required_skill},
            )
            return SkillMatch(
                skill=required_skill,
                normalized=req_norm,
                match_type="historical_feedback",
                confidence=0.70,
            )

        logger.debug(f"âœ— No match found for '{required_skill}'")
        return None

    def _evidence_adjusted_confidence(self, skill: str, candidate: Candidate, base_confidence: float) -> float:
        """
        Lowers match confidence when a skill lacks supporting candidate evidence.
        """
        is_learning = False
        skill_lower = normalize_skill_name(skill)
        for detail in candidate.skills_detailed or []:
            if not isinstance(detail, dict):
                continue
            name = normalize_skill_name(str(detail.get("name", "")))
            status = str(detail.get("status", "")).lower().strip()
            if name == skill_lower and status == "learning":
                is_learning = True
                break
        if not is_learning:
            learning_skills = {normalize_skill_name(s) for s in (candidate.learning_skills or [])}
            if skill_lower in learning_skills:
                is_learning = True

        if is_learning:
            return min(base_confidence, 0.60)

        if self._candidate_has_skill_evidence(skill, candidate):
            return base_confidence
        return min(base_confidence, 0.80)

    def _candidate_skill_is_negated(self, skill: str, candidate: Candidate, allow_learning: bool = False) -> bool:
        """
        Checks whether the candidate explicitly denies or is only learning a skill.
        """
        skill_lower = normalize_skill_name(skill)
        neg_list = list(candidate.negative_skills or [])
        if not allow_learning:
            neg_list += list(candidate.learning_skills or [])
        negative_skills = {
            normalize_skill_name(item)
            for item in neg_list
        }
        if skill_lower in negative_skills:
            return True

        for detail in candidate.skills_detailed or []:
            if not isinstance(detail, dict):
                continue
            name = normalize_skill_name(str(detail.get("name", "")))
            status = str(detail.get("status", "")).lower().strip()
            context = str(detail.get("context", "") or "")
            neg_statuses = {"no_experience"}
            if not allow_learning:
                neg_statuses.add("learning")
            if name == skill_lower and status in neg_statuses:
                return True
            if name == skill_lower and self._text_has_negative_skill(
                skill_lower,
                context,
                include_learning=not allow_learning,
            ):
                return True

        evidence_text = " ".join(
            list(candidate.experience or [])
            + list(candidate.projects or [])
            + list(candidate.education or [])
            + [candidate.raw_text or ""]
        )
        return self._text_has_negative_skill(
            skill_lower,
            evidence_text,
            include_learning=not allow_learning,
        )

    def _candidate_has_skill_evidence(self, skill: str, candidate: Candidate) -> bool:
        """
        Checks candidate sections and detailed skills for positive evidence of a skill.
        """
        skill_lower = normalize_skill_name(skill)
        if self._candidate_skill_is_negated(skill_lower, candidate):
            return False
        for detail in candidate.skills_detailed or []:
            if not isinstance(detail, dict):
                continue
            name = normalize_skill_name(str(detail.get("name", "")))
            status = str(detail.get("status", "")).lower().strip()
            context = str(detail.get("context", "")).strip()
            if name == skill_lower and status in {"has_experience", "unknown"} and context:
                return True

        evidence_text = " ".join(
            list(candidate.experience or [])[:20]
            + list(candidate.projects or [])[:20]
            + list(candidate.education or [])[:10]
        ).lower()
        if self._text_has_positive_skill(skill_lower, evidence_text):
            return True
        return self._raw_text_has_non_stuffed_skill(skill_lower, candidate)

    def _text_has_positive_skill(self, skill: str, text: str) -> bool:
        """
        Checks text for a skill mention that is not in a negative context.
        """
        text_lower = str(text or "").lower()
        matches = list(build_skill_pattern(skill).finditer(text_lower))
        if not matches:
            return False
        for match in matches:
            window = text_lower[max(0, match.start() - 80): match.end() + 80]
            if not NON_EVIDENCE_SKILL_CONTEXT.search(window):
                return True
        return False

    def _text_has_negative_skill(self, skill: str, text: str, include_learning: bool = True) -> bool:
        """
        Checks text for negated skill evidence, optionally including learning-only phrases.
        """
        text_lower = str(text or "").lower()
        matches = list(build_skill_pattern(skill).finditer(text_lower))
        if not matches:
            return False
        negative_pattern = NON_EVIDENCE_SKILL_CONTEXT if include_learning else HARD_NEGATION_SKILL_CONTEXT
        for match in matches:
            window = text_lower[max(0, match.start() - 80): match.end() + 80]
            if negative_pattern.search(window):
                return True
        return False

    @staticmethod
    def _is_broad_skill_term(skill: str) -> bool:
        """
        Checks whether a skill term is broad enough to need stricter matching.
        """
        return normalize_skill_name(skill) in BROAD_SKILL_TERMS

    def _is_broad_to_specific_match(self, required_skill: str, candidate_skill: str) -> bool:
        """
        Prevents broad category terms from matching unrelated specific skills.
        """
        return (
            not self._is_broad_skill_term(required_skill)
            and self._is_broad_skill_term(candidate_skill)
        )

    def _raw_text_has_non_stuffed_skill(self, skill: str, candidate: Candidate) -> bool:
        """
        Detects a raw-text skill mention without rewarding keyword stuffing.
        """
        raw_text = (candidate.raw_text or "").lower()
        if not self._text_has_positive_skill(skill, raw_text):
            return False
        tokens = [token for token in raw_text.replace("/", " ").replace(",", " ").split() if token]
        if not tokens:
            return False
        skill_mentions = len(build_skill_pattern(skill).findall(raw_text))
        if skill_mentions > 10:
            return False
        unique_ratio = len(set(tokens)) / len(tokens)
        return unique_ratio >= 0.35
    
    def _build_candidate_text(self, candidate: Candidate) -> str:
        """Build text representation of candidate for embedding."""
        return build_candidate_embedding_text_from_candidate(candidate)
    
    def _compute_seniority_match(self, job: Job, candidate: Candidate) -> float:
        """Compute seniority match score."""
        return compute_seniority_score(job.seniority, candidate.total_years_experience)
    
    def _build_reasoning(
        self,
        job: Job,
        candidate: Candidate,
        skill_result: SkillMatchResult,
        semantic_score: float,
        seniority_score: float,
        years_score: float,
        raw_semantic_score: float | None = None,
        project_semantic_bonus: float = 0.0,
        junior_evidence_year_credit: float = 0.0,
        junior_evidence_signals: list[str] | None = None,
    ) -> MatchReasoning:
        """Build detailed reasoning for the match."""
        reasoning = MatchReasoning()
        junior_evidence_signals = junior_evidence_signals or []
        
        # Score breakdown
        reasoning.score_breakdown = {
            "skill_required": skill_result.required_score,
            "skill_optional": skill_result.optional_score,
            "semantic": semantic_score,
            "experience": years_score,
            "seniority": seniority_score,
        }
        if project_semantic_bonus > 0:
            reasoning.score_breakdown["raw_semantic"] = raw_semantic_score or 0.0
            reasoning.score_breakdown["project_semantic_bonus"] = project_semantic_bonus
        if junior_evidence_year_credit > 0:
            reasoning.score_breakdown["junior_evidence_year_credit"] = junior_evidence_year_credit
        total_required = len(skill_result.matched_required) + len(skill_result.missing_required)
        scoring = compute_explainable_score(
            required_score=skill_result.required_score,
            optional_score=skill_result.optional_score,
            semantic_score=semantic_score,
            years_score=years_score,
            seniority_score=seniority_score,
            has_required_skills=total_required > 0,
            weights=self.weights,
        )
        reasoning.scoring_model = CURRENT_SCORING_MODEL
        reasoning.scoring_formula = BASE_SCORING_FORMULA
        if project_semantic_bonus > 0:
            reasoning.scoring_formula += "; junior project evidence supplied the semantic score boost"
        if junior_evidence_year_credit > 0:
            reasoning.scoring_formula += "; junior internship/certificate evidence supplied experience credit"
        reasoning.score_weights = scoring["score_weights"]
        reasoning.score_contributions = scoring["score_contributions"]
        reasoning.score_penalties = scoring["score_penalties"]
        reasoning.score_trace = {
            **scoring["score_trace"],
            "job_id": job.id,
            "candidate_id": candidate.id,
            "required_matched_count": len(skill_result.matched_required),
            "required_total": total_required,
            "optional_matched_count": len(skill_result.matched_optional),
            "rag_matched_count": skill_result.rag_matched_count,
            "rag_enriched_skills": skill_result.rag_enriched_skills,
            "required_confidence_sum": round(sum(match.confidence for match in skill_result.matched_required), 4),
            "optional_confidence_sum": round(sum(match.confidence for match in skill_result.matched_optional), 4),
            "required_score_type": "confidence_weighted_coverage",
            "optional_score_type": "confidence_weighted_coverage",
            "junior_evidence_year_credit": round(junior_evidence_year_credit, 4),
            "junior_evidence_signals": junior_evidence_signals,
        }
        reasoning.pre_cap_score = scoring["pre_cap_score"]
        reasoning.score_cap = scoring["score_cap"]
        reasoning.score_cap_reason = scoring["score_cap_reason"]
        
        # Matched and missing skills
        reasoning.matched_skills = [m.skill for m in skill_result.matched_required]
        reasoning.missing_skills = skill_result.missing_required.copy()
        reasoning.rag_matched_count = skill_result.rag_matched_count
        reasoning.rag_enriched_skills = skill_result.rag_enriched_skills.copy()
        
        # Strengths
        if skill_result.required_score >= 0.8:
            reasoning.strengths.append("Strong skill match")
        if semantic_score >= 0.7:
            reasoning.strengths.append("Good semantic alignment")
        if project_semantic_bonus > 0:
            reasoning.strengths.append("Relevant project evidence for junior role")
        if "internship_experience" in junior_evidence_signals:
            reasoning.strengths.append("Internship experience supports junior readiness")
        if "relevant_certificate" in junior_evidence_signals:
            reasoning.strengths.append("Relevant certificate supports junior readiness")
        if skill_result.rag_matched_count:
            reasoning.strengths.append("RAG knowledge base supplied weak skill evidence")
        if seniority_score >= 0.8:
            reasoning.strengths.append("Experience level matches role")
        
        # Gaps
        if skill_result.missing_required:
            reasoning.gaps.append(f"Missing required skills: {', '.join(skill_result.missing_required[:3])}")
        if seniority_score < 0.5:
            reasoning.gaps.append("Experience level below requirements")
        
        # Overqualification check
        job_seniority = (job.seniority or "").lower()
        if job_seniority and candidate.total_years_experience:
            expected_range = SENIORITY_YEARS.get(job_seniority, (0, 10))
            if candidate.total_years_experience > expected_range[1] + 2:
                reasoning.overqualified = True
                reasoning.gaps.append("Potentially overqualified")
        
        # Seniority match classification
        if seniority_score >= 0.9:
            reasoning.seniority_match = "exact"
        elif seniority_score < 0.5:
            reasoning.seniority_match = "under"
        elif reasoning.overqualified:
            reasoning.seniority_match = "over"
        else:
            reasoning.seniority_match = "acceptable"
        
        # Recommendations
        if skill_result.required_score < 0.5:
            reasoning.recommendations.append("Consider if transferable skills apply")
        if reasoning.overqualified:
            reasoning.recommendations.append("Discuss career goals and role fit")
        
        return reasoning
    
    def _compute_final_score(
        self,
        skill_result: SkillMatchResult,
        semantic_score: float,
        seniority_score: float,
        years_score: float = 0.0,
    ) -> float:
        """Compute final weighted score without cross-encoder."""
        total_required = len(skill_result.matched_required) + len(skill_result.missing_required)
        scoring = compute_explainable_score(
            required_score=skill_result.required_score,
            optional_score=skill_result.optional_score,
            semantic_score=semantic_score,
            years_score=years_score,
            seniority_score=seniority_score,
            has_required_skills=total_required > 0,
            weights=self.weights,
        )
        return scoring["final_score"]
    
    def _compute_final_score_with_cross_encoder(
        self,
        result: HybridMatchResult,
        cross_score: float,
    ) -> float:
        """Compute final score with a bounded cross-encoder adjustment."""
        cross_weight = clamp_score(self.weights.get("cross_encoder", DEFAULT_WEIGHTS["cross_encoder"]))
        scoring = compute_cross_encoder_adjusted_score(
            base_score=result.final_score,
            cross_score=cross_score,
            score_cap=self._required_skill_score_cap(result.skill_match),
            cross_weight=cross_weight,
        )
        return scoring["final_score"]

    def _apply_cross_encoder_explanation(
        self,
        result: HybridMatchResult,
        cross_score: float,
        base_score: float,
    ) -> None:
        """
        Adds cross-encoder adjustment details to the reasoning payload.
        """
        scoring = compute_cross_encoder_adjusted_score(
            base_score=base_score,
            cross_score=cross_score,
            score_cap=self._required_skill_score_cap(result.skill_match),
            cross_weight=self.weights.get("cross_encoder", DEFAULT_WEIGHTS["cross_encoder"]),
        )
        cross_weight = scoring["cross_encoder_weight"]
        adjustment = scoring["cross_encoder_adjustment"]
        result.reasoning.scoring_model = CURRENT_CROSS_ENCODER_SCORING_MODEL
        result.reasoning.scoring_formula = CROSS_ENCODER_SCORING_FORMULA
        result.reasoning.score_breakdown = {
            **result.reasoning.score_breakdown,
            "cross_encoder": cross_score,
            "base_hybrid": base_score,
            "cross_encoder_adjustment": adjustment,
        }
        result.reasoning.score_weights = {
            **result.reasoning.score_weights,
            "cross_encoder_adjustment": cross_weight,
        }
        if adjustment > 0:
            result.reasoning.score_contributions = {
                **result.reasoning.score_contributions,
                "cross_encoder_adjustment": adjustment,
            }
            result.reasoning.score_penalties = {}
        elif adjustment < 0:
            result.reasoning.score_penalties = {
                "cross_encoder_adjustment": abs(adjustment),
            }
        else:
            result.reasoning.score_penalties = {}
        result.reasoning.pre_cap_score = scoring["pre_cap_score"]
        result.reasoning.score_cap = self._required_skill_score_cap(result.skill_match)
        result.reasoning.score_cap_reason = self._required_skill_score_cap_reason(result.skill_match)
        result.reasoning.score_trace = {
            **result.reasoning.score_trace,
            "scoring_model": CURRENT_CROSS_ENCODER_SCORING_MODEL,
            "cross_encoder_score": scoring["cross_encoder_score"],
            "base_hybrid_score": scoring["base_score"],
            "cross_encoder_weight": cross_weight,
            "cross_encoder_weighted_delta": scoring["cross_encoder_weighted_delta"],
            "cross_encoder_adjustment": adjustment,
            "cross_encoder_max_adjustment": scoring["cross_encoder_max_adjustment"],
            "pre_cap_score": result.reasoning.pre_cap_score,
            "score_cap": round(result.reasoning.score_cap, 4),
            "cap_applied": result.reasoning.pre_cap_score > result.reasoning.score_cap,
            "final_score": round(result.final_score, 4),
        }

    def _required_skill_score_cap(self, skill_result: SkillMatchResult) -> float:
        """
        Returns the score cap implied by required-skill coverage.
        """
        total_required = len(skill_result.matched_required) + len(skill_result.missing_required)
        return required_skill_score_cap_from_coverage(skill_result.required_score, total_required > 0)

    def _required_skill_score_cap_reason(self, skill_result: SkillMatchResult) -> str:
        """
        Explains the required-skill cap for the match reasoning.
        """
        total_required = len(skill_result.matched_required) + len(skill_result.missing_required)
        return required_skill_score_cap_reason_from_coverage(skill_result.required_score, total_required > 0)
    
    async def _get_cached_embedding(self, vector_store: VectorStore, candidate: Candidate) -> list[float] | None:
        """
        Loads a candidate embedding when its stored metadata still matches the candidate
        text.
        """
        try:
            from sqlalchemy import select
            from app.models.embedding import Embedding
            candidate_text = self._build_candidate_text(candidate)
            expected_metadata = embedding_metadata_for_text(candidate_text)
            stmt = select(Embedding).where(
                Embedding.entity_type == "candidate",
                Embedding.entity_id == candidate.id,
            )
            result = await vector_store.session.execute(stmt)
            row = result.scalar_one_or_none()
            if row:
                if (
                    row.provider != expected_metadata["provider"]
                    or row.model_name != expected_metadata["model_name"]
                    or row.source_hash != expected_metadata["source_hash"]
                ):
                    return None
                validate_embedding_vector(row.embedding_json)
                return row.embedding_json
            return None
        except Exception:
            return None

    async def _cache_embedding(self, vector_store: VectorStore, candidate: Candidate, embedding: list[float]) -> None:
        """
        Stores a fresh candidate embedding with metadata for future matching runs.
        """
        try:
            candidate_text = self._build_candidate_text(candidate)
            await vector_store.upsert_embedding(
                entity_type="candidate",
                entity_id=candidate.id,
                embedding=embedding,
                metadata=embedding_metadata_for_text(candidate_text),
            )
        except Exception:
            pass

    async def _cross_encoder_rerank(
        self,
        job: Job,
        candidate_ids: list[str],
        candidates: list[Candidate],
    ) -> dict[str, float]:
        """Re-rank top candidates using cross-encoder."""
        try:
            from app.services.ollama_cross_encoder import get_ollama_cross_encoder
            
            cross_encoder = get_ollama_cross_encoder()
            
            # Build candidate texts
            candidate_map = {c.id: c for c in candidates}
            pairs = []
            ordered_ids = []
            
            job_text = (
                f"{job.title or ''} {job.description}. "
                f"Required skills: {', '.join(job.required_skills or [])}. "
                f"Optional skills: {', '.join(job.optional_skills or [])}."
            )
            for cid in candidate_ids:
                if cid in candidate_map:
                    candidate = candidate_map[cid]
                    text = self._build_candidate_text(candidate)
                    pairs.append((job_text, text))
                    ordered_ids.append(cid)
            
            if not pairs:
                return {}
            
            # Keep optional deep reranking bounded so a slow local LLM does not
            # block the whole matching request.
            scores = await asyncio.wait_for(
                cross_encoder.predict(pairs),
                timeout=settings.matching_rerank_timeout_seconds,
            )
            
            return {
                cid: score
                for cid, score in zip(ordered_ids, scores)
                if score is not None
            }
            
        except asyncio.TimeoutError:
            logger.warning(
                "Cross-encoder re-ranking timed out; using base hybrid scores",
                extra={"timeout_seconds": settings.matching_rerank_timeout_seconds},
            )
            return {}
        except Exception as e:
            logger.warning(f"Cross-encoder re-ranking failed: {e}")
            return {}
