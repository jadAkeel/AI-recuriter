import json

import numpy as np
import pytest

from app.core.config import settings
from app.schemas.esco import EscoSkill
from app.services import esco_extractor as esco_module
from app.services.esco_extractor import EscoSkillExtractor


@pytest.mark.asyncio
async def test_esco_embedding_cache_dimension_mismatch_is_ignored(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Checks that ESCO embedding cache dimension mismatch is ignored.
    """
    embeddings_file = tmp_path / "esco_embeddings.npy"
    skills_list_file = tmp_path / "esco_skills_list.json"
    np.save(str(embeddings_file), np.zeros((1, settings.embedding_dimension + 1), dtype=np.float32))
    skills_list_file.write_text(json.dumps(["python"]), encoding="utf-8")

    monkeypatch.setattr(esco_module, "EMBEDDINGS_FILE", embeddings_file)
    monkeypatch.setattr(esco_module, "SKILLS_LIST_FILE", skills_list_file)

    extractor = EscoSkillExtractor()
    extractor._skills = [EscoSkill(uri="esco:python", title="python")]

    await extractor._load_embeddings()

    assert extractor._embeddings is None
