"""No live model or external service: SSE lifecycle regressions."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_idle_heartbeat_does_not_cancel_the_model_iterator():
    from app.api.chat import _stream_with_heartbeat

    ready = asyncio.Event()
    closed = []

    async def source():
        try:
            await ready.wait()
            yield "data: result\n\n"
        finally:
            closed.append(True)

    stream = _stream_with_heartbeat(source(), interval=0.001)
    assert await anext(stream) == ": keepalive\n\n"
    assert await anext(stream) == ": keepalive\n\n"
    assert not closed
    ready.set()
    assert await anext(stream) == "data: result\n\n"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert closed == [True]


@pytest.mark.asyncio
async def test_disconnect_cancels_pending_work_and_closes_iterator():
    from app.api.chat import _stream_with_heartbeat

    closed = []

    async def source():
        try:
            await asyncio.Event().wait()
            yield "unreachable"
        finally:
            closed.append(True)

    stream = _stream_with_heartbeat(source(), interval=0.001)
    assert await anext(stream) == ": keepalive\n\n"
    await stream.aclose()
    assert closed == [True]


@pytest.mark.asyncio
async def test_source_failure_is_not_hidden_by_heartbeat():
    from app.api.chat import _stream_with_heartbeat

    async def source():
        yield "first"
        raise RuntimeError("synthetic failure")

    stream = _stream_with_heartbeat(source(), interval=0.001)
    assert await anext(stream) == "first"
    with pytest.raises(RuntimeError, match="synthetic failure"):
        await anext(stream)


@pytest.mark.asyncio
@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("save_fails", [False, True])
async def test_terminal_event_follows_persistence_attempt(monkeypatch, cached, save_fails):
    from app.api import chat
    from app.perception.context_package import ContextPackage
    import app.database as database
    import app.services.message_persistence as persistence

    saved = []

    async def build_context_package(**kwargs):
        return ContextPackage(
            raw_input=kwargs['raw_input'], rewritten_query=kwargs['raw_input'],
            company_id='65', intent_type='general', cache_hit=cached,
            direct_return='synthetic answer' if cached else None,
        )

    async def execute(_context):
        yield {'type': 'result', 'data': 'synthetic answer'}
        yield {'type': 'done'}

    def save(**_kwargs):
        saved.append('attempted')
        if save_fails:
            raise RuntimeError('synthetic persistence failure')

    monkeypatch.setattr(database, 'db', MagicMock())
    monkeypatch.setattr(persistence, 'get_or_create_conversation', lambda **kw: SimpleNamespace(id=42, message_count=0))
    monkeypatch.setattr(persistence, 'save_user_message', lambda **kw: None)
    monkeypatch.setattr(chat, '_persist_assistant_reply', save)
    monkeypatch.setattr(chat, '_get_perception_pipeline', lambda: SimpleNamespace(build_context_package=build_context_package))
    monkeypatch.setattr(chat, '_get_master_router', lambda: SimpleNamespace(execute=execute))
    monkeypatch.setattr(chat, '_build_company_context_from_db', lambda _: {})

    response = await chat.chat_stream(
        chat.ChatRequest(message='write a synthetic greeting', company_context={'name': 'fixture'}),
        req=SimpleNamespace(), current_user=SimpleNamespace(id=7, company_id=65),
    )
    assert response.media_type == 'text/event-stream'
    terminals = []
    async for chunk in response.body_iterator:
        if chunk.startswith('data: '):
            event = json.loads(chunk[6:].strip())
            if event['type'] == 'done':
                assert saved == ['attempted']
                assert event['history_saved'] is not save_fails
                assert event['conversation_id'] == 42
                terminals.append(event)
    assert len(terminals) == 1
