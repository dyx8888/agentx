import pytest

from app.agents.master_router import MasterAgentRouter
from app.agents.master_routing import ExecutionPath
from app.perception.context_package import ContextPackage


def _context(query: str = "请用一句话回复：AgentRuntime SSE smoke ok。") -> ContextPackage:
    return ContextPackage(
        rewritten_query=query,
        raw_input=query,
        company_id="65",
        intent_type="chat",
        intent_entities={"model_provider": "custom_proxy"},
        rag_chunks=[],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["1", "true", "yes"])
async def test_smoke_disable_llm_review_skips_llm_after_structural_pass(monkeypatch, value):
    monkeypatch.setenv("AGENTX_SMOKE_DISABLE_LLM_REVIEW", value)
    router = MasterAgentRouter()

    async def fail_llm_review(*_args, **_kwargs):
        raise AssertionError("LLM review should be skipped for smoke runs")

    monkeypatch.setattr(router, "_llm_review", fail_llm_review)

    passed, reason = await router._review_result(
        _context(),
        ExecutionPath.REACT,
        result_produced=True,
        final_result_text="AgentRuntime SSE smoke ok。",
    )

    assert passed is True
    assert reason == "Smoke LLM review disabled by test env"


@pytest.mark.asyncio
async def test_smoke_disable_llm_review_keeps_structural_validation(monkeypatch):
    monkeypatch.setenv("AGENTX_SMOKE_DISABLE_LLM_REVIEW", "1")
    router = MasterAgentRouter()

    async def fail_llm_review(*_args, **_kwargs):
        raise AssertionError("LLM review should not run when structural validation fails")

    monkeypatch.setattr(router, "_llm_review", fail_llm_review)

    passed, reason = await router._review_result(
        _context(),
        ExecutionPath.REACT,
        result_produced=False,
        final_result_text="AgentRuntime SSE smoke ok。",
    )

    assert passed is False
    assert "未产出 result 事件" in reason


@pytest.mark.asyncio
async def test_llm_review_runs_by_default(monkeypatch):
    monkeypatch.delenv("AGENTX_SMOKE_DISABLE_LLM_REVIEW", raising=False)
    router = MasterAgentRouter()
    calls = 0

    async def fake_llm_review(query, final_result_text, context):
        nonlocal calls
        calls += 1
        assert "AgentRuntime SSE smoke ok" in query
        assert final_result_text == "AgentRuntime SSE smoke ok。"
        assert context.intent_entities["model_provider"] == "custom_proxy"
        return True, "fake review accepted"

    monkeypatch.setattr(router, "_llm_review", fake_llm_review)

    passed, reason = await router._review_result(
        _context(),
        ExecutionPath.REACT,
        result_produced=True,
        final_result_text="AgentRuntime SSE smoke ok。",
    )

    assert passed is True
    assert reason == "fake review accepted"
    assert calls == 1
