from __future__ import annotations

import asyncio
import io
import logging
import re
from pathlib import Path
from typing import Any

import pdfplumber
from docx import Document
from rapidfuzz import fuzz

from app.schemas.candidate import (
    CandidateProfile,
    EducationEntry,
    ExperienceEntry,
    SkillDetail,
    SkillLevel,
    SkillStatus,
)
from app.services.bilingual_llm import get_bilingual_llm_service
from app.services.esco_service import ESCOSkillService, get_esco_service, NormalizedSkill
from app.services.skill_catalog import (
    SKILL_KEYWORDS,
    build_skill_pattern,
    canonicalize_skill_name,
    normalize_text_for_skill_matching,
    skill_in_text,
    validate_catalog_skill_list,
)
from app.services.stanza_nlp import ParsedText, parse_text_with_stanza

logger = logging.getLogger(__name__)

SECTION_HEADERS = {
    "experience": re.compile(
        r"^(experience|work history|employment|professional experience|work experience)\b",
        re.IGNORECASE,
    ),
    "education": re.compile(
        r"^(education|academic|qualifications|degree)\b",
        re.IGNORECASE,
    ),
    "projects": re.compile(
        r"^(projects|project experience|personal projects)\b",
        re.IGNORECASE,
    ),
    "skills": re.compile(
        r"^(skills|technical skills|core competencies|technologies)\b",
        re.IGNORECASE,
    ),
    "summary": re.compile(
        r"^(summary|objective|profile|about me|professional summary)\b",
        re.IGNORECASE,
    ),
    "languages": re.compile(
        r"^(languages|language proficiency)\b",
        re.IGNORECASE,
    ),
    "other": re.compile(
        r"^(certifications|certificates|awards|publications|references|contact)\b",
        re.IGNORECASE,
    ),
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

NEGATION_INDICATORS = [
    "don't know",
    "do not know",
    "no experience",
    "not experienced",
    "never used",
    "haven't used",
    "not familiar",
    "don't have",
    "do not have",
    "no knowledge",
    "currently learning",
    "want to learn",
    "wish to learn",
]


class EnhancedCVParser:
    def __init__(self, use_llm: bool = True, use_esco: bool = True) -> None:
        """
        Initializes the enhanced CV parser with optional LLM and ESCO support.
        """
        self.use_llm = use_llm
        self.use_esco = use_esco
        self._llm_service = None
        self._esco_service: ESCOSkillService | None = None

    def _get_llm_service(self) -> Any:
        """
        Lazily creates the LLM service used for CV skill analysis.
        """
        if self._llm_service is None and self.use_llm:
            self._llm_service = get_bilingual_llm_service()
        return self._llm_service
    
    def _get_esco_service(self) -> ESCOSkillService:
        """
        Lazily creates the ESCO skill service used for normalization.
        """
        if self._esco_service is None and self.use_esco:
            self._esco_service = get_esco_service()
        return self._esco_service

    def extract_text(self, file_name: str, content: bytes) -> str:
        """
        Extracts CV text through the shared parser.
        """
        from app.services.cv_parser import extract_text as extract_cv_text

        return extract_cv_text(file_name, content)

    def _extract_text_without_ocr(self, file_name: str, content: bytes) -> str:
        """
        Extracts CV text without using OCR fallback.
        """
        extension = Path(file_name).suffix.lower()
        if extension == ".pdf":
            return self._ensure_parseable_text(self._extract_pdf_text(content))
        if extension == ".docx":
            return self._ensure_parseable_text(self._extract_docx_text(content))
        if extension == ".doc":
            raise ValueError("Legacy .doc files are not supported safely. Please upload PDF, DOCX, or TXT.")
        if extension in {".txt", ""}:
            return self._ensure_parseable_text(content.decode(errors="ignore"))
        raise ValueError(f"Unsupported file type: {extension}")

    def _extract_pdf_text(self, content: bytes) -> str:
        """
        Extracts text from a PDF text layer.
        """
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
            return "\n".join(pages)
        except Exception as exc:
            raise ValueError("Could not safely extract text from PDF") from exc

    def _extract_docx_text(self, content: bytes) -> str:
        """
        Extracts paragraph text from a DOCX file.
        """
        try:
            document = Document(io.BytesIO(content))
            return "\n".join(paragraph.text for paragraph in document.paragraphs)
        except Exception as exc:
            raise ValueError("Could not safely extract text from DOCX") from exc

    def _ensure_parseable_text(self, text: str) -> str:
        """
        Rejects empty or very short CV text before enhanced parsing.
        """
        cleaned = str(text or "").strip()
        if sum(1 for char in cleaned if char.isalnum()) < 10:
            raise ValueError("CV text is empty or too short to parse reliably")
        return cleaned

    def _normalize_text(self, text: str) -> str:
        """
        Normalizes text for skill and evidence matching.
        """
        return normalize_text_for_skill_matching(text)

    def _extract_name(self, text: str) -> str | None:
        """
        Finds a likely candidate name while avoiding contact fields.
        """
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return None

        first_line = lines[0]
        if len(first_line.split()) <= 5 and len(first_line) <= 60:
            email_match = EMAIL_PATTERN.search(first_line)
            phone_match = PHONE_PATTERN.search(first_line)
            if not email_match and not phone_match:
                return first_line

        for line in lines[:10]:
            if re.match(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}$", line):
                return line

        return None

    def _extract_email(self, text: str) -> str | None:
        """
        Extracts the first email address found in the CV.
        """
        match = EMAIL_PATTERN.search(text)
        return match.group(0) if match else None

    def _extract_phone(self, text: str) -> str | None:
        """
        Extracts the first phone number found in the CV.
        """
        match = PHONE_PATTERN.search(text)
        return match.group(0) if match else None

    def _extract_location(self, text: str) -> str | None:
        """
        Extracts a location or address field from the CV.
        """
        match = LOCATION_PATTERN.search(text)
        if match:
            return match.group(1).strip()[:120]
        return None

    def _extract_languages(self, text: str, sections: dict[str, list[str]]) -> list[str]:
        """
        Extracts known language names from CV text or the languages section.
        """
        candidates: set[str] = set()
        language_text = " ".join(sections.get("languages", []))
        searchable = self._normalize_text(language_text or text)
        for language in LANGUAGE_WORDS:
            if re.search(r"\b" + re.escape(language) + r"\b", searchable):
                candidates.add(language)
        return sorted(candidates)

    def _extract_sections(self, text: str) -> dict[str, list[str]]:
        """
        Collects CV lines under known section headers.
        """
        lines = [line.strip() for line in text.splitlines()]
        sections: dict[str, list[str]] = {
            "experience": [],
            "education": [],
            "projects": [],
            "skills": [],
            "summary": [],
            "languages": [],
        }
        current_section: str | None = None

        for line in lines:
            if not line:
                continue

            matched_header = self._match_header(line)
            if matched_header:
                current_section = matched_header
                continue

            if current_section in sections:
                sections[current_section].append(line)

        return sections

    def _match_header(self, line: str) -> str | None:
        """
        Matches one CV line to a known section header.
        """
        for section, pattern in SECTION_HEADERS.items():
            if section == "skills" and re.match(r"^technologies\s*:\s*\S", line, re.IGNORECASE):
                continue
            if pattern.search(line):
                return section
        return None

    def _parse_text_for_nlp(self, text: str) -> ParsedText:
        # Stanza is the NLP sentence/token parser; regex fallback stays inside the helper.
        """
        Runs the Stanza-backed NLP parser with fallback behavior.
        """
        return parse_text_with_stanza(text)

    def _extract_skills_rule_based(
        self,
        normalized_text: str,
        original_text: str,
        parsed_text: ParsedText | None = None,
    ) -> tuple[list[SkillDetail], list[str], list[str]]:
        """
        Extract skills from CV text using rule-based matching with ESCO normalization.
        
        Returns:
            Tuple of (skills_with_details, negative_skills, learning_skills)
        """
        skills_found: list[SkillDetail] = []
        skills_set: set[str] = set()
        negative_skills: list[str] = []
        learning_skills: list[str] = []
        
        esco = self._get_esco_service() if self.use_esco else None
        sentences = self._sentence_candidates(original_text, parsed_text)

        for skill in SKILL_KEYWORDS:
            if not skill_in_text(skill, normalized_text):
                if not (" " in skill and fuzz.partial_ratio(skill.lower(), normalized_text) >= 90):
                    continue

            if skill in skills_set:
                continue
            skills_set.add(skill)

            status = SkillStatus.UNKNOWN
            years: float | None = None
            level = SkillLevel.UNKNOWN
            context: str | None = None
            confidence = 0.5
            normalized_skill: NormalizedSkill | None = None

            # Try ESCO normalization
            if esco:
                normalized_skill = esco.normalize_skill(skill)
                if normalized_skill:
                    confidence = max(confidence, normalized_skill.confidence)

            best_status = SkillStatus.UNKNOWN
            best_years: float | None = None
            best_level = SkillLevel.UNKNOWN
            best_confidence = 0.5
            best_context: str | None = None

            for sentence in sentences:
                sentence_lower = self._normalize_text(sentence)
                skill_match = build_skill_pattern(skill).search(sentence_lower)
                if not skill_match and not (
                    " " in skill and fuzz.partial_ratio(skill.lower(), sentence_lower) >= 90
                ):
                    continue

                sent_context = sentence.strip()
                sent_status = SkillStatus.UNKNOWN
                sent_years: float | None = None
                sent_level = SkillLevel.UNKNOWN
                sent_confidence = 0.6

                # Check for negation indicators (strong signal)
                for neg in NEGATION_INDICATORS:
                    if neg in sentence_lower:
                        neg_index = sentence_lower.find(neg)
                        skill_index = skill_match.start() if skill_match else sentence_lower.find(skill.lower())
                        if abs(neg_index - skill_index) < 100:
                            if "learn" in neg or "learning" in neg or "studying" in neg:
                                sent_status = SkillStatus.LEARNING
                            else:
                                sent_status = SkillStatus.NO_EXPERIENCE
                            sent_confidence = 0.85
                            break

                # Extract years of experience
                year_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:year|yr|years|yrs)", sentence_lower)
                if year_match and sent_status == SkillStatus.UNKNOWN:
                    sent_years = float(year_match.group(1))
                    if sent_years >= 5:
                        sent_level = SkillLevel.SENIOR
                    elif sent_years >= 2:
                        sent_level = SkillLevel.MID
                    else:
                        sent_level = SkillLevel.JUNIOR
                    sent_confidence = 0.75
                    sent_status = SkillStatus.HAS_EXPERIENCE

                if sent_status == SkillStatus.UNKNOWN:
                    sent_status = SkillStatus.HAS_EXPERIENCE

                # Keep sentence with highest priority: HAS_EXPERIENCE > LEARNING > NO_EXPERIENCE > UNKNOWN
                priority = {SkillStatus.HAS_EXPERIENCE: 3, SkillStatus.LEARNING: 2, SkillStatus.NO_EXPERIENCE: 1, SkillStatus.UNKNOWN: 0}
                if priority.get(sent_status, 0) > priority.get(best_status, 0):
                    best_status = sent_status
                    best_years = sent_years
                    best_level = sent_level
                    best_confidence = sent_confidence
                    best_context = sent_context

                # If we found HAS_EXPERIENCE with years, no need to look further
                if best_status == SkillStatus.HAS_EXPERIENCE and best_years is not None:
                    break

            status = best_status
            years = best_years
            level = best_level
            confidence = best_confidence
            context = best_context

            if status == SkillStatus.LEARNING:
                learning_skills.append(skill)
            elif status == SkillStatus.NO_EXPERIENCE:
                negative_skills.append(skill)

            skill_detail = SkillDetail(
                name=skill,
                level=level,
                years=years,
                status=status,
                confidence=confidence,
                context=context,
            )
            
            # Add ESCO metadata if available
            if normalized_skill:
                skill_detail.esco_uri = normalized_skill.esco_uri
                skill_detail.preferred_label = normalized_skill.preferred_label
                skill_detail.category = normalized_skill.category
            
            skills_found.append(skill_detail)

        return skills_found, negative_skills, learning_skills

    @staticmethod
    def _sentence_candidates(text: str, parsed_text: ParsedText | None = None) -> list[str]:
        """
        Builds unique sentence candidates from regex and Stanza parsing.
        """
        parsed_text = parsed_text or parse_text_with_stanza(text)
        regex_sentences = [part.strip() for part in re.split(r"[.!?\n]", text) if part.strip()]
        stanza_sentences = parsed_text.sentences if parsed_text.parser == "stanza" else []

        sentences: list[str] = []
        seen: set[str] = set()
        for sentence in regex_sentences + stanza_sentences:
            key = " ".join(sentence.lower().split())
            if key and key not in seen:
                seen.add(key)
                sentences.append(sentence)
        return sentences

    async def _extract_skills_with_llm(
        self,
        text: str,
        parsed_text: ParsedText | None = None,
    ) -> tuple[list[SkillDetail], list[str], list[str]]:
        """
        Combines rule-based skills with grounded LLM skill analysis.
        """
        llm_service = self._get_llm_service()
        if llm_service is None:
            return self._extract_skills_rule_based(self._normalize_text(text), text, parsed_text)

        try:
            rule_based_skills, rule_based_negative, rule_based_learning = self._extract_skills_rule_based(
                self._normalize_text(text),
                text,
                parsed_text,
            )
            analysis = await llm_service.analyze_cv_skills(text)
            raw_skills = analysis.get("skills_with_context", [])

            if not raw_skills:
                logger.warning("LLM returned no skills, falling back to rule-based")
                return rule_based_skills, rule_based_negative, rule_based_learning

            skills_found: list[SkillDetail] = []
            negative_skills = self._grounded_llm_list(analysis.get("negative_skills", []), text)
            learning_skills = self._grounded_llm_list(analysis.get("learning_skills", []), text)

            for skill_data in raw_skills:
                if not isinstance(skill_data, dict):
                    continue
                catalog_skill = canonicalize_skill_name(
                    str(skill_data.get("skill") or skill_data.get("name") or "")
                )
                if not catalog_skill:
                    logger.warning(
                        "Discarded non-catalog LLM CV skill",
                        extra={"skill": str(skill_data.get("skill", ""))[:80]},
                    )
                    continue
                if not self._llm_skill_is_grounded(skill_data, text):
                    logger.warning(
                        "Discarded ungrounded LLM CV skill",
                        extra={"skill": str(skill_data.get("skill", ""))[:80]},
                    )
                    continue
                status_map = {
                    "has_experience": SkillStatus.HAS_EXPERIENCE,
                    "learning": SkillStatus.LEARNING,
                    "no_experience": SkillStatus.NO_EXPERIENCE,
                }
                level_map = {
                    "junior": SkillLevel.JUNIOR,
                    "mid": SkillLevel.MID,
                    "senior": SkillLevel.SENIOR,
                    "expert": SkillLevel.EXPERT,
                }

                skill_detail = SkillDetail(
                    name=catalog_skill,
                    level=level_map.get(skill_data.get("level", "unknown"), SkillLevel.UNKNOWN),
                    years=skill_data.get("years"),
                    status=status_map.get(skill_data.get("status", "unknown"), SkillStatus.UNKNOWN),
                    confidence=skill_data.get("confidence", 0.5),
                    context=skill_data.get("context"),
                )
                skills_found.append(skill_detail)

            if not skills_found:
                logger.warning("LLM returned no grounded skills, falling back to rule-based")
                return rule_based_skills, rule_based_negative, rule_based_learning

            return (
                self._merge_skill_details(skills_found, rule_based_skills),
                validate_catalog_skill_list(negative_skills + rule_based_negative),
                validate_catalog_skill_list(learning_skills + rule_based_learning),
            )

        except Exception as e:
            logger.error("LLM skill extraction failed", extra={"error_type": type(e).__name__})
            return self._extract_skills_rule_based(self._normalize_text(text), text, parsed_text)

    @staticmethod
    def _merge_skill_details(
        primary: list[SkillDetail],
        fallback: list[SkillDetail],
    ) -> list[SkillDetail]:
        """
        Merges LLM and rule-based skill details while keeping stronger evidence.
        """
        merged: dict[str, SkillDetail] = {}
        for detail in primary + fallback:
            normalized = canonicalize_skill_name(detail.name)
            if not normalized:
                continue
            existing = merged.get(normalized)
            if existing is None:
                merged[normalized] = detail.model_copy(update={"name": normalized})
                continue

            priority = {
                SkillStatus.HAS_EXPERIENCE: 3,
                SkillStatus.UNKNOWN: 2,
                SkillStatus.LEARNING: 1,
                SkillStatus.NO_EXPERIENCE: 0,
            }
            if priority.get(detail.status, -1) > priority.get(existing.status, -1):
                merged[normalized] = detail.model_copy(update={"name": normalized})
        return list(merged.values())

    @staticmethod
    def _normalize_llm_list(items: list[Any]) -> list[str]:
        """
        Normalizes LLM skill list output into plain skill names.
        """
        if not isinstance(items, list):
            return []
        normalized: list[str] = []
        for item in items:
            if isinstance(item, str):
                normalized.append(item)
            elif isinstance(item, dict):
                name = item.get("skill") or item.get("name")
                if name:
                    normalized.append(str(name))
        return normalized

    def _grounded_llm_list(self, items: list[Any], text: str) -> list[str]:
        """
        Keeps only LLM-listed skills that are grounded in the CV text.
        """
        normalized: list[str] = []
        seen: set[str] = set()
        for skill in self._normalize_llm_list(items):
            skill_name = canonicalize_skill_name(skill)
            if not skill_name or skill_name in seen:
                continue
            if self._skill_name_is_grounded(skill_name, text):
                seen.add(skill_name)
                normalized.append(skill_name)
        return normalized[:100]

    def _llm_skill_is_grounded(self, skill_data: dict[str, Any], text: str) -> bool:
        """
        Checks whether one LLM skill extraction has text evidence in the CV.
        """
        skill_name = canonicalize_skill_name(str(skill_data.get("skill") or skill_data.get("name") or ""))
        if not skill_name:
            return False
        if self._skill_name_is_grounded(skill_name, text):
            return True
        context = str(skill_data.get("context") or "").strip()
        if not context:
            return False
        normalized_text = self._normalize_text(text)
        normalized_context = self._normalize_text(context)
        return bool(
            normalized_context
            and normalized_context in normalized_text
            and skill_in_text(skill_name, normalized_context)
        )

    def _skill_name_is_grounded(self, skill_name: str, text: str) -> bool:
        """
        Checks whether a canonical skill appears in the CV text.
        """
        normalized_text = self._normalize_text(text)
        normalized_skill = canonicalize_skill_name(skill_name)
        if not normalized_skill:
            return False
        return skill_in_text(normalized_skill, normalized_text)

    def _parse_experience_entries(self, experience_lines: list[str]) -> list[ExperienceEntry]:
        """
        Converts experience section lines into structured experience entries.
        """
        entries: list[ExperienceEntry] = []
        if not experience_lines:
            return entries

        current_entry: dict[str, Any] = {}
        description_lines: list[str] = []

        for line in experience_lines:
            date_pattern = r"(?:19|20)\d{2}\s*(?:[-–to]\s*(?:19|20)\d{2}|present|current|now)"
            date_match = re.search(date_pattern, line, re.IGNORECASE)

            title_patterns = [
                r"^(.+?)\s+at\s+(.+?)(?:\s*[-–|]\s*(.+))?$",
                r"^(.+?)\s*[-–|]\s*(.+?)(?:\s*[-–|]\s*(.+))?$",
            ]

            is_new_entry = False

            if date_match or re.match(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:at|in|with|for)\s+", line):
                if current_entry:
                    if description_lines:
                        current_entry["description"] = "\n".join(description_lines)
                    entries.append(ExperienceEntry(**current_entry))
                    current_entry = {}
                    description_lines = []
                is_new_entry = True

            if is_new_entry:
                for pattern in title_patterns:
                    match = re.match(pattern, line)
                    if match:
                        current_entry["title"] = match.group(1).strip()
                        current_entry["company"] = match.group(2).strip()
                        break

                if not current_entry.get("title"):
                    current_entry["title"] = line.strip()

                if date_match:
                    date_str = date_match.group(0)
                    parts = re.split(r"\s*[-–to]\s*", date_str, flags=re.IGNORECASE)
                    if len(parts) >= 1:
                        current_entry["start_date"] = parts[0].strip()
                    if len(parts) >= 2:
                        current_entry["end_date"] = parts[1].strip()
            else:
                if line.startswith(("-", "•", "*", "◦")) or len(description_lines) > 0:
                    description_lines.append(line.strip())

        if current_entry:
            if description_lines:
                current_entry["description"] = "\n".join(description_lines)
            entries.append(ExperienceEntry(**current_entry))

        return entries

    def _parse_education_entries(self, education_lines: list[str]) -> list[EducationEntry]:
        """
        Converts education section lines into structured education entries.
        """
        entries: list[EducationEntry] = []
        if not education_lines:
            return entries

        degree_keywords = [
            "bachelor", "master", "phd", "doctorate", "degree",
            "bsc", "msc", "ba", "ma", "mba", "diploma",
        ]

        current_entry: dict[str, Any] = {}

        for line in education_lines:
            line_lower = line.lower()

            has_degree = any(kw in line_lower for kw in degree_keywords)
            has_date = re.search(r"(?:19|20)\d{2}", line)

            if has_degree and current_entry:
                entries.append(EducationEntry(**current_entry))
                current_entry = {}

            if has_degree:
                current_entry["degree"] = line.strip()
            elif "gpa" in line_lower:
                current_entry["gpa"] = line.strip()
            elif has_date and not current_entry.get("end_date"):
                date_match = re.search(r"(?:19|20)\d{2}", line)
                if date_match:
                    current_entry["end_date"] = date_match.group(0)
            elif line.strip():
                if not current_entry.get("institution"):
                    current_entry["institution"] = line.strip()
                elif not current_entry.get("description"):
                    current_entry["description"] = line.strip()

        if current_entry:
            entries.append(EducationEntry(**current_entry))

        return entries

    def _calculate_total_years(self, entries: list[ExperienceEntry]) -> float | None:
        """
        Estimates total experience years from parsed date ranges.
        """
        total_years = 0.0
        has_calculable = False

        for entry in entries:
            if entry.start_date and entry.end_date:
                try:
                    start_match = re.search(r"(19|20)\d{2}", entry.start_date)
                    end_match = re.search(r"(19|20)\d{2}", entry.end_date) if entry.end_date else None

                    if start_match:
                        start_year = int(start_match.group(0))
                        if end_match and entry.end_date and "present" not in entry.end_date.lower():
                            end_year = int(end_match.group(0))
                            total_years += end_year - start_year
                        else:
                            from datetime import datetime

                            current_year = datetime.now().year
                            total_years += current_year - start_year
                        has_calculable = True
                except Exception:
                    continue

        return total_years if has_calculable else None

    def _extract_highest_degree(self, entries: list[EducationEntry]) -> str | None:
        """
        Finds the highest degree mentioned in parsed education entries.
        """
        degree_rank = {
            "phd": 7,
            "doctorate": 7,
            "doctoral": 7,
            "mba": 6,
            "master": 5,
            "msc": 5,
            "ma": 5,
            "bachelor": 4,
            "bsc": 4,
            "ba": 4,
            "diploma": 3,
            "associate": 2,
            "certificate": 1,
        }

        highest_rank = -1
        highest_degree = None

        for entry in entries:
            if entry.degree:
                degree_lower = entry.degree.lower()
                for keyword, rank in degree_rank.items():
                    if keyword in degree_lower and rank > highest_rank:
                        highest_rank = rank
                        highest_degree = entry.degree
                        break

        return highest_degree

    def _build_profile(
        self,
        text: str,
        skills_detailed: list[SkillDetail],
        negative_skills: list[str],
        learning_skills: list[str],
    ) -> CandidateProfile:
        """
        Builds the final structured candidate profile from extracted CV signals.
        """
        sections = self._extract_sections(text)

        full_name = self._extract_name(text)
        email = self._extract_email(text)
        phone = self._extract_phone(text)
        location = self._extract_location(text)
        languages = self._extract_languages(text, sections)

        skills = [s.name for s in skills_detailed if s.status not in {SkillStatus.NO_EXPERIENCE, SkillStatus.LEARNING}]

        experience_entries = self._parse_experience_entries(sections.get("experience", []))
        education_entries = self._parse_education_entries(sections.get("education", []))

        total_years = self._calculate_total_years(experience_entries)
        if total_years is None:
            total_match = re.search(r"Total Years of Experience:\s*([\d.]+)", text, re.IGNORECASE)
            if total_match:
                total_years = float(total_match.group(1))
        highest_degree = self._extract_highest_degree(education_entries)

        summary = "\n".join(sections.get("summary", [])) if sections.get("summary") else None

        profile = CandidateProfile(
            full_name=full_name,
            email=email,
            phone=phone,
            location=location,
            skills=skills,
            skills_detailed=skills_detailed,
            experience=sections.get("experience", []),
            experience_entries=experience_entries,
            total_years_experience=total_years,
            education=sections.get("education", []),
            education_entries=education_entries,
            highest_degree=highest_degree,
            projects=sections.get("projects", []),
            languages=languages,
            negative_skills=negative_skills,
            learning_skills=learning_skills,
            summary=summary,
            raw_text=text,
            parser_version="enhanced-v2",
        )

        logger.info(
            "CV parsed with enhanced parser",
            extra={
                "skills_count": len(skills),
                "negative_count": len(negative_skills),
                "learning_count": len(learning_skills),
                "total_years": total_years,
            },
        )

        return profile

    async def parse_async(self, text: str) -> CandidateProfile:
        """
        Parses CV text asynchronously, using the LLM path when enabled.
        """
        text = self._ensure_parseable_text(text)
        normalized = self._normalize_text(text)
        parsed_text = self._parse_text_for_nlp(text)
        if self.use_llm and self._get_llm_service():
            skills_detailed, negative_skills, learning_skills = await self._extract_skills_with_llm(text, parsed_text)
        else:
            skills_detailed, negative_skills, learning_skills = self._extract_skills_rule_based(normalized, text, parsed_text)

        return self._build_profile(text, skills_detailed, negative_skills, learning_skills)

    def parse(self, text: str) -> CandidateProfile:
        """
        Parses CV text synchronously when no event loop is already running.
        """
        text = self._ensure_parseable_text(text)
        normalized = self._normalize_text(text)
        parsed_text = self._parse_text_for_nlp(text)
        if not self.use_llm:
            skills_detailed, negative_skills, learning_skills = self._extract_skills_rule_based(normalized, text, parsed_text)
            return self._build_profile(text, skills_detailed, negative_skills, learning_skills)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.parse_async(text))

        raise RuntimeError("Use await parse_async() when parsing with LLM inside an async context")


def get_enhanced_cv_parser() -> EnhancedCVParser:
    """
    Creates an enhanced parser with LLM support enabled.
    """
    return EnhancedCVParser(use_llm=True)


def get_simple_cv_parser() -> EnhancedCVParser:
    """
    Creates an enhanced parser with LLM support disabled.
    """
    return EnhancedCVParser(use_llm=False)
