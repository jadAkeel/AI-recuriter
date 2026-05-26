import pytest
import asyncio
from app.core.config import settings
from app.services.embedding import (
    get_embedding_service,
    get_multilingual_embedding_service,
    get_standard_embedding_service,
    is_arabic,
    detect_language,
    embedding_metadata_for_text,
    validate_embedding_vector,
)
from app.services.vector_store import VectorStore
from app.services.rag import ingest_knowledge_base, query_knowledge
from sqlalchemy.ext.asyncio import AsyncSession


def test_arabic_detection() -> None:
    """
    Checks that Arabic characters are correctly detected.
    """
    assert is_arabic("بايثون") is True
    assert is_arabic("Python") is False
    assert is_arabic("Python بايثون") is True
    assert is_arabic("") is False
    assert is_arabic(None) is False


def test_language_detection() -> None:
    """
    Checks that language detection handles Arabic and English correctly.
    """
    assert detect_language("بايثون") == "ar"
    assert detect_language("Python developer") == "en"


@pytest.mark.asyncio
async def test_dynamic_dimensions_and_arabic_routing(monkeypatch) -> None:
    """
    Checks that Arabic texts route to multilingual model (768 dim)
    and English texts route to standard model (384 dim).
    """
    monkeypatch.setattr(settings, "embedding_provider", "hash")
    monkeypatch.setattr(settings, "auto_detect_lang", True)
    monkeypatch.setattr(settings, "use_multilingual_embedding", False)

    service = get_embedding_service()
    
    # English text
    eng_vectors = await service.embed(["python developer"])
    assert len(eng_vectors) == 1
    assert len(eng_vectors[0]) == 384
    
    # Arabic text
    ar_vectors = await service.embed(["مهندس بايثون"])
    assert len(ar_vectors) == 1
    assert len(ar_vectors[0]) == 768


def test_production_hash_provider_failure(monkeypatch) -> None:
    """
    Checks that Hash provider throws RuntimeError in production.
    """
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "embedding_provider", "hash")
    
    from app.services.embedding import _get_cached_embedding_service
    _get_cached_embedding_service.cache_clear()
    
    with pytest.raises(RuntimeError) as exc_info:
        get_embedding_service()
    assert "DevelopmentFallbackEmbedding" in str(exc_info.value)
    
    _get_cached_embedding_service.cache_clear()


def test_embedding_metadata_fallback_and_lang() -> None:
    """
    Checks that embedding metadata contains fallback status and language.
    """
    meta_eng = embedding_metadata_for_text("Python Developer", provider="hash")
    assert meta_eng["is_fallback"] is True
    assert meta_eng["embedding_language"] == "en"
    
    meta_ar = embedding_metadata_for_text("مهندس بايثون", provider="sentence-transformers")
    assert meta_ar["is_fallback"] is False
    assert meta_ar["embedding_language"] == "ar"


@pytest.mark.asyncio
async def test_rag_multilingual_query() -> None:
    """
    Validates RAG query language detection and language routing.
    """
    from app.core.db import SessionLocal, init_db
    await init_db()
    
    async with SessionLocal() as db_session:
        # Seed db
        await ingest_knowledge_base(db_session)
        
        # Query in Arabic
        ar_response = await query_knowledge(db_session, query="بايثون")
        assert ar_response.query_language == "ar"
        
        # Query in English
        en_response = await query_knowledge(db_session, query="Python programming")
        assert en_response.query_language == "en"


