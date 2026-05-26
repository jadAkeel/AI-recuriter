from __future__ import annotations

import logging
from dataclasses import dataclass, asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.job import Job
from app.models.match_result import MatchResult
from app.models.report import Report
from app.services.ai_metadata import current_ai_provider_metadata
from app.services.candidate_text import build_candidate_embedding_text_from_candidate
from app.services.cv_parser import parse_cv_text
from app.services.embedding import embedding_metadata_for_text, get_embedding_service
from app.services.hybrid_matcher import SCORING_VERSION
from app.services.skill_catalog import normalize_skill_name
from app.services.skill_evidence import replace_candidate_skill_evidence
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)


@dataclass
class BackfillSummary:
    candidates_seen: int = 0
    candidates_updated: int = 0
    skill_evidence_rows: int = 0
    candidate_embeddings_rebuilt: int = 0
    job_embeddings_rebuilt: int = 0
    stale_matches_marked: int = 0
    stale_reports_marked: int = 0
    dry_run: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _normalize_list(values: list[str] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        normalized = normalize_skill_name(str(value))
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _candidate_needs_skill_reextract(candidate: Candidate) -> bool:
    return bool(candidate.raw_text and not candidate.skills)


async def run_production_backfill(
    session: AsyncSession,
    *,
    dry_run: bool = False,
    rebuild_embeddings: bool = False,
) -> BackfillSummary:
    """
    Idempotently normalizes legacy candidate data, rebuilds evidence, and marks stale outputs.
    """
    summary = BackfillSummary(dry_run=dry_run)
    provider_metadata = current_ai_provider_metadata()

    candidates = list((await session.execute(select(Candidate))).scalars().all())
    summary.candidates_seen = len(candidates)
    embedder = get_embedding_service() if rebuild_embeddings and not dry_run else None
    store = VectorStore(session) if rebuild_embeddings and not dry_run else None

    for candidate in candidates:
        changed = False
        normalized_skills = _normalize_list(candidate.skills)
        normalized_negative = _normalize_list(candidate.negative_skills)
        normalized_learning = _normalize_list(candidate.learning_skills)
        normalized_uncatalogued = _normalize_list(candidate.uncatalogued_skills)

        if _candidate_needs_skill_reextract(candidate):
            try:
                parsed = parse_cv_text(candidate.raw_text)
                normalized_skills = _normalize_list(parsed.skills)
                normalized_negative = _normalize_list(parsed.negative_skills)
                normalized_learning = _normalize_list(parsed.learning_skills)
                candidate.skills_detailed = [skill.model_dump() for skill in parsed.skills_detailed]
                candidate.experience = parsed.experience
                candidate.experience_entries = [entry.model_dump() for entry in parsed.experience_entries]
                candidate.education = parsed.education
                candidate.education_entries = [entry.model_dump() for entry in parsed.education_entries]
                candidate.projects = parsed.projects
                candidate.total_years_experience = parsed.total_years_experience
                changed = True
            except Exception:
                logger.warning("Candidate skill re-extraction failed", extra={"candidate_id": candidate.id})

        if candidate.skills != normalized_skills:
            candidate.skills = normalized_skills
            changed = True
        if (candidate.negative_skills or None) != (normalized_negative or None):
            candidate.negative_skills = normalized_negative or None
            changed = True
        if (candidate.learning_skills or None) != (normalized_learning or None):
            candidate.learning_skills = normalized_learning or None
            changed = True
        if (candidate.uncatalogued_skills or None) != (normalized_uncatalogued or None):
            candidate.uncatalogued_skills = normalized_uncatalogued or None
            changed = True

        if changed:
            summary.candidates_updated += 1

        if not dry_run:
            summary.skill_evidence_rows += await replace_candidate_skill_evidence(session, candidate)

            if embedder is not None and store is not None:
                embedding_text = build_candidate_embedding_text_from_candidate(candidate)
                embedding = (await embedder.embed([embedding_text]))[0]
                await store.upsert_embedding(
                    "candidate",
                    candidate.id,
                    embedding,
                    metadata=embedding_metadata_for_text(embedding_text),
                    commit=False,
                )
                summary.candidate_embeddings_rebuilt += 1

    if rebuild_embeddings and not dry_run:
        jobs = list((await session.execute(select(Job))).scalars().all())
        embedder = embedder or get_embedding_service()
        store = store or VectorStore(session)
        for job in jobs:
            embedding = (await embedder.embed([job.description]))[0]
            await store.upsert_embedding(
                "job",
                job.id,
                embedding,
                metadata=embedding_metadata_for_text(job.description),
                commit=False,
            )
            summary.job_embeddings_rebuilt += 1

    matches = list((await session.execute(select(MatchResult))).scalars().all())
    for match in matches:
        if match.scoring_version != SCORING_VERSION:
            summary.stale_matches_marked += 1
            if not dry_run:
                match.is_stale = True
                match.provider_metadata = match.provider_metadata or provider_metadata

    reports = list((await session.execute(select(Report))).scalars().all())
    for report in reports:
        if report.scoring_version != SCORING_VERSION:
            summary.stale_reports_marked += 1
            if not dry_run:
                report.is_stale = True
                report.provider_metadata = report.provider_metadata or provider_metadata

    if not dry_run:
        await session.commit()

    logger.info("Production backfill completed", extra=summary.to_dict())
    return summary
