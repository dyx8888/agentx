from types import SimpleNamespace

import pytest

from app.api import chat
from app.perception.context_package import ContextPackage


class _FakePipeline:
    def __init__(self):
        self.kwargs = None

    async def build_context_package(self, **kwargs):
        self.kwargs = kwargs
        return ContextPackage(
            rewritten_query=kwargs["raw_input"],
            raw_input=kwargs["raw_input"],
            intent_type="general",
            company_id=kwargs["company_id"],
            memory_context=[{"source": "memory"}],
            similar_answers=[{"source": "similar"}],
        )


class _FakeRouter:
    def __init__(self):
        self.context_package = None

    async def execute(self, context_package):
        self.context_package = context_package
        yield {"type": "result", "data": "ok"}
        yield {"type": "done"}


class _DummySession:
    def __enter__(self):
        return object()

    def __exit__(self, *_args):
        return False


class _DummyDB:
    def get_session(self):
        return _DummySession()


async def _collect_chat_stream(monkeypatch, *, smoke_env_value=None):
    import app.database as database_module
    import app.services.message_persistence as persistence_module

    fake_pipeline = _FakePipeline()
    fake_router = _FakeRouter()

    if smoke_env_value is None:
        monkeypatch.delenv("AGENTX_SMOKE_DISABLE_RAG_PRERETRIEVAL", raising=False)
    else:
        monkeypatch.setenv("AGENTX_SMOKE_DISABLE_RAG_PRERETRIEVAL", smoke_env_value)

    monkeypatch.setattr(chat, "_get_perception_pipeline", lambda: fake_pipeline)
    monkeypatch.setattr(chat, "_get_master_router", lambda: fake_router)
    monkeypatch.setattr(chat, "_build_company_context_from_db", lambda _company_id: {})
    monkeypatch.setattr(chat, "_persist_assistant_reply", lambda **_kwargs: None)
    monkeypatch.setattr(database_module, "db", _DummyDB())
    monkeypatch.setattr(
        persistence_module,
        "get_or_create_conversation",
        lambda **_kwargs: SimpleNamespace(id=123, message_count=0),
    )
    monkeypatch.setattr(persistence_module, "save_user_message", lambda **_kwargs: None)

    response = await chat.chat_stream(
        chat.ChatRequest(message="AgentRuntime SSE smoke ok", company_context={"brand": "x"}),
        req=SimpleNamespace(),
        current_user=SimpleNamespace(id=7, company_id=65),
    )

    body = []
    async for chunk in response.body_iterator:
        body.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)

    return fake_pipeline, fake_router, "".join(body)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["1", "true", "yes"])
async def test_smoke_rag_preretrieval_env_passes_skip_rag(monkeypatch, value):
    fake_pipeline, fake_router, body = await _collect_chat_stream(
        monkeypatch, smoke_env_value=value
    )

    assert fake_pipeline.kwargs["skip_rag"] is True
    assert fake_router.context_package.memory_context == [{"source": "memory"}]
    assert fake_router.context_package.similar_answers == [{"source": "similar"}]
    assert "ok" in body


@pytest.mark.asyncio
async def test_chat_rag_preretrieval_allowed_by_default(monkeypatch):
    fake_pipeline, _, _ = await _collect_chat_stream(monkeypatch)

    assert fake_pipeline.kwargs["skip_rag"] is False
