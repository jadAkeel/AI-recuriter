from __future__ import annotations

import logging
import re

from app.schemas.job import JobProfile
from app.services.skill_catalog import SKILL_KEYWORDS, extract_catalog_skills, normalize_text_for_skill_matching, skill_in_text

logger = logging.getLogger(__name__)

REQUIREMENT_HEADERS = re.compile(r"^(requirements|must have|required skills|required qualifications|minimum qualifications)\b", re.IGNORECASE)
OPTIONAL_HEADERS = re.compile(r"^(nice to have|preferred|bonus|preferred qualifications|desirable)\b", re.IGNORECASE)
SECTION_BOUNDARY_HEADERS = re.compile(
    r"^(requirements|must have|required skills|required qualifications|minimum qualifications|"
    r"nice to have|preferred|bonus|preferred qualifications|desirable|responsibilities|"
    r"about|benefits|overview|summary)\b",
    re.IGNORECASE,
)
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
    """
    Parses a job description into title, required skills, optional skills, and
    seniority.
    """
    normalized = _normalize_text(text)
    required = _extract_section_skills(text, REQUIREMENT_HEADERS)
    optional = _extract_section_skills(text, OPTIONAL_HEADERS)

    all_skills = _extract_skills(normalized)

    if BONUS_PHRASE_PATTERN.search(normalized):
        optional = sorted(set(optional) | _extract_bonus_skills(text))

    if not required:
        required = [s for s in all_skills if s not in set(optional)]

    if not required and not optional:
        required = all_skills

    if optional:
        optional = sorted(skill for skill in set(optional) if skill not in set(required))
    required = sorted(set(required))

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


def _extract_bonus_skills(text: str) -> set[str]:
    """
    Extracts skills from lines marked as bonus or preferred.
    """
    lines = text.splitlines()
    bonus_skills: set[str] = set()
    for line in lines:
        if BONUS_PHRASE_PATTERN.search(line):
            line_normalized = _normalize_text(line)
            for skill in SKILL_KEYWORDS:
                if skill_in_text(skill, line_normalized):
                    bonus_skills.add(skill)
    return bonus_skills


def _extract_title(text: str) -> str | None:
    """
    Uses the first non-empty line as the likely job title.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        return lines[0][:120]
    return None


def _normalize_text(text: str) -> str:
    """
    Normalizes job text for skill matching.
    """
    return normalize_text_for_skill_matching(text)


def _extract_skills(normalized_text: str) -> list[str]:
    """
    Extracts catalog skills from normalized job text.
    """
    return extract_catalog_skills(normalized_text)


def _extract_section_skills(text: str, header_pattern: re.Pattern[str]) -> list[str]:
    """
    Extracts skills from a labeled job description section.
    """
    lines = [line.strip() for line in text.splitlines()]
    in_section = False
    collected: list[str] = []
    for line in lines:
        if header_pattern.search(line):
            in_section = True
            remainder = header_pattern.sub("", line, count=1).strip(" :-")
            if remainder:
                collected.append(remainder)
            continue
        if in_section and SECTION_BOUNDARY_HEADERS.search(line):
            break
        if in_section and not line:
            break
        if in_section:
            collected.append(line)

    normalized = _normalize_text(" ".join(collected))
    return _extract_skills(normalized)


def _detect_seniority(text: str) -> str | None:
    """
    Detects job seniority from common seniority phrases.
    """
    for label, pattern in SENIORITY_PATTERNS.items():
        if pattern.search(text):
            return label
    return None
