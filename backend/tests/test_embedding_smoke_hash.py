import numpy as np
import pytest

from app.rag import embedding_service as embedding


def test_smoke_hash_embedding_does_not_load_sentence_transformer(monkeypatch):
    def fail_load_model(self):
        pytest.fail("hash embedding mode must not load SentenceTransformer")

    monkeypatch.setattr(embedding.EmbeddingService, "_load_model", fail_load_model)

    service = embedding.EmbeddingService(mode=embedding.EmbeddingMode.HASH)
    assert service.dimension == 512

    vectors = service.encode(["灵鹿小黑瓶", "灵鹿小黑瓶"])

    assert vectors.shape == (2, 512)
    assert vectors.dtype == np.float32
    np.testing.assert_allclose(vectors[0], vectors[1])
    assert abs(float(np.dot(vectors[0], vectors[0])) - 1.0) < 0.01


@pytest.mark.asyncio
async def test_smoke_hash_embedding_async_path_does_not_load_model(monkeypatch):
    def fail_load_model(self):
        pytest.fail("hash embedding async path must not load SentenceTransformer")

    monkeypatch.setattr(embedding.EmbeddingService, "_load_model", fail_load_model)

    service = embedding.EmbeddingService(mode=embedding.EmbeddingMode.HASH)
    vectors = await service.encode_async(["售后规则", "库存规则"])

    assert vectors.shape == (2, 512)
    assert vectors.dtype == np.float32


def test_smoke_hash_env_overrides_local_embedding_without_loading_model(monkeypatch):
    def fail_load_model(self):
        pytest.fail("AGENTX_SMOKE_EMBEDDING_MODE=hash must not load SentenceTransformer")

    monkeypatch.setenv("AGENTX_SMOKE_EMBEDDING_MODE", "hash")
    monkeypatch.setenv("EMBEDDING_MODE", "local")
    monkeypatch.setattr(embedding.EmbeddingService, "_load_model", fail_load_model)
    embedding.set_embedding_service(None)

    try:
        service = embedding.get_embedding_service()
        assert service.mode == embedding.EmbeddingMode.HASH
        assert service.encode(["合成知识"]).shape == (1, 512)
    finally:
        embedding.set_embedding_service(None)


def test_default_embedding_mode_remains_local(monkeypatch):
    monkeypatch.delenv("AGENTX_SMOKE_EMBEDDING_MODE", raising=False)
    monkeypatch.delenv("EMBEDDING_MODE", raising=False)

    assert embedding._embedding_mode_from_env() == embedding.EmbeddingMode.LOCAL


def test_invalid_smoke_embedding_mode_is_ignored(monkeypatch):
    monkeypatch.setenv("AGENTX_SMOKE_EMBEDDING_MODE", "invalid")
    monkeypatch.setenv("EMBEDDING_MODE", "local")

    assert embedding._embedding_mode_from_env() == embedding.EmbeddingMode.LOCAL