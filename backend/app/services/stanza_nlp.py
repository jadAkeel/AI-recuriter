from __future__ import annotations

import functools
import logging
import re
from dataclasses import dataclass

try:
    import stanza
except Exception:  # pragma: no cover - Stanza is optional at runtime.
    stanza = None

logger = logging.getLogger(__name__)

STANZA_LANGUAGE = "en"
STANZA_PROCESSORS = "tokenize"


@dataclass(frozen=True)
class ParsedText:
    raw_text: str
    sentences: list[str]
    tokens: list[str]
    parser: str


@functools.lru_cache(maxsize=1)
def _get_stanza_pipeline():
    """Load Stanza lazily so missing models never break CV parsing."""
    if stanza is None:
        logger.debug("Stanza library unavailable")
        return None

    try:
        return _build_pipeline(stanza)
    except Exception as exc:
        logger.info(
            "Stanza language model unavailable; attempting download",
            extra={"language": STANZA_LANGUAGE, "error_type": type(exc).__name__},
        )

    try:
        stanza.download(STANZA_LANGUAGE, processors=STANZA_PROCESSORS, verbose=False)
        return _build_pipeline(stanza)
    except Exception as exc:
        logger.debug("Stanza pipeline unavailable", extra={"error_type": type(exc).__name__})
        return None


def _build_pipeline(stanza_module):
    """
    Builds the Stanza pipeline for tokenization and sentence splitting.
    """
    return stanza_module.Pipeline(
        lang=STANZA_LANGUAGE,
        processors=STANZA_PROCESSORS,
        use_gpu=False,
        verbose=False,
    )


def parse_text_with_stanza(text: str, *, max_chars: int = 8000) -> ParsedText:
    """Parse raw text with Stanza when available, with a regex fallback."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return ParsedText(raw_text="", sentences=[], tokens=[], parser="empty")

    pipeline = _get_stanza_pipeline()
    if pipeline is None:
        return _fallback_parse(cleaned)

    try:
        doc = pipeline(cleaned[:max_chars])
    except Exception as exc:
        logger.debug("Stanza sentence splitting failed", extra={"error_type": type(exc).__name__})
        return _fallback_parse(cleaned)

    sentences: list[str] = []
    tokens: list[str] = []
    for sentence in getattr(doc, "sentences", []) or []:
        words = [
            word.text
            for word in getattr(sentence, "words", []) or []
            if getattr(word, "text", "")
        ]
        tokens.extend(words)
        text_value = " ".join(words).strip()
        if text_value:
            sentences.append(text_value)
    if not sentences:
        return _fallback_parse(cleaned)
    return ParsedText(raw_text=cleaned, sentences=sentences, tokens=tokens, parser="stanza")


def split_sentences_with_stanza(text: str, *, max_chars: int = 8000) -> list[str]:
    """
    Returns sentence splits from the Stanza-backed parser.
    """
    parsed = parse_text_with_stanza(text, max_chars=max_chars)
    return parsed.sentences if parsed.parser == "stanza" else []


def _fallback_parse(text: str) -> ParsedText:
    """
    Splits text into simple sentences and tokens when Stanza is unavailable.
    """
    sentences = [part.strip() for part in re.split(r"[.!?\n]", text) if part.strip()]
    tokens = re.findall(r"\b\w[\w+#.-]*\b", text)
    return ParsedText(raw_text=text, sentences=sentences, tokens=tokens, parser="regex_fallback")
