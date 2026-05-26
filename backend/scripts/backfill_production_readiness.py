from __future__ import annotations

import argparse
import asyncio
import json
import logging

from app.core.db import SessionLocal, init_db
from app.services.production_backfill import run_production_backfill


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Run idempotent production-readiness backfill.")
    parser.add_argument("--dry-run", action="store_true", help="Report intended changes without committing.")
    parser.add_argument("--rebuild-embeddings", action="store_true", help="Recompute candidate and job embeddings.")
    args = parser.parse_args()

    await init_db()
    async with SessionLocal() as session:
        summary = await run_production_backfill(
            session,
            dry_run=args.dry_run,
            rebuild_embeddings=args.rebuild_embeddings,
        )
    print(json.dumps(summary.to_dict(), indent=2, sort_keys=True))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
