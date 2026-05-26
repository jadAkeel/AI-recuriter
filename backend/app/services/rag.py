from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeDocument
from app.schemas.rag import DocumentItem, IngestResponse, QueryResponse
from app.services.embedding import (
    get_embedding_service,
    get_multilingual_embedding_service,
    get_standard_embedding_service,
    is_arabic,
    detect_language,
)

logger = logging.getLogger(__name__)

INITIAL_KNOWLEDGE: list[dict[str, Any]] = [
    {
        "title": "Python Skill Definition",
        "content": "Python is a high-level, interpreted programming language known for readability and versatility. Used in web development, data science, machine learning, and automation. Key concepts: dynamic typing, garbage collection, list comprehensions, generators, decorators, context managers.",
        "category": "skill",
        "tags": ["python", "programming", "backend"],
    },
    {
        "title": "NLP Skill Definition",
        "content": "Natural Language Processing involves enabling computers to understand, interpret, and generate human language. Key techniques: tokenization, stemming, named entity recognition, sentiment analysis, word embeddings, transformer architectures (BERT, GPT), sequence labeling, text classification.",
        "category": "skill",
        "tags": ["nlp", "machine learning", "ai"],
    },
    {
        "title": "Seniority Evaluation Guidelines",
        "content": "Junior: 0-2 years experience, works under guidance, foundational knowledge. Mid-level: 2-5 years, independent contributor, solid problem-solving. Senior: 5+ years, technical leadership, architectural decisions, mentoring.",
        "category": "policy",
        "tags": ["seniority", "evaluation", "hiring"],
    },
    {
        "title": "Hiring Best Practices",
        "content": "Focus on both technical skills and cultural fit. Evaluate problem-solving approach over memorized answers. Consider diversity and inclusion. Use structured interviews with consistent scoring. Provide constructive feedback to all candidates.",
        "category": "policy",
        "tags": ["hiring", "best-practices", "recruitment"],
    },
    {
        "title": "Docker Skill Definition",
        "content": "Docker is a containerization platform that enables packaging applications with their dependencies into containers. Key concepts: images, containers, Dockerfile, docker-compose, volumes, networks, multi-stage builds, container orchestration.",
        "category": "skill",
        "tags": ["docker", "devops", "containers"],
    },
]


async def _generate_and_store_embedding(document: KnowledgeDocument) -> None:
    """
    Generates English and Multilingual embeddings for a knowledge document when possible.
    """
    try:
        std_embedder = get_standard_embedding_service()
        std_emb = (await std_embedder.embed([document.content]))[0]
        document.embedding = std_emb
    except Exception:
        logger.warning("Failed to generate standard embedding for document: %s", document.title)

    try:
        multi_embedder = get_multilingual_embedding_service()
        multi_emb = (await multi_embedder.embed([document.content]))[0]
        document.embedding_multilingual = multi_emb
    except Exception:
        logger.warning("Failed to generate multilingual embedding for document: %s", document.title)



async def ingest_knowledge_base(session: AsyncSession) -> int:
    """
    Seeds the database with built-in knowledge documents.
    """
    count = 0
    for doc in INITIAL_KNOWLEDGE:
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.title == doc["title"]
        )
        result = await session.execute(stmt)
        if result.scalar_one_or_none():
            continue
        document = KnowledgeDocument(
            id=str(uuid.uuid4()),
            title=doc["title"],
            content=doc["content"],
            category=doc["category"],
            tags=doc["tags"],
        )
        await _generate_and_store_embedding(document)
        session.add(document)
        count += 1
    await session.commit()
    return count


async def add_document(
    session: AsyncSession,
    title: str,
    content: str,
    category: str,
    tags: list[str],
) -> IngestResponse:
    """
    Adds one knowledge document and its embedding to the database.
    """
    document = KnowledgeDocument(
        id=str(uuid.uuid4()),
        title=title,
        content=content,
        category=category,
        tags=tags,
    )
    await _generate_and_store_embedding(document)
    session.add(document)
    await session.commit()
    return IngestResponse(document_id=document.id, title=title, category=category)


async def query_knowledge(
    session: AsyncSession,
    query: str,
    category: str | None = None,
    top_k: int = 5,
) -> QueryResponse:
    """
    Ranks knowledge documents by embedding similarity to a query.
    """
    stmt = select(KnowledgeDocument)
    if category:
        stmt = stmt.where(KnowledgeDocument.category == category)
    result = await session.execute(stmt)
    documents = result.scalars().all()

    # Auto-detect language
    query_language = detect_language(query)
    use_multilingual = query_language == "ar"

    try:
        if use_multilingual:
            embedder = get_multilingual_embedding_service()
        else:
            embedder = get_standard_embedding_service()
            
        query_emb = (await embedder.embed([query]))[0]
    except Exception:
        logger.warning("Knowledge query embedding failed")
        return QueryResponse(query=query, results=[], query_language=query_language)

    import numpy as np
    query_np = np.array(query_emb)
    query_norm = np.linalg.norm(query_np)
    scored: list[tuple[KnowledgeDocument, float]] = []
    for doc in documents:
        # If query is Arabic/Multilingual, rank against embedding_multilingual.
        # Otherwise, rank against standard embedding.
        emb = doc.embedding_multilingual if use_multilingual else doc.embedding
        if emb is None:
            emb = doc.embedding if use_multilingual else doc.embedding_multilingual
            
        if emb is None:
            continue
            
        # Safeguard dimension mismatch
        if len(emb) != len(query_emb):
            continue
            
        doc_np = np.array(emb)
        sim = float(np.dot(query_np, doc_np) / (query_norm * np.linalg.norm(doc_np) + 1e-8))
        scored.append((doc, sim))

    scored.sort(key=lambda x: x[1], reverse=True)
    results = [
        DocumentItem(
            document_id=doc.id,
            title=doc.title,
            content=doc.content,
            category=doc.category,
            score=round(score, 4),
        )
        for doc, score in scored[:top_k]
    ]
    return QueryResponse(query=query, results=results, query_language=query_language)


async def get_skill_definitions(
    skills: list[str],
    session: AsyncSession | None = None,
) -> dict[str, str]:
    """
    Returns knowledge-base definitions for requested skills.
    """
    if session is None:
        from app.core.db import SessionLocal

        async with SessionLocal() as managed_session:
            return await get_skill_definitions(skills, managed_session)

    normalized_skills = [" ".join(skill.lower().split()) for skill in skills if str(skill).strip()]
    if not normalized_skills:
        return {}

    result = await session.execute(select(KnowledgeDocument).where(KnowledgeDocument.category == "skill"))
    documents = result.scalars().all()
    definitions: dict[str, str] = {}
    for skill in normalized_skills:
        best: tuple[KnowledgeDocument, int] | None = None
        for document in documents:
            title = " ".join((document.title or "").lower().split())
            tags = {" ".join(str(tag).lower().split()) for tag in document.tags or []}
            score = 0
            if skill in tags:
                score = 3
            elif skill in title:
                score = 2
            elif skill in " ".join((document.content or "").lower().split()):
                score = 1
            if score and (best is None or score > best[1]):
                best = (document, score)
        if best:
            definitions[skill] = best[0].content
    return definitions
