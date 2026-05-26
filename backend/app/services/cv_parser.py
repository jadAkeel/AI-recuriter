from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Iterable
import pdfplumber
from docx import Document
from app.schemas.candidate import CandidateProfile
from app.services.skill_catalog import extract_catalog_skills, normalize_text_for_skill_matching
from app.services.stanza_nlp import ParsedText, parse_text_with_stanza

logger = logging.getLogger(__name__)

SECTION_HEADERS = {
    "experience": re.compile(r"^(experience|work history|employment|professional experience|work experience)\b", re.IGNORECASE),
    "education": re.compile(r"^(education|academic|qualifications|degree)\b", re.IGNORECASE),
    "projects": re.compile(r"^(projects|project experience)\b", re.IGNORECASE),
    "skills": re.compile(r"^(skills|technical skills|core competencies|technologies)\b", re.IGNORECASE),
    "summary": re.compile(r"^(summary|objective|profile|about me|professional summary)\b", re.IGNORECASE),
    "languages": re.compile(r"^(languages|language proficiency)\b", re.IGNORECASE),
    "other": re.compile(r"^(certifications|certificates|awards|publications|references|contact)\b", re.IGNORECASE),
}

EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_PATTERN = re.compile(r"(\+?\d[\d\s\-().]{8,}\d)")
LOCATION_PATTERN = re.compile(r"^(?:location|address)\s*[:\-]\s*(.+)$", re.IGNORECASE | re.MULTILINE)
LANGUAGE_WORDS = {
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




def extract_text(file_name: str, content: bytes) -> str:
    """
    Extracts readable text from an uploaded CV file.
    """
    extension = Path(file_name).suffix.lower()
    if extension == ".pdf":
        return _extract_pdf_text_with_ocr(content)
    if extension == ".docx":
        return _ensure_parseable_text(_extract_docx_text(content))
    if extension == ".doc":
        raise ValueError("Legacy .doc files are not supported safely. Please upload PDF, DOCX, or TXT.")
    if extension in {".txt", ""}:
        return _ensure_parseable_text(content.decode(errors="ignore"))
    raise ValueError(f"Unsupported file type: {extension}")


def parse_cv_text(text: str) -> CandidateProfile:
    """
    Parses CV text into a structured candidate profile.
    """
    text = _ensure_parseable_text(text)
    normalized = _normalize_text(text)
    parsed_text = parse_text_with_stanza(text)
    skills = _extract_skills(normalized)
    sections = _extract_sections(text, parsed_text)

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
    """
    Extracts text from a PDF text layer.
    """
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return "\n".join(pages)
    except Exception as exc:
        raise ValueError("Could not safely extract text from PDF") from exc


def _extract_pdf_text_with_ocr(content: bytes) -> str:
    """
    Extracts PDF text and falls back to OCR for scanned documents.
    """
    text = _extract_pdf_text(content)
    if _has_parseable_text(text):
        return _ensure_parseable_text(text)

    logger.info("PDF text layer empty or too short; attempting OCR fallback")
    ocr_text = _ocr_pdf_text(content)
    if not _has_parseable_text(ocr_text):
        raise ValueError("Could not extract readable text from PDF. OCR returned empty text.")
    return _ensure_parseable_text(ocr_text)


def _ocr_pdf_text(content: bytes) -> str:
    """
    Runs OCR over PDF pages when the text layer is empty.
    """
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
    except Exception as exc:
        raise ValueError(
            "Could not extract readable text from scanned PDF. OCR dependencies are unavailable."
        ) from exc

    try:
        images = convert_from_bytes(content)
        return "\n".join(pytesseract.image_to_string(image) or "" for image in images)
    except Exception as exc:
        raise ValueError("Could not extract readable text from scanned PDF using OCR") from exc


def _extract_docx_text(content: bytes) -> str:
    """
    Extracts paragraph text from a DOCX file.
    """
    try:
        document = Document(io.BytesIO(content))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    except Exception as exc:
        raise ValueError("Could not safely extract text from DOCX") from exc


def _ensure_parseable_text(text: str) -> str:
    """
    Rejects empty or very short CV text before parsing.
    """
    cleaned = str(text or "").strip()
    if not _has_parseable_text(cleaned):
        raise ValueError("CV text is empty or too short to parse reliably")
    return cleaned


def _has_parseable_text(text: str | None) -> bool:
    """
    Checks whether text has enough readable characters to parse.
    """
    return sum(1 for char in str(text or "").strip() if char.isalnum()) >= 10


def _normalize_text(text: str) -> str:
    """
    Normalizes text for catalog-based skill matching.
    """
    return normalize_text_for_skill_matching(text)


def _extract_skills(normalized_text: str) -> list[str]:
    """
    Extracts catalog skills from normalized CV text.
    """
    return extract_catalog_skills(normalized_text)


def _extract_sections(text: str, parsed_text: ParsedText | None = None) -> dict[str, list[str]]:
    """
    Splits CV text into common resume sections.
    """
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

    _add_stanza_sentence_fallbacks(sections, parsed_text)

    return sections


def _add_stanza_sentence_fallbacks(
    sections: dict[str, list[str]],
    parsed_text: ParsedText | None,
) -> None:
    """Use Stanza sentence splitting as a light fallback when CV headers are missing."""

    if parsed_text is None or not parsed_text.sentences:
        return

    if not sections.get("experience"):
        sections["experience"] = _sentences_matching(
            parsed_text.sentences,
            ("experience", "worked", "developed", "implemented", "built", "managed"),
        )
    if not sections.get("projects"):
        sections["projects"] = _sentences_matching(
            parsed_text.sentences,
            ("project", "portfolio", "github"),
        )
    if not sections.get("education"):
        sections["education"] = _sentences_matching(
            parsed_text.sentences,
            ("university", "bachelor", "master", "phd", "degree", "diploma"),
        )


def _sentences_matching(sentences: Iterable[str], keywords: Iterable[str]) -> list[str]:
    """
    Selects sentences that contain section-related keywords.
    """
    keyword_tuple = tuple(keywords)
    matched = [sentence.strip() for sentence in sentences if any(keyword in sentence.lower() for keyword in keyword_tuple)]
    return _cleanup_section(matched)


def _match_header(line: str) -> str | None:
    """
    Matches a CV line to a known section header.
    """
    for section, pattern in SECTION_HEADERS.items():
        if pattern.search(line):
            return section
    return None


def _cleanup_section(items: Iterable[str]) -> list[str]:
    """
    Cleans and limits collected section lines.
    """
    cleaned = [item for item in items if len(item) > 2]
    return cleaned[:50]


def _extract_name(text: str) -> str | None:
    """
    Finds a likely candidate name near the top of the CV.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None

    first_line = lines[0]
    if len(first_line.split()) <= 5 and len(first_line) <= 60:
        return first_line

    for line in lines[:5]:
        if re.match(r"^[A-Z][a-z]+\s+[A-Z][a-z]+", line):
            return line
    return None


def _extract_location(text: str) -> str | None:
    """
    Extracts a location or address field from CV text.
    """
    match = LOCATION_PATTERN.search(text)
    if match:
        return match.group(1).strip()[:120]
    return None


def _extract_languages(text: str, sections: dict[str, list[str]]) -> list[str]:
    """
    Extracts known language names from the CV.
    """
    candidates: set[str] = set()
    language_text = " ".join(sections.get("languages", []))
    searchable = _normalize_text(language_text or text)
    for language in LANGUAGE_WORDS:
        if re.search(r"\b" + re.escape(language) + r"\b", searchable):
            candidates.add(language)
    return sorted(candidates)


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    """
    Returns the first regex match from the text.
    """
    match = pattern.search(text)
    if match:
        return match.group(0)
    return None
