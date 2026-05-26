from __future__ import annotations

import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.skill_evidence import SkillEvidence
from app.services.embedding import embedding_model_name_for_provider
from app.services.skill_catalog import normalize_skill_name, skill_in_text


def _snippet_around(text: str, skill: str, radius: int = 120) -> str | None:
    source = text or ""
    lowered = source.lower()
    needle = skill.lower()
    index = lowered.find(needle)
    if index < 0:
        normalized = normalize_skill_name(skill)
        index = lowered.find(normalized)
        needle = normalized
    if index < 0:
        return None
    start = max(0, index - radius)
    end = min(len(source), index + len(needle) + radius)
    return " ".join(source[start:end].split())


def _evidence_status(candidate: Candidate, skill: str, explicit_status: str | None = None) -> str:
    normalized = normalize_skill_name(skill)
    if explicit_status:
        return explicit_status
    if normalized in {normalize_skill_name(item) for item in candidate.negative_skills or []}:
        return "no_experience"
    if normalized in {normalize_skill_name(item) for item in candidate.learning_skills or []}:
        return "learning"
    return "has_experience"


def build_skill_evidence_rows(candidate: Candidate) -> list[SkillEvidence]:
    """
    Converts parsed candidate skill fields into traceable evidence rows.
    """
    rows: list[SkillEvidence] = []
    seen: set[tuple[str, str, str]] = set()
    provider = settings.llm_provider if settings.llm_provider != "rule" else "parser"
    model_name = embedding_model_name_for_provider(settings.embedding_provider, candidate.raw_text)

    def add_row(
        *,
        skill: str,
        source_type: str,
        snippet: str | None,
        confidence: float | None,
        status: str | None = None,
        method: str = "parser",
    ) -> None:
        normalized = normalize_skill_name(skill)
        if not normalized:
            return
        dedupe_key = (normalized, source_type, snippet or "")
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        rows.append(
            SkillEvidence(
                id=str(uuid.uuid4()),
                candidate_id=candidate.id,
                job_id=None,
                skill_name=skill,
                normalized_skill=normalized,
                source_type=source_type,
                evidence_snippet=snippet,
                confidence=confidence,
                status=_evidence_status(candidate, skill, status),
                extraction_method=method,
                provider=provider,
                model_name=model_name,
            )
        )

    for detail in candidate.skills_detailed or []:
        if not isinstance(detail, dict):
            continue
        skill = str(detail.get("name") or detail.get("skill") or "").strip()
        if not skill:
            continue
        confidence = detail.get("confidence")
        try:
            confidence = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence = None
        context = str(detail.get("context") or "").strip() or _snippet_around(candidate.raw_text, skill)
        add_row(
            skill=skill,
            source_type="cv_skill_detail" if context else "parser",
            snippet=context,
            confidence=confidence,
            status=str(detail.get("status") or "").strip() or None,
            method="enhanced_parser",
        )

    raw_text = candidate.raw_text or ""
    for skill in candidate.skills or []:
        normalized = normalize_skill_name(skill)
        source_type = "raw_text" if skill_in_text(normalized, raw_text.lower()) else "parser"
        add_row(
            skill=skill,
            source_type=source_type,
            snippet=_snippet_around(raw_text, skill),
            confidence=None,
        )

    project_text = "\n".join(candidate.projects or [])
    for skill in candidate.skills or []:
        normalized = normalize_skill_name(skill)
        if project_text and skill_in_text(normalized, project_text.lower()):
            add_row(
                skill=skill,
                source_type="project",
                snippet=_snippet_around(project_text, skill),
                confidence=None,
            )

    for skill in candidate.negative_skills or []:
        add_row(skill=skill, source_type="negative_statement", snippet=_snippet_around(raw_text, skill), confidence=None, status="no_experience")
    for skill in candidate.learning_skills or []:
        add_row(skill=skill, source_type="learning_statement", snippet=_snippet_around(raw_text, skill), confidence=None, status="learning")

    return rows


async def replace_candidate_skill_evidence(
    session: AsyncSession,
    candidate: Candidate,
    *,
    commit: bool = False,
) -> int:
    """
    Replaces evidence rows for one candidate. Safe to rerun after re-parsing/backfill.
    """
    await session.execute(delete(SkillEvidence).where(SkillEvidence.candidate_id == candidate.id))
    rows = build_skill_evidence_rows(candidate)
    session.add_all(rows)
    if commit:
        await session.commit()
    return len(rows)
