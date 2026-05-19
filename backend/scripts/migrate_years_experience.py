"""
Backfill total_years_experience for existing candidates
using the year-estimation logic from matching service.
Run: python -m app.migrate_years_experience
"""
from __future__ import annotations

import asyncio
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal, init_db
from app.models.candidate import Candidate

logger = logging.getLogger(__name__)
YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")


def _estimate_years(experience_entries: list[str]) -> float | None:
    """
    Estimates years of experience from stored experience text.
    """
    years: set[int] = set()
    for entry in experience_entries:
        found = YEAR_PATTERN.findall(entry)
        for y in found:
            years.add(int(y))
    if len(years) >= 2:
        return float(max(years) - min(years))
    return None


async def migrate() -> None:
    """
    Backfills total years of experience for existing candidates.
    """
    await init_db()
    async with SessionLocal() as session:
        result = await session.execute(select(Candidate))
        candidates: list[Candidate] = list(result.scalars().all())

        updated = 0
        for c in candidates:
            if c.total_years_experience is not None:
                continue
            est = _estimate_years(c.experience or [])
            if est is not None:
                c.total_years_experience = est
                updated += 1

        await session.commit()
        print(f"Updated {updated} of {len(candidates)} candidates with estimated years.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(migrate())
