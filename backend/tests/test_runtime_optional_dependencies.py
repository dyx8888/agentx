from unittest.mock import patch


def test_model_gateway_exposes_embedding_adapter(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODE", "hash")
    from app.services.model_gateway import ModelGateway

    service = ModelGateway().get_embeddings()

    assert service.embed_query("公开网页测试")


def test_optional_redis_defaults_to_memory(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    from app.core.checkpoint import RedisSaver
    from app.services.session_store import SessionStore

    with patch("app.core.checkpoint.logger") as checkpoint_logger:
        saver = RedisSaver()
        checkpoint_logger.info.assert_any_call("checkpoint_redis_disabled_using_memory")
    with patch("app.services.session_store.logger") as session_logger:
        store = SessionStore()
        session_logger.info.assert_any_call("session_store_redis_disabled_using_memory")

    assert not saver.is_available
    assert not store._redis_available
