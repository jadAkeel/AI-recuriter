from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.skill_feedback import SkillFeedback
from app.services.skill_catalog import add_dynamic_synonym, normalize_skill_name

logger = logging.getLogger(__name__)

SYNONYM_CONFIRMATION_THRESHOLD = 3
_ACCEPTED_DYNAMIC_SYNONYMS: set[tuple[str, str]] = set()


async def process_feedback_batch(session: AsyncSession, batch_size: int = 50) -> dict[str, Any]:
    """
    Analyzes stored feedback and promotes repeated corrections to dynamic synonyms.
    """
    result = await session.execute(select(SkillFeedback).where(SkillFeedback.correct_match.is_(True)))
    feedback_items = list(result.scalars().all())
    if not feedback_items:
        return await get_feedback_stats(session)

    candidate_ids = {item.candidate_id for item in feedback_items}
    candidate_result = await session.execute(select(Candidate).where(Candidate.id.in_(candidate_ids)))
    candidates = {candidate.id: candidate for candidate in candidate_result.scalars().all()}

    pair_counts: Counter[tuple[str, str]] = Counter()
    for item in feedback_items:
        candidate = candidates.get(item.candidate_id)
        if candidate is None:
            continue
        target = normalize_skill_name(item.skill_name)
        if not target:
            continue
        candidate_skills = list(candidate.skills or []) + list(candidate.uncatalogued_skills or [])
        for candidate_skill in candidate_skills:
            source = normalize_skill_name(candidate_skill)
            if not source or source == target:
                continue
            pair_counts[tuple(sorted((target, source)))] += 1

    suggested = 0
    accepted = 0
    for pair, count in pair_counts.items():
        if count < SYNONYM_CONFIRMATION_THRESHOLD:
            continue
        suggested += 1
        if pair not in _ACCEPTED_DYNAMIC_SYNONYMS:
            update_synonym_map(pair[0], pair[1])
            _ACCEPTED_DYNAMIC_SYNONYMS.add(pair)
            accepted += 1
            logger.info("Accepted dynamic skill synonym", extra={"skill_a": pair[0], "skill_b": pair[1], "count": count})

    stats = await get_feedback_stats(session)
    stats.update({"synonyms_suggested": suggested, "synonyms_accepted": len(_ACCEPTED_DYNAMIC_SYNONYMS), "new_synonyms_accepted": accepted})
    return stats


async def suggest_new_synonym(session: AsyncSession, skill_a: str, skill_b: str) -> bool:
    """
    Returns true when the observed feedback count supports a new synonym.
    """
    left = normalize_skill_name(skill_a)
    right = normalize_skill_name(skill_b)
    if not left or not right or left == right:
        return False
    stats = await process_feedback_batch(session, batch_size=SYNONYM_CONFIRMATION_THRESHOLD)
    return tuple(sorted((left, right))) in _ACCEPTED_DYNAMIC_SYNONYMS or stats.get("synonyms_suggested", 0) > 0


def update_synonym_map(skill_a: str, skill_b: str) -> None:
    """
    Adds one confirmed dynamic synonym to the in-memory catalog.
    """
    add_dynamic_synonym(skill_a, skill_b)


async def get_feedback_stats(session: AsyncSession) -> dict[str, Any]:
    """
    Returns aggregate feedback and learning counters.
    """
    total = await session.scalar(select(func.count()).select_from(SkillFeedback)) or 0
    positive = await session.scalar(
        select(func.count()).select_from(SkillFeedback).where(SkillFeedback.correct_match.is_(True))
    ) or 0
    return {
        "total_feedback": int(total),
        "pending_review": max(0, int(total) - int(positive)),
        "synonyms_suggested": 0,
        "synonyms_accepted": len(_ACCEPTED_DYNAMIC_SYNONYMS),
    }
