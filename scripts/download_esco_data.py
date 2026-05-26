from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

ESCO_API = "https://ec.europa.eu/esco/api"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "backend" / "data" / "esco_skills.json"


def _fallback_payload() -> dict[str, Any]:
    """Returns a small ESCO-shaped seed set for offline development."""
    with OUTPUT_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _normalize_skill(item: dict[str, Any]) -> dict[str, Any]:
    uri = item.get("uri") or item.get("conceptUri") or item.get("href") or ""
    preferred = item.get("preferredLabel") or item.get("title") or item.get("label") or ""
    if isinstance(preferred, str):
        preferred_label = {"en": preferred}
    else:
        preferred_label = preferred
    return {
        "uri": uri,
        "preferredLabel": preferred_label,
        "altLabels": item.get("altLabels") or {"en": item.get("alternativeLabel", []) or []},
        "description": item.get("description"),
        "skillType": item.get("skillType", "skill"),
        "broader": item.get("broader") or item.get("broader_skills") or [],
        "narrower": item.get("narrower") or item.get("narrower_skills") or [],
        "related": item.get("related") or item.get("related_skills") or [],
    }


def download_esco_data(limit: int = 200) -> dict[str, Any]:
    """Fetches ESCO skills and returns a normalized JSON payload."""
    fallback = _fallback_payload()
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{ESCO_API}/search",
                params={"type": "skill", "language": "en", "limit": limit},
            )
            response.raise_for_status()
            data = response.json()
        raw_skills = data.get("_embedded", {}).get("results", data.get("results", []))
        skills = [_normalize_skill(item) for item in raw_skills if isinstance(item, dict)]
        if skills:
            by_uri = {skill["uri"]: skill for skill in fallback.get("skills", []) if skill.get("uri")}
            for skill in skills:
                if skill.get("uri"):
                    by_uri.setdefault(skill["uri"], skill)
            return {"skills": list(by_uri.values()), "skillGroups": fallback.get("skillGroups", [])}
    except Exception as exc:
        print(f"ESCO download failed, using local fallback: {type(exc).__name__}")
    return fallback


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = download_esco_data()
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(payload.get('skills', []))} ESCO skills to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
