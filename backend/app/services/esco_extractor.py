from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from app.core.config import settings
from app.schemas.esco import EscoExtractionResult, EscoSkill, EscoSkillMatch
from app.services.embedding import EmbeddingProvider

logger = logging.getLogger(__name__)

ESCO_API_BASE = "https://ec.europa.eu/esco/api"
CACHE_DIR = Path(settings.cv_storage_path).parent / "esco_cache"
CACHE_FILE = CACHE_DIR / "esco_skills.json"
EMBEDDINGS_FILE = CACHE_DIR / "esco_embeddings.npy"
SKILLS_LIST_FILE = CACHE_DIR / "esco_skills_list.json"

DEFAULT_BATCH_SIZE = 100
DEFAULT_THRESHOLD = 0.55
DEFAULT_TOP_K = 30

TECH_SKILL_FILTER = {
    "programming", "software", "development", "framework", "database",
    "cloud", "devops", "machine learning", "data", "api", "web",
    "algorithm", "computing", "network", "security", "automation",
    "artificial intelligence", "nlp", "computer vision",
    "testing", "deployment", "infrastructure", "architecture",
    "engineering", "analysis", "modelling", "design",
}


class EscoSkillExtractor:
    def __init__(self, threshold: float = DEFAULT_THRESHOLD) -> None:
        self.threshold = threshold
        self._skills: list[EscoSkill] = []
        self._embeddings: np.ndarray | None = None
        self._embedding_service: EmbeddingProvider | None = None

    # ── Public API ─────────────────────────────────────────────

    async def extract_skills(
        self, text: str, top_k: int = DEFAULT_TOP_K
    ) -> EscoExtractionResult:
        if not self._skills:
            await self._load_or_fetch()

        if not self._skills:
            logger.warning("No ESCO skills available, returning empty result")
            return EscoExtractionResult(skills=[], total_esco_skills=0)

        if self._embeddings is None:
            await self._compute_embeddings()

        emb_svc = self._get_embedding_service()
        embed_result = await emb_svc.embed([text])
        query_vec = np.array(embed_result[0], dtype=np.float32)
        query_norm = np.linalg.norm(query_vec) or 1.0

        emb_norms = np.linalg.norm(self._embeddings, axis=1)
        emb_norms[emb_norms == 0] = 1.0
        scores = np.dot(self._embeddings, query_vec) / (query_norm * emb_norms)

        top_indices = np.argsort(scores)[-top_k:][::-1]

        matches: list[EscoSkillMatch] = []
        for idx in top_indices:
            score = float(scores[idx])
            if score < self.threshold:
                continue
            skill = self._skills[idx]
            matches.append(
                EscoSkillMatch(skill=skill, score=round(score, 4))
            )

        logger.info(
            "ESCO extraction complete",
            extra={
                "input_length": len(text),
                "matches": len(matches),
                "top_score": matches[0].score if matches else 0,
            },
        )
        return EscoExtractionResult(
            skills=matches,
            total_esco_skills=len(self._skills),
        )

    async def skill_count(self) -> int:
        if not self._skills:
            await self._load_or_fetch()
        return len(self._skills)

    # ── Fetch from ESCO API ────────────────────────────────────

    async def fetch_and_cache(self) -> int:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        skills: list[dict[str, Any]] = []
        offset = 0
        total = None

        async with httpx.AsyncClient(timeout=30) as client:
            while total is None or offset < total:
                try:
                    resp = await client.get(
                        f"{ESCO_API_BASE}/search",
                        params={
                            "language": "en",
                            "type": "skill",
                            "limit": DEFAULT_BATCH_SIZE,
                            "offset": offset,
                            "full": "true",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    logger.error(f"ESCO API fetch failed at offset {offset}: {e}")
                    break

                if total is None:
                    total = data.get("total", 0)
                    logger.info("ESCO API total skills: %s", total)

                for item in data.get("_embedded", {}).get("results", []):
                    title = item.get("title", "")
                    if not title:
                        continue
                    preferred = item.get("preferredLabel", {})
                    description = preferred.get("en") if isinstance(preferred, dict) else None
                    skill = {
                        "uri": item.get("uri", ""),
                        "title": title,
                        "description": description,
                        "skill_type": _get_skill_type(item),
                        "reuse_level": _get_reuse_level(item),
                        "broader_skills": _get_broader_titles(item),
                    }
                    skills.append(skill)

                offset += DEFAULT_BATCH_SIZE
                logger.debug("Fetched %d/%d ESCO skills", min(offset, total or 0), total or 0)

        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"skills": skills, "total": len(skills), "updated": time.time()}, f)

        logger.info("Cached %d ESCO skills to %s", len(skills), CACHE_FILE)
        return len(skills)

    # ── Cache management ───────────────────────────────────────

    async def _load_or_fetch(self) -> None:
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._skills = [EscoSkill(**s) for s in data.get("skills", [])]
                logger.info("Loaded %d ESCO skills from cache", len(self._skills))
                await self._load_embeddings()
                return
            except Exception as e:
                logger.warning(f"Failed to load ESCO cache: {e}")

        logger.info("ESCO cache not found, fetching from API...")
        count = await self.fetch_and_cache()
        if count > 0:
            await self._load_or_fetch()
        else:
            logger.error("Failed to fetch any ESCO skills")

    async def _compute_embeddings(self) -> None:
        if self._embeddings is not None:
            return
        if not self._skills:
            return

        emb_svc = self._get_embedding_service()
        titles = [s.title for s in self._skills]
        logger.info("Computing embeddings for %d ESCO skills...", len(titles))

        try:
            vectors = await emb_svc.embed(titles)
            self._embeddings = np.array(vectors, dtype=np.float32)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            np.save(str(EMBEDDINGS_FILE), self._embeddings)
            with open(SKILLS_LIST_FILE, "w", encoding="utf-8") as f:
                json.dump(titles, f)
            logger.info("ESCO embeddings computed and cached")
        except Exception as e:
            logger.error(f"ESCO embedding computation failed: {e}")
            self._embeddings = np.zeros((len(self._skills), 384), dtype=np.float32)

    async def _load_embeddings(self) -> None:
        if EMBEDDINGS_FILE.exists() and SKILLS_LIST_FILE.exists():
            try:
                self._embeddings = np.load(str(EMBEDDINGS_FILE))
                logger.info("Loaded ESCO embeddings from cache")
            except Exception as e:
                logger.warning(f"Failed to load ESCO embeddings: {e}")

    def _get_embedding_service(self):
        if self._embedding_service is None:
            from app.services.embedding import get_embedding_service
            self._embedding_service = get_embedding_service()
        return self._embedding_service


# ── Helpers ────────────────────────────────────────────────────

def _get_skill_type(item: dict) -> str | None:
    types = item.get("hasSkillType", [])
    if types:
        uri = types[0]
        return uri.rsplit("/", 1)[-1] if isinstance(uri, str) else None
    return None


def _get_reuse_level(item: dict) -> str | None:
    levels = item.get("hasReuseLevel", [])
    if levels:
        uri = levels[0]
        return uri.rsplit("/", 1)[-1] if isinstance(uri, str) else None
    return None


def _get_broader_titles(item: dict) -> list[str]:
    broader = item.get("broaderSkill", [])
    titles: list[str] = []
    for b in broader:
        if isinstance(b, str):
            titles.append(b.rsplit("/", 1)[-1].replace("-", " "))
    return titles


# ── Singleton ──────────────────────────────────────────────────

_extractor_instance: EscoSkillExtractor | None = None


async def get_esco_extractor() -> EscoSkillExtractor:
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = EscoSkillExtractor()
        await _extractor_instance._load_or_fetch()
    return _extractor_instance
