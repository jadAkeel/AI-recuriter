from __future__ import annotations

from typing import Any, Iterable, Sequence


def _bounded_join(items: Iterable[str] | None, limit: int) -> str:
    """
    Joins a limited number of text items for embedding input.
    """
    return " ".join(str(item).strip() for item in list(items or [])[:limit] if str(item).strip())


def build_candidate_embedding_text(
    *,
    skills: Sequence[str] | None = None,
    experience: Sequence[str] | None = None,
    education: Sequence[str] | None = None,
    projects: Sequence[str] | None = None,
    uncatalogued_skills: Sequence[str] | None = None,
    raw_text: str | None = None,
) -> str:
    """
    Builds compact candidate text for embedding generation.
    """
    parts: list[str] = []
    if skills:
        parts.append(f"Skills: {', '.join(str(skill).strip() for skill in skills if str(skill).strip())}")
    if uncatalogued_skills:
        parts.append(
            f"Additional detected skills: {', '.join(str(skill).strip() for skill in uncatalogued_skills if str(skill).strip())}"
        )
    experience_text = _bounded_join(experience, 10)
    if experience_text:
        parts.append(f"Experience: {experience_text}")
    education_text = _bounded_join(education, 5)
    if education_text:
        parts.append(f"Education: {education_text}")
    projects_text = _bounded_join(projects, 5)
    if projects_text:
        parts.append(f"Projects: {projects_text}")
    cv_text = " ".join(str(raw_text or "").split())
    if cv_text:
        parts.append(f"CV text: {cv_text[:4000]}")
    return ". ".join(parts)


def build_candidate_embedding_text_from_profile(profile) -> str:
    """
    Builds embedding text from a parsed candidate profile.
    """
    return build_candidate_embedding_text(
        skills=getattr(profile, "skills", None),
        experience=getattr(profile, "experience", None),
        education=getattr(profile, "education", None),
        projects=getattr(profile, "projects", None),
        uncatalogued_skills=getattr(profile, "uncatalogued_skills", None),
        raw_text=getattr(profile, "raw_text", None),
    )


def build_candidate_embedding_text_from_candidate(candidate) -> str:
    """
    Builds embedding text from a stored candidate record.
    """
    return build_candidate_embedding_text(
        skills=getattr(candidate, "skills", None),
        experience=getattr(candidate, "experience", None),
        education=getattr(candidate, "education", None),
        projects=getattr(candidate, "projects", None),
        uncatalogued_skills=getattr(candidate, "uncatalogued_skills", None),
        raw_text=getattr(candidate, "raw_text", None),
    )


async def upsert_candidate_embedding(session: Any, candidate_id: str, profile: Any) -> None:
    """
    Creates or updates the embedding stored for a candidate profile.
    """
    from app.services.embedding import embedding_metadata_for_text, get_embedding_service
    from app.services.vector_store import VectorStore

    embedding_text = build_candidate_embedding_text_from_profile(profile)
    embedder = get_embedding_service()
    embedding = (await embedder.embed([embedding_text]))[0]
    store = VectorStore(session)
    await store.upsert_embedding(
        "candidate",
        candidate_id,
        embedding,
        metadata=embedding_metadata_for_text(embedding_text),
    )
