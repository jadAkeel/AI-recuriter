from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Iterable

import pdfplumber
from docx import Document
from rapidfuzz import fuzz

from app.schemas.candidate import CandidateProfile
from app.services.skill_catalog import SKILL_KEYWORDS, skill_in_text

logger = logging.getLogger(__name__)

SECTION_HEADERS = {
    "experience": re.compile(r"^(experience|work history|employment|professional experience|work experience|خبرات|خبرة|الخبرات)\b", re.IGNORECASE),
    "education": re.compile(r"^(education|academic|تعليم|المؤهلات|التعليم)\b", re.IGNORECASE),
    "projects": re.compile(r"^(projects|project experience|مشاريع|المشاريع)\b", re.IGNORECASE),
    "skills": re.compile(r"^(skills|technical skills|مهارات|المهارات|المهارات التقنية)\b", re.IGNORECASE),
    "summary": re.compile(r"^(summary|objective|profile|about me|professional summary)\b", re.IGNORECASE),
    "languages": re.compile(r"^(languages|language proficiency)\b", re.IGNORECASE),
    "other": re.compile(r"^(certifications|certificates|awards|publications|references|contact)\b", re.IGNORECASE),
}

EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_PATTERN = re.compile(r"(\+?\d[\d\s\-().]{8,}\d)")
LOCATION_PATTERN = re.compile(r"^(?:location|address)\s*[:\-]\s*(.+)$", re.IGNORECASE | re.MULTILINE)
LANGUAGE_WORDS = {
    "arabic",
    "english",
    "french",
    "spanish",
    "german",
    "italian",
    "portuguese",
    "turkish",
    "russian",
    "mandarin",
    "chinese",
}

ARABIC_NORMALIZE_MAP = str.maketrans({
    "إ": "ا", "أ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي",
})


def extract_text(file_name: str, content: bytes) -> str:
    extension = Path(file_name).suffix.lower()
    if extension == ".pdf":
        return _ensure_parseable_text(_extract_pdf_text(content))
    if extension == ".docx":
        return _ensure_parseable_text(_extract_docx_text(content))
    if extension == ".doc":
        raise ValueError("Legacy .doc files are not supported safely. Please upload PDF, DOCX, or TXT.")
    if extension in {".txt", ""}:
        return _ensure_parseable_text(content.decode(errors="ignore"))
    raise ValueError(f"Unsupported file type: {extension}")


def parse_cv_text(text: str) -> CandidateProfile:
    text = _ensure_parseable_text(text)
    normalized = _normalize_text(text)
    skills = _extract_skills(normalized)
    sections = _extract_sections(text)

    full_name = _extract_name(text)
    email = _first_match(EMAIL_PATTERN, text)
    phone = _first_match(PHONE_PATTERN, text)
    location = _extract_location(text)
    languages = _extract_languages(text, sections)

    total_years = None
    total_match = re.search(r"Total Years of Experience:\s*([\d.]+)", text, re.IGNORECASE)
    if total_match:
        total_years = float(total_match.group(1))

    profile = CandidateProfile(
        full_name=full_name,
        email=email,
        phone=phone,
        location=location,
        skills=skills,
        experience=sections.get("experience", []),
        education=sections.get("education", []),
        projects=sections.get("projects", []),
        languages=languages,
        total_years_experience=total_years,
        raw_text=text,
    )
    logger.info("CV parsed", extra={"skills_count": len(skills)})
    return profile


def _extract_pdf_text(content: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return "\n".join(pages)
    except Exception as exc:
        raise ValueError("Could not safely extract text from PDF") from exc


def _extract_docx_text(content: bytes) -> str:
    try:
        document = Document(io.BytesIO(content))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    except Exception as exc:
        raise ValueError("Could not safely extract text from DOCX") from exc


def _ensure_parseable_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if sum(1 for char in cleaned if char.isalnum()) < 10:
        raise ValueError("CV text is empty or too short to parse reliably")
    return cleaned


def _normalize_text(text: str) -> str:
    lowered = text.lower()
    lowered = lowered.replace("/", " ")
    lowered = re.sub(r"[^a-z0-9+#.\s\u0600-\u06FF]", " ", lowered)
    lowered = lowered.translate(ARABIC_NORMALIZE_MAP)
    return re.sub(r"\s+", " ", lowered).strip()


def _extract_skills(normalized_text: str) -> list[str]:
    found: set[str] = set()
    for skill in SKILL_KEYWORDS:
        if skill_in_text(skill, normalized_text):
            found.add(skill)
            continue

        if " " in skill and fuzz.partial_ratio(skill, normalized_text) >= 90:
            found.add(skill)

    return sorted(found)


def _extract_sections(text: str) -> dict[str, list[str]]:
    lines = [line.strip() for line in text.splitlines()]
    sections: dict[str, list[str]] = {"experience": [], "education": [], "projects": [], "languages": []}
    current_section: str | None = None

    for line in lines:
        if not line:
            continue
        matched_header = _match_header(line)
        if matched_header:
            current_section = matched_header
            continue

        if current_section in sections:
            sections[current_section].append(line)

    for key, items in sections.items():
        sections[key] = _cleanup_section(items)

    return sections


def _match_header(line: str) -> str | None:
    for section, pattern in SECTION_HEADERS.items():
        if pattern.search(line):
            return section
    return None


def _cleanup_section(items: Iterable[str]) -> list[str]:
    cleaned = [item for item in items if len(item) > 2]
    return cleaned[:50]


def _extract_name(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None

    first_line = lines[0]
    if len(first_line.split()) <= 5 and len(first_line) <= 60:
        return first_line

    for line in lines[:5]:
        if re.match(r"^[A-Z][a-z]+\s+[A-Z][a-z]+", line):
            return line
        if re.match(r"^[\u0600-\u06FF]+\s+[\u0600-\u06FF]+", line):
            return line
    return None


def _extract_location(text: str) -> str | None:
    match = LOCATION_PATTERN.search(text)
    if match:
        return match.group(1).strip()[:120]
    return None


def _extract_languages(text: str, sections: dict[str, list[str]]) -> list[str]:
    candidates: set[str] = set()
    language_text = " ".join(sections.get("languages", []))
    searchable = _normalize_text(language_text or text)
    for language in LANGUAGE_WORDS:
        if re.search(r"\b" + re.escape(language) + r"\b", searchable):
            candidates.add(language)
    return sorted(candidates)


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if match:
        return match.group(0)
    return None
