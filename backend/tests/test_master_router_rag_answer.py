import pytest

from app.agents.master_routing import ExecutionPath, select_path
from app.agents.master_router import MasterAgentRouter
from app.perception.context_package import ContextPackage


class _FakeResponse:
    def __init__(self, content="RAG_SMOKE_TEST", response_metadata=None):
        self.content = content
        self.response_metadata = response_metadata or {}


class _FakeLLM:
    def __init__(self):
        self.last_kwargs = {}
        self.response_metadata = {}

    async def ainvoke(self, messages, **kwargs):
        self.last_kwargs = kwargs
        joined = "\n".join(getattr(message, "content", "") for message in messages)
        assert "RAG_SMOKE_TEST" in joined
        assert "Do not say the task is outside the platform scope" in joined
        return _FakeResponse(response_metadata=self.response_metadata)


class _FakeGateway:
    def __init__(self):
        self.last_kwargs = {}
        self.llm = _FakeLLM()

    def get_llm(self, *args, **kwargs):
        self.last_kwargs = kwargs
        return self.llm


@pytest.mark.asyncio
async def test_react_uses_rag_chunks_before_generic_routing(monkeypatch):
    gateway = _FakeGateway()
    router = MasterAgentRouter(model_gateway=gateway)

    async def fail_react_execute(*args, **kwargs):
        raise AssertionError("generic ReAct path should not run when RAG chunks exist")

    monkeypatch.setattr(router, "_react_execute", fail_react_execute)

    context = ContextPackage(
        rewritten_query="What is the marker?",
        raw_input="What is the marker?",
        company_id="65",
        intent_type="knowledge",
        intent_entities={"model_provider": "custom_proxy"},
        rag_chunks=[
            {
                "content": "The secret marker is RAG_SMOKE_TEST.",
                "source_file": "smoke.txt",
                "score": 0.99,
            }
        ],
    )

    events = [event async for event in router._run_react(context)]
    result_events = [event for event in events if event.get("type") == "result"]

    assert result_events
    assert result_events[-1]["data"] == "RAG_SMOKE_TEST"
    assert any(event.get("type") == "observation" for event in events)
    assert gateway.last_kwargs["model_key"] == "custom_proxy"
    assert gateway.last_kwargs["company_id"] == 65
    assert gateway.llm.last_kwargs["company_id"] == 65


@pytest.mark.asyncio
async def test_react_emits_warning_when_rag_answer_uses_model_fallback(monkeypatch):
    gateway = _FakeGateway()
    gateway.llm.response_metadata = {
        "model_fallback": {
            "from_model": "primary-model",
            "to_model": "backup-model",
            "error": "primary timeout",
        }
    }
    router = MasterAgentRouter(model_gateway=gateway)

    async def fail_react_execute(*args, **kwargs):
        raise AssertionError("generic ReAct path should not run when RAG chunks exist")

    monkeypatch.setattr(router, "_react_execute", fail_react_execute)

    context = ContextPackage(
        rewritten_query="What is the marker?",
        raw_input="What is the marker?",
        company_id="65",
        intent_type="knowledge",
        rag_chunks=[
            {
                "content": "The secret marker is RAG_SMOKE_TEST.",
                "source_file": "smoke.txt",
                "score": 0.99,
            }
        ],
    )

    events = [event async for event in router._run_react(context)]
    warning_events = [event for event in events if event.get("type") == "warning"]
    result_events = [event for event in events if event.get("type") == "result"]

    assert warning_events
    assert warning_events[0]["code"] == "model_fallback"
    assert warning_events[0]["from_model"] == "primary-model"
    assert warning_events[0]["to_model"] == "backup-model"
    assert "backup-model" in warning_events[0]["message"]
    assert result_events[-1]["data"] == "RAG_SMOKE_TEST"


@pytest.mark.asyncio
async def test_react_exact_reply_short_path_skips_generic_routing(monkeypatch):
    router = MasterAgentRouter()

    async def fail_react_execute(*args, **kwargs):
        raise AssertionError("generic ReAct path should not run for exact reply requests")

    monkeypatch.setattr(router, "_react_execute", fail_react_execute)

    context = ContextPackage(
        rewritten_query="DOCKER_UI_SMOKE_OK_abc123",
        raw_input="请只回复 DOCKER_UI_SMOKE_OK_abc123，不要添加其他内容。",
        company_id="65",
        intent_type="chat",
        rag_chunks=[],
    )

    events = [event async for event in router._run_react(context)]
    result_events = [event for event in events if event.get("type") == "result"]

    assert result_events[-1]["data"] == "DOCKER_UI_SMOKE_OK_abc123"
    assert any("short path" in event.get("data", "") for event in events)


def test_exact_reply_extractor_is_narrow():
    assert (
        MasterAgentRouter._extract_exact_reply_request(
            "请只回复 DOCKER_UI_SMOKE_OK_abc123，不要添加其他内容。"
        )
        == "DOCKER_UI_SMOKE_OK_abc123"
    )
    assert MasterAgentRouter._extract_exact_reply_request("只输出：OK") == "OK"
    assert MasterAgentRouter._extract_exact_reply_request("请分析 GMV 增长原因") == ""


def test_exact_reply_prompt_routes_to_react_even_when_intent_is_generate():
    context = ContextPackage(
        rewritten_query="生成 DOCKER_UI_SMOKE_OK_abc123",
        raw_input="请只回复 DOCKER_UI_SMOKE_OK_abc123，不要添加其他内容。",
        company_id="65",
        intent_type="generate",
        intent_entities={},
    )

    assert select_path(context) == ExecutionPath.REACT
