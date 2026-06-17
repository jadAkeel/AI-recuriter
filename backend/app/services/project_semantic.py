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
JUNIOR_INTERNSHIP_YEAR_CREDIT = 0.50
JUNIOR_CERTIFICATE_YEAR_CREDIT = 0.25
JUNIOR_EVIDENCE_YEAR_CAP = 1.00
PROJECT_HEADER = re.compile(
    r"^(?:proj\s+)?(projects|project experience|personal projects)\b",
    re.IGNORECASE,
)
CERTIFICATE_HEADER = re.compile(
    r"^(certifications|certificates|licenses|credentials|courses)\b",
    re.IGNORECASE,
)
SECTION_HEADER_AFTER_PROJECTS = re.compile(
    r"^(experience|work history|employment|professional experience|work experience|"
    r"education|academic|qualifications|degree|skills|technical skills|core competencies|"
    r"summary|objective|profile|about me|professional summary|languages|language proficiency|"
    r"certifications|certificates|awards|publications|references|contact)\b",
    re.IGNORECASE,
)
SECTION_HEADER_AFTER_CERTIFICATES = re.compile(
    r"^(experience|work history|employment|professional experience|work experience|"
    r"education|academic|qualifications|degree|skills|technical skills|core competencies|"
    r"summary|objective|profile|about me|professional summary|languages|language proficiency|"
    r"projects|project experience|personal projects|awards|publications|references|contact)\b",
    re.IGNORECASE,
)
INTERNSHIP_PATTERN = re.compile(
    r"\b(internship|intern|trainee|apprenticeship|apprentice)\b",
    re.IGNORECASE,
)
CERTIFICATE_PATTERN = re.compile(
    r"\b(certification|certifications|certificate|certificates|certified|credential|license)\b",
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


def compute_junior_evidence_year_credit(job: Job, candidate: Candidate) -> tuple[float, list[str]]:
    """
    Credits junior candidates for internship experience and relevant certificates.
    """
    if not is_junior_job(job):
        return 0.0, []

    signals: list[str] = []
    credit = 0.0
    if _has_internship_evidence(candidate):
        signals.append("internship_experience")
        credit += JUNIOR_INTERNSHIP_YEAR_CREDIT
    if _has_relevant_certificate_evidence(job, candidate):
        signals.append("relevant_certificate")
        credit += JUNIOR_CERTIFICATE_YEAR_CREDIT

    if credit <= 0.0:
        return 0.0, []
    return round(min(JUNIOR_EVIDENCE_YEAR_CAP, credit), 2), signals


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


def _candidate_experience_text(candidate: Candidate) -> str:
    """
    Builds searchable experience evidence from structured and raw CV text.
    """
    lines = [str(item).strip() for item in (candidate.experience or []) if str(item).strip()]
    for entry in candidate.experience_entries or []:
        if not isinstance(entry, dict):
            continue
        lines.extend(
            str(entry.get(key, "")).strip()
            for key in ("title", "company", "description")
            if str(entry.get(key, "")).strip()
        )
    lines.extend(_raw_context_windows(candidate.raw_text or "", INTERNSHIP_PATTERN))
    return " ".join(lines)


def _certificate_evidence_text(candidate: Candidate) -> str:
    """
    Builds searchable certificate evidence from raw and structured CV text.
    """
    lines = [str(item).strip() for item in (candidate.education or []) if str(item).strip()]
    for entry in candidate.education_entries or []:
        if not isinstance(entry, dict):
            continue
        lines.extend(
            str(entry.get(key, "")).strip()
            for key in ("degree", "institution", "description")
            if str(entry.get(key, "")).strip()
        )
    lines.extend(_raw_certificate_section_lines(candidate.raw_text or ""))
    lines.extend(_raw_context_windows(candidate.raw_text or "", CERTIFICATE_PATTERN))
    return " ".join(lines)


def _has_internship_evidence(candidate: Candidate) -> bool:
    """
    Checks whether the CV contains internship-style practical experience.
    """
    return bool(INTERNSHIP_PATTERN.search(_candidate_experience_text(candidate)))


def _has_relevant_certificate_evidence(job: Job, candidate: Candidate) -> bool:
    """
    Checks whether certificate text overlaps with skills from the junior role.
    """
    certificate_text = _certificate_evidence_text(candidate)
    if not CERTIFICATE_PATTERN.search(certificate_text):
        return False

    skills = _dedupe_skills(list(job.required_skills or []) + list(job.optional_skills or []))
    if not skills:
        return True

    normalized_certificates = normalize_text_for_skill_matching(certificate_text)
    for skill in skills:
        normalized = normalize_skill_name(skill)
        variants = {skill, normalized, *SYNONYM_MAP.get(normalized, set())}
        if any(skill_in_text(variant, normalized_certificates) for variant in variants if variant):
            return True
    return False


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


def _raw_certificate_section_lines(raw_text: str) -> list[str]:
    """
    Extracts lines from raw certificate sections.
    """
    lines = [line.strip() for line in str(raw_text or "").splitlines()]
    in_certificates = False
    certificate_lines: list[str] = []

    for line in lines:
        if not line:
            continue
        if CERTIFICATE_HEADER.search(line):
            in_certificates = True
            continue
        if in_certificates and SECTION_HEADER_AFTER_CERTIFICATES.search(line):
            break
        if in_certificates:
            certificate_lines.append(line)

    return certificate_lines[:80]


def _raw_context_windows(raw_text: str, pattern: re.Pattern[str]) -> list[str]:
    """
    Extracts nearby raw-text windows around a signal pattern.
    """
    text = str(raw_text or "")
    windows: list[str] = []
    for match in pattern.finditer(text):
        start = max(0, match.start() - 240)
        end = min(len(text), match.end() + 480)
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
