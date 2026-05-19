from __future__ import annotations

import re

from app.models.candidate import Candidate
from app.models.job import Job
from app.services.skill_catalog import (
    SYNONYM_MAP,
    is_job_skill_name,
    normalize_skill_name,
    normalize_text_for_skill_matching,
    skill_in_text,
)

JUNIOR_PROJECT_SEMANTIC_CAP = 0.50
PROJECT_HEADER = re.compile(
    r"^(?:proj\s+)?(projects|project experience|personal projects)\b",
    re.IGNORECASE,
)
SECTION_HEADER_AFTER_PROJECTS = re.compile(
    r"^(experience|work history|employment|professional experience|work experience|"
    r"education|academic|qualifications|degree|skills|technical skills|core competencies|"
    r"summary|objective|profile|about me|professional summary|languages|language proficiency|"
    r"certifications|certificates|awards|publications|references|contact)\b",
    re.IGNORECASE,
)


def is_junior_job(job: Job) -> bool:
    """
    Checks whether a job should use junior project evidence.
    """
    seniority = (job.seniority or "").lower().strip()
    if seniority == "junior":
        return True
    title = (job.title or "").lower()
    return bool(re.search(r"\b(junior|entry\s+level|internship|intern)\b", title))


def compute_junior_project_semantic_bonus(job: Job, candidate: Candidate) -> float:
    """
    Adds a capped semantic bonus when junior projects cover job skills.
    """
    if not is_junior_job(job):
        return 0.0

    project_text = _project_evidence_text(candidate)
    if not project_text:
        return 0.0

    normalized_projects = normalize_text_for_skill_matching(project_text)
    required_skills = _dedupe_skills(job.required_skills or [])
    required_set = {normalize_skill_name(s) for s in required_skills}
    optional_skills = [
        skill for skill in _dedupe_skills(job.optional_skills or [])
        if normalize_skill_name(skill) not in required_set
    ]
    if not required_skills and not optional_skills:
        return 0.0

    matched_weight = 0.0
    total_weight = 0.0
    weighted_skills = [(skill, 1.0) for skill in required_skills] + [(skill, 0.5) for skill in optional_skills]
    for skill, weight in weighted_skills:
        normalized = normalize_skill_name(skill)
        if not normalized:
            continue
        total_weight += weight
        variants = {skill, normalized, *SYNONYM_MAP.get(normalized, set())}
        if any(skill_in_text(variant, normalized_projects) for variant in variants if variant):
            matched_weight += weight

    if total_weight <= 0 or matched_weight <= 0:
        return 0.0
    return JUNIOR_PROJECT_SEMANTIC_CAP


def _project_evidence_text(candidate: Candidate) -> str:
    """
    Builds searchable project evidence from structured and raw CV text.
    """
    lines = [
        str(item).strip()
        for item in (candidate.projects or [])[:50]
        if str(item).strip()
    ]
    lines.extend(_raw_project_section_lines(candidate.raw_text or ""))
    lines.extend(_raw_project_context_windows(candidate.raw_text or ""))

    result: list[str] = []
    seen: set[str] = set()
    for line in lines:
        normalized = " ".join(line.split()).lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(line)
    return " ".join(result)


def _raw_project_section_lines(raw_text: str) -> list[str]:
    """
    Extracts lines from the raw projects section of a CV.
    """
    lines = [line.strip() for line in str(raw_text or "").splitlines()]
    in_projects = False
    project_lines: list[str] = []

    for line in lines:
        if not line:
            continue
        if PROJECT_HEADER.search(line):
            in_projects = True
            continue
        if in_projects and SECTION_HEADER_AFTER_PROJECTS.search(line):
            break
        if in_projects:
            project_lines.append(line)

    return project_lines[:120]


def _raw_project_context_windows(raw_text: str) -> list[str]:
    """
    Extracts nearby raw-text windows around project mentions.
    """
    text = str(raw_text or "")
    if not re.search(
        r"^\s*(?:proj\s+)?(projects|project experience|personal projects)\b",
        text,
        re.IGNORECASE | re.MULTILINE,
    ):
        return []

    windows: list[str] = []
    for match in re.finditer(r"\bproject(?:s| experience)?\b", text, re.IGNORECASE):
        start = max(0, match.start() - 160)
        end = min(len(text), match.end() + 900)
        window = " ".join(text[start:end].split())
        if window:
            windows.append(window)
    return windows[:12]


def _dedupe_skills(skills: list[str]) -> list[str]:
    """
    Normalizes and de-duplicates job skills for project matching.
    """
    result: list[str] = []
    seen: set[str] = set()
    for skill in skills or []:
        normalized = normalize_skill_name(skill)
        if normalized and normalized not in seen and is_job_skill_name(normalized):
            seen.add(normalized)
            result.append(normalized)
    return result
