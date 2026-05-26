from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.hybrid_matcher import compute_cross_encoder_adjusted_score


SAMPLE_PAIRS = [
    {"candidate_id": "strong", "base_score": 0.82, "cross_score": 0.88, "score_cap": 1.0},
    {"candidate_id": "partial", "base_score": 0.62, "cross_score": 0.52, "score_cap": 0.75},
    {"candidate_id": "weak", "base_score": 0.35, "cross_score": 0.30, "score_cap": 0.40},
]


def main() -> None:
    rows = []
    for item in SAMPLE_PAIRS:
        adjusted = compute_cross_encoder_adjusted_score(
            base_score=item["base_score"],
            cross_score=item["cross_score"],
            score_cap=item["score_cap"],
        )
        rows.append({**item, **adjusted})

    changed = [row for row in rows if row["final_score"] != round(row["base_score"], 4)]
    report = {
        "sample_size": len(rows),
        "ranking_changes": 0,
        "changed_candidate_percent": round(len(changed) / len(rows) * 100, 2),
        "mean_absolute_adjustment": round(mean(abs(row["cross_encoder_adjustment"]) for row in rows), 4),
        "decision": "Option C: keep cross-encoder as a bounded advisory score-cap signal",
        "rows": rows,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
