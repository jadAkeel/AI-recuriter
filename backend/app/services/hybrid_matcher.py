"""
Hybrid Matching Engine for CV-to-Job matching.

This module provides a sophisticated matching system that combines:
- ESCO-based skill matching with semantic understanding
- Vector embeddings for semantic similarity
- Structured scoring (experience, education, seniority)
- Cross-encoder re-ranking for top candidates
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.job import Job
from app.services.esco_service import ESCOSkillService, get_esco_service, NormalizedSkill
from app.services.embedding import EmbeddingProvider, get_embedding_service
from app.services.skill_catalog import SYNONYM_MAP
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)

# Score weights for hybrid matching
DEFAULT_WEIGHTS = {
    "skill_required": 0.35,
    "skill_optional": 0.15,
    "semantic": 0.20,
    "experience": 0.15,
    "seniority_match": 0.10,
    "cross_encoder": 0.60,  # When cross-encoder is used
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
    
    def to_dict(self) -> dict[str, Any]:
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
        }


@dataclass
class MatchReasoning:
    """Detailed reasoning for a match result."""
    score_breakdown: dict[str, float] = field(default_factory=dict)
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    overqualified: bool = False
    seniority_match: str = "unknown"  # exact, under, over
    recommendations: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "score_breakdown": {k: round(v, 4) for k, v in self.score_breakdown.items()},
            "matched_skills": self.matched_skills,
            "missing_skills": self.missing_skills,
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
            "score_breakdown": {k: round(v, 4) for k, v in reas.score_breakdown.items()},
            "matched_skills": reas.matched_skills,
            "missing_skills": reas.missing_skills,
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
        self.esco = esco_service or get_esco_service()
        self.embedder = embedding_service or get_embedding_service()
        self.weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    
    async def match(
        self,
        job: Job,
        candidates: list[Candidate],
        top_k: int = 10,
        enable_cross_encoder: bool = True,
        cross_encoder_top_k: int = 0,
        vector_store: VectorStore | None = None,
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
        
        # Step 1: Pre-compute job embedding once (not per candidate)
        job_text = f"{job.title or ''} {job.description}"
        logger.info("Step 1/4: Computing job embedding...")
        try:
            job_embedding_vec = (await self.embedder.embed([job_text]))[0]
            logger.info("Job embedding computed", extra={"dimension": len(job_embedding_vec)})
        except Exception as e:
            logger.warning("Job embedding failed, using fallback", extra={"error": str(e)})
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
                    uncached_indices.append(i)
                    uncached_texts.append(candidate_texts[i])
            if uncached_indices:
                logger.info("Cache miss for %d/%d candidates, computing embeddings...",
                            len(uncached_indices), len(candidates))
        else:
            uncached_indices = list(range(len(candidates)))
            uncached_texts = candidate_texts

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
                if emb is not None:
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
            semantic_score = semantic_scores.get(i, 0.5)
            result = await self._compute_match(job, candidate, semantic_score)
            if result:
                results.append(result)
        
        # Sort by initial score
        results.sort(key=lambda r: r.final_score, reverse=True)
        
        # Cross-encoder re-ranking for top candidates
        if enable_cross_encoder and cross_encoder_top_k > 0:
            top_n = min(cross_encoder_top_k, len(results))
            logger.info("Step 4/4: Cross-encoder re-ranking top %d candidates...", top_n)
            cross_scores = await self._cross_encoder_rerank(job, [r.candidate_id for r in results[:top_n]], candidates)
            
            for i, result in enumerate(results[:top_n]):
                if result.candidate_id in cross_scores:
                    cross_score = cross_scores[result.candidate_id]
                    result.cross_encoder_score = cross_score
                    
                    # Recompute final score with cross-encoder
                    result.final_score = self._compute_final_score_with_cross_encoder(
                        result, cross_score
                    )
        
        # Final sort
        results.sort(key=lambda r: r.final_score, reverse=True)
        
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
            logger.warning("Matching complete — no candidates scored above zero")
        
        return top_results
    
    async def _compute_match(self, job: Job, candidate: Candidate, semantic_score: float = 0.5) -> HybridMatchResult | None:
        """Compute match between a job and candidate."""
        try:
            # Skill matching
            skill_result = await self._compute_skill_match(job, candidate)
            
            # Experience/seniority matching
            seniority_score = self._compute_seniority_match(job, candidate)
            
            # Estimated years for frontend compatibility
            estimated_years = candidate.total_years_experience
            years_score = min(1.0, (estimated_years or 0) / 10.0)
            
            # Build reasoning
            reasoning = self._build_reasoning(
                job, candidate, skill_result, semantic_score, seniority_score
            )
            
            # Compute final score
            final_score = self._compute_final_score(
                skill_result, semantic_score, seniority_score
            )
            
            # Ensure score is bounded [0, 1]
            final_score = max(0.0, min(1.0, final_score))
            
            return HybridMatchResult(
                candidate_id=candidate.id,
                final_score=final_score,
                skill_match=skill_result,
                semantic_score=semantic_score,
                cross_encoder_score=None,  # Will be set during re-ranking
                reasoning=reasoning,
                estimated_years=estimated_years,
                years_score=years_score,
            )
        except Exception as e:
            logger.error(f"Match computation failed for candidate {candidate.id}: {e}")
            return None
    
    async def _compute_skill_match(self, job: Job, candidate: Candidate) -> SkillMatchResult:
        """Compute ESCO-aware skill matching."""
        result = SkillMatchResult()
        
        required_skills = job.required_skills or []
        optional_skills = job.optional_skills or []
        candidate_skills = candidate.skills or []
        
        if not required_skills and not optional_skills:
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
        for req_skill in required_skills:
            match = self._match_single_skill(req_skill, candidate_skills, candidate_normalized)
            if match:
                result.matched_required.append(match)
                if match.normalized:
                    esco_matches += 1
            else:
                result.missing_required.append(req_skill)
        
        # Match optional skills
        for opt_skill in optional_skills:
            match = self._match_single_skill(opt_skill, candidate_skills, candidate_normalized)
            if match:
                result.matched_optional.append(match)
                if match.normalized:
                    esco_matches += 1
        
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
    
    def _match_single_skill(
        self,
        required_skill: str,
        candidate_skills: list[str],
        candidate_normalized: dict[str, NormalizedSkill],
    ) -> SkillMatch | None:
        """Match a single required skill against candidate skills."""
        req_lower = required_skill.lower().strip()
        
        # Direct match
        if req_lower in [s.lower() for s in candidate_skills]:
            return SkillMatch(
                skill=required_skill,
                normalized=candidate_normalized.get(req_lower),
                match_type="exact",
                confidence=1.0,
            )

        # Curated synonym matching. Keep this narrow: broad category matches
        # like "python" <-> "java" are not acceptable for job-fit ranking.
        req_synonyms = SYNONYM_MAP.get(req_lower, set())
        for cand_skill in candidate_skills:
            cand_lower = cand_skill.lower().strip()
            cand_synonyms = SYNONYM_MAP.get(cand_lower, set())
            if cand_lower in req_synonyms or req_lower in cand_synonyms:
                return SkillMatch(
                    skill=required_skill,
                    normalized=candidate_normalized.get(cand_lower),
                    match_type="synonym",
                    confidence=0.85,
                )
        
        # ESCO-based matching
        req_norm = self.esco.normalize_skill(required_skill)
        if req_norm:
            # Check if any candidate skill matches via ESCO
            for cand_skill, cand_norm in candidate_normalized.items():
                # Same ESCO URI
                if cand_norm and cand_norm.esco_uri == req_norm.esco_uri:
                    return SkillMatch(
                        skill=required_skill,
                        normalized=cand_norm,
                        match_type="synonym",
                        confidence=0.95,
                    )
            
            # Check related skills
            related = self.esco.get_related_skills(required_skill, depth=1)
            for rel in related:
                for cand_skill, cand_norm in candidate_normalized.items():
                    if cand_norm and cand_norm.esco_uri == rel.skill.esco_uri:
                        return SkillMatch(
                            skill=required_skill,
                            normalized=cand_norm,
                            match_type="related",
                            confidence=rel.similarity_score,
                        )
            
        return None
    
    def _build_candidate_text(self, candidate: Candidate) -> str:
        """Build text representation of candidate for embedding."""
        parts = []
        
        if candidate.skills:
            parts.append(f"Skills: {', '.join(candidate.skills)}")
        
        if candidate.experience:
            parts.append(f"Experience: {' '.join(candidate.experience[:10])}")
        
        if candidate.education:
            parts.append(f"Education: {' '.join(candidate.education[:5])}")
        
        if candidate.projects:
            parts.append(f"Projects: {' '.join(candidate.projects[:5])}")
        
        return ". ".join(parts) if parts else candidate.raw_text
    
    def _compute_seniority_match(self, job: Job, candidate: Candidate) -> float:
        """Compute seniority match score."""
        job_seniority = (job.seniority or "").lower()
        if not job_seniority:
            return 0.5  # Neutral if no seniority specified
        
        candidate_years = candidate.total_years_experience
        if candidate_years is None:
            return 0.5  # Neutral if unknown
        
        expected_range = SENIORITY_YEARS.get(job_seniority, (0, 10))
        min_years, max_years = expected_range
        
        if candidate_years >= min_years and candidate_years <= max_years:
            return 1.0  # Perfect match
        elif candidate_years < min_years:
            # Under-qualified - score based on how close
            ratio = candidate_years / min_years if min_years > 0 else 0.5
            return max(0.0, min(0.5, ratio * 0.5))
        else:
            # Over-qualified - slight penalty
            excess = candidate_years - max_years
            penalty = min(0.3, excess * 0.05)
            return max(0.5, 1.0 - penalty)
    
    def _build_reasoning(
        self,
        job: Job,
        candidate: Candidate,
        skill_result: SkillMatchResult,
        semantic_score: float,
        seniority_score: float,
    ) -> MatchReasoning:
        """Build detailed reasoning for the match."""
        reasoning = MatchReasoning()
        
        # Score breakdown
        reasoning.score_breakdown = {
            "skill_required": skill_result.required_score,
            "skill_optional": skill_result.optional_score,
            "semantic": semantic_score,
            "seniority": seniority_score,
        }
        
        # Matched and missing skills
        reasoning.matched_skills = [m.skill for m in skill_result.matched_required]
        reasoning.missing_skills = skill_result.missing_required.copy()
        
        # Strengths
        if skill_result.required_score >= 0.8:
            reasoning.strengths.append("Strong skill match")
        if semantic_score >= 0.7:
            reasoning.strengths.append("Good semantic alignment")
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
    ) -> float:
        """Compute final weighted score without cross-encoder."""
        w = self.weights
        
        score = (
            w["skill_required"] * skill_result.required_score +
            w["skill_optional"] * skill_result.optional_score +
            w["semantic"] * semantic_score +
            w["seniority_match"] * seniority_score
        )
        
        # Penalty for missing required skills (proportional, like legacy)
        missing_penalty = 0.0
        total_required = len(skill_result.matched_required) + len(skill_result.missing_required)
        if total_required > 0:
            missing_penalty = 0.30 * (len(skill_result.missing_required) / total_required)
        
        return max(0.0, score - missing_penalty)
    
    def _compute_final_score_with_cross_encoder(
        self,
        result: HybridMatchResult,
        cross_score: float,
    ) -> float:
        """Compute final score incorporating cross-encoder."""
        w = self.weights
        
        # When cross-encoder is used, it gets high weight but not 100%
        cross_weight = w["cross_encoder"]
        remaining_weight = 1.0 - cross_weight
        
        other_score = self._compute_final_score(
            result.skill_match,
            result.semantic_score,
            result.reasoning.score_breakdown.get("seniority", 0.5),
        )
        
        return cross_weight * cross_score + remaining_weight * other_score
    
    async def _get_cached_embedding(self, vector_store: VectorStore, candidate: Candidate) -> list[float] | None:
        try:
            from sqlalchemy import select
            from app.models.embedding import Embedding
            stmt = select(Embedding.embedding_json).where(
                Embedding.entity_type == "candidate",
                Embedding.entity_id == candidate.id,
            )
            result = await vector_store.session.execute(stmt)
            row = result.scalar_one_or_none()
            return row if row else None
        except Exception:
            return None

    async def _cache_embedding(self, vector_store: VectorStore, candidate: Candidate, embedding: list[float]) -> None:
        try:
            await vector_store.upsert_embedding(
                entity_type="candidate",
                entity_id=candidate.id,
                embedding=embedding,
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
            
            job_text = f"{job.title or ''} {job.description}"
            for cid in candidate_ids:
                if cid in candidate_map:
                    candidate = candidate_map[cid]
                    text = self._build_candidate_text(candidate)
                    pairs.append((job_text, text))
                    ordered_ids.append(cid)
            
            if not pairs:
                return {}
            
            # Get cross-encoder scores
            scores = await cross_encoder.predict(pairs)
            
            return dict(zip(ordered_ids, scores))
            
        except Exception as e:
            logger.warning(f"Cross-encoder re-ranking failed: {e}")
            return {}
