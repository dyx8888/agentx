from app.skills.registry import SkillRegistry


def test_skill_embedding_precompute_is_opt_in(monkeypatch):
    monkeypatch.delenv("SKILL_EMBEDDINGS_ENABLED", raising=False)
    registry = SkillRegistry()
    registry._embedding_cache.clear()

    monkeypatch.setattr(registry, "_skills", {})
    registry._precompute_embeddings()
    assert registry._embedding_cache == {}
