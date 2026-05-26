from __future__ import annotations

import json
from pathlib import Path

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "backend" / "data" / "extra_skills.json"

DEFAULT_EXTRA_SKILLS = {
    "categories": {
        "AI/ML Tools": [
            "semantic search",
            "retrieval augmented generation",
            "prompt evaluation",
            "embedding search",
            "reranking",
            "guardrails",
            "agentic workflows",
        ],
        "Databases": [
            "pgvector",
            "pinecone",
            "qdrant",
            "weaviate",
            "milvus",
            "duckdb",
        ],
        "DevOps Tools": [
            "github workflows",
            "docker swarm",
            "kubernetes operators",
            "platform engineering",
        ],
    }
}


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if OUTPUT_PATH.exists():
        try:
            existing = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    categories = existing.get("categories", {}) if isinstance(existing, dict) else {}
    for category, skills in DEFAULT_EXTRA_SKILLS["categories"].items():
        target = categories.setdefault(category, [])
        seen = {str(skill).lower().strip() for skill in target}
        for skill in skills:
            if skill not in seen:
                target.append(skill)
                seen.add(skill)
    OUTPUT_PATH.write_text(json.dumps({"categories": categories}, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(skills) for skills in categories.values())
    print(f"Saved {total} extra skills to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
