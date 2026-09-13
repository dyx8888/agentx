"""Current chat-route contract tests for the public-demo master assistant."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import chat
from app.auth import get_current_active_user
from app.main import app
from app.perception.context_package import ContextPackage


class _FakePipeline:
    async def build_context_package(self, **kwargs):
        return ContextPackage(
            rewritten_query=kwargs["raw_input"],
            raw_input=kwargs["raw_input"],
            intent_type="general",
            company_id=kwargs["company_id"],
            memory_context=[],
            similar_answers=[],
        )


class _FakeRouter:
    async def execute(self, _context_package):
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


@pytest.fixture
def client(monkeypatch):
    import app.database as database_module
    import app.services.message_persistence as persistence_module

    user = SimpleNamespace(
        id=7, company_id=65, is_active=True, disabled=False, is_admin=False
    )
    monkeypatch.setattr(chat, "_get_perception_pipeline", lambda: _FakePipeline())
    monkeypatch.setattr(chat, "_get_master_router", lambda: _FakeRouter())
    monkeypatch.setattr(chat, "_build_company_context_from_db", lambda _company_id: {})
    monkeypatch.setattr(chat, "_persist_assistant_reply", lambda **_kwargs: None)
    monkeypatch.setattr(database_module, "db", _DummyDB())
    monkeypatch.setattr(
        persistence_module,
        "get_or_create_conversation",
        lambda **_kwargs: SimpleNamespace(id=123, message_count=0),
    )
    monkeypatch.setattr(persistence_module, "save_user_message", lambda **_kwargs: None)

    app.dependency_overrides[get_current_active_user] = lambda: user
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        test_client.close()


def _parse_sse(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def _stream(client, message: str, **extra):
    payload = {"message": message, **extra}
    with client.stream("POST", "/api/chat", json=payload) as response:
        body = "\n".join(
            line.decode("utf-8") if isinstance(line, bytes) else line
            for line in response.iter_lines()
        )
        return response.status_code, _parse_sse(body)


def test_brand_bd_search_kols_uses_current_company_data(client, monkeypatch):
    monkeypatch.setattr(
        chat,
        "_search_company_kols_for_chat",
        lambda **_kwargs: {
            "params": {"platform": "xiaohongshu", "category_label": "美妆"},
            "results": [
                {
                    "name": "公开达人",
                    "platform": "xiaohongshu",
                    "followers": 12000,
                    "engagement_rate": 5.2,
                    "category": "美妆",
                    "data_source": "manual",
                }
            ],
            "data_source_summary": {"manual": 1},
            "code": "ok",
        },
    )

    status, events = _stream(client, "帮我找1个小红书美妆达人", agent_name="brand_bd")

    assert status == 200
    assert any(
        event.get("type") == "content" and "公开达人" in event.get("content", "")
        for event in events
    )
    assert events[-1]["type"] == "done"


def test_outreach_request_is_a_review_draft_not_an_external_send(client):
    status, events = _stream(client, "为 LisaBeauty 生成一份邀约话术", agent_name="brand_bd")

    assert status == 200
    assert any(event.get("guarded") is True for event in events)
    assert any(event.get("requires_human_review") is True for event in events)
    assert events[-1]["type"] == "done"


@pytest.mark.parametrize(
    "message",
    [
        "查询订单 ORD001 的物流状态",
        "为 BeautyQueen 生成直播间脚本",
        "生成本月销售表现报告",
        "客户问：这个口红是什么色号？",
        "分析本月销售额趋势",
    ],
)
def test_chat_requests_return_user_visible_sse_events(client, message):
    status, events = _stream(client, message, agent_name="brand_bd")

    assert status == 200
    assert any(event.get("type") == "content" for event in events)
    assert events[-1]["type"] == "done"


def test_agent_name_is_legacy_metadata_and_does_not_change_route(client):
    status, events = _stream(
        client,
        "请给出一个简短的运营分析",
        agent_name="nonexistent_agent",
    )

    assert status == 200
    assert any(event.get("type") == "content" for event in events)


def test_missing_message_is_validation_error(client):
    response = client.post("/api/chat", json={"agent_name": "brand_bd"})

    assert response.status_code == 422
    assert "detail" in response.json()


def test_agent_name_is_optional(client):
    status, events = _stream(client, "请回复一个简短的运营建议")

    assert status == 200
    assert any(event.get("type") == "content" for event in events)


def test_empty_message_returns_a_structured_stream(client):
    status, events = _stream(client, "")

    assert status == 200
    assert any(event.get("type") in {"content", "error"} for event in events)
    assert events[-1]["type"] == "done"


def test_conversation_stateless_behavior(client):
    status_1, events_1 = _stream(client, "帮我分析一个美妆运营问题", agent_name="brand_bd")
    status_2, events_2 = _stream(client, "再帮我分析一个穿搭运营问题", agent_name="brand_bd")

    assert status_1 == status_2 == 200
    assert events_1 and events_2
