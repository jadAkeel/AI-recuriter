from __future__ import annotations

import logging
import re

from app.schemas.job import JobProfile
from app.services.skill_catalog import SKILL_KEYWORDS, skill_in_text

logger = logging.getLogger(__name__)

REQUIREMENT_HEADERS = re.compile(r"^(requirements|must have|required skills)\b", re.IGNORECASE)
OPTIONAL_HEADERS = re.compile(r"^(nice to have|preferred|bonus)\b", re.IGNORECASE)
SENIORITY_PATTERNS = {
    "junior": re.compile(r"\b(junior|entry level|associate)\b", re.IGNORECASE),
    "mid": re.compile(r"\b(mid|intermediate)\b", re.IGNORECASE),
    "senior": re.compile(r"\b(senior|lead|principal|staff)\b", re.IGNORECASE),
}


BONUS_PHRASE_PATTERN = re.compile(
    r"(is a plus|nice to have|preferred|bonus|plus|good to have|desirable|advantage)",
    re.IGNORECASE,
)


def parse_job_description(text: str) -> JobProfile:
    normalized = _normalize_text(text)
    required = _extract_section_skills(text, REQUIREMENT_HEADERS)
    optional = _extract_section_skills(text, OPTIONAL_HEADERS)

    all_skills = _extract_skills(normalized)

    bonus_match = BONUS_PHRASE_PATTERN.search(normalized)
    if bonus_match:
        bonus_sentences = _extract_bonus_skills(text, normalized)
        optional_from_bonus = [s for s in all_skills if s in bonus_sentences]
        optional = list(set(optional + optional_from_bonus))
        required = [s for s in all_skills if s not in optional]
    elif not required:
        required = all_skills

    if optional:
        optional = [skill for skill in optional if skill not in required]

    seniority = _detect_seniority(text)

    profile = JobProfile(
        title=_extract_title(text),
        description=text,
        required_skills=required,
        optional_skills=optional,
        seniority=seniority,
    )
    logger.info("Job parsed", extra={"required": len(required), "optional": len(optional)})
    return profile


def _extract_bonus_skills(text: str, normalized: str) -> set[str]:
    lines = text.splitlines()
    bonus_skills: set[str] = set()
    for line in lines:
        if BONUS_PHRASE_PATTERN.search(line):
            line_normalized = _normalize_text(line)
            for skill in SKILL_KEYWORDS:
                if re.search(r"\b" + re.escape(skill) + r"\b", line_normalized):
                    bonus_skills.add(skill)
    return bonus_skills


def _extract_title(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        return lines[0][:120]
    return None


def _normalize_text(text: str) -> str:
    lowered = text.lower()
    lowered = lowered.replace("/", " ")
    lowered = re.sub(r"[^a-z0-9+#.\s]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _extract_skills(normalized_text: str) -> list[str]:
    skills: set[str] = set()
    for skill in SKILL_KEYWORDS:
        if skill_in_text(skill, normalized_text):
            skills.add(skill)
    return sorted(skills)


def _extract_section_skills(text: str, header_pattern: re.Pattern[str]) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    in_section = False
    collected: list[str] = []
    for line in lines:
        if header_pattern.search(line):
            in_section = True
            continue
        if in_section and not line:
            break
        if in_section:
            collected.append(line)

    normalized = _normalize_text(" ".join(collected))
    return _extract_skills(normalized)


def _detect_seniority(text: str) -> str | None:
    for label, pattern in SENIORITY_PATTERNS.items():
        if pattern.search(text):
            return label
    return None
