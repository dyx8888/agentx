from types import SimpleNamespace

import pytest

from app.runtime import orchestrator


@pytest.mark.asyncio
async def test_runtime_initialization_uses_company_model_credentials(monkeypatch):
    calls = []

    class FakeGateway:
        def get_llm(self, **kwargs):
            calls.append(kwargs)
            return object()

        def get_default_model(self):
            return "deepseek"

    monkeypatch.setattr(orchestrator, "get_global_model_gateway", lambda: FakeGateway())
    monkeypatch.setattr(orchestrator, "MemoryManager", lambda: object())
    monkeypatch.setattr(orchestrator, "DynamicValidator", lambda *_: object())

    runtime = orchestrator.AgentRuntime()
    runtime.tool_loader.load = lambda _ctx: _empty_tools()
    runtime._build_graph = lambda: None

    await runtime.initialize(SimpleNamespace(company_id="42", capabilities=[]))

    assert calls == [{"company_id": 42}]
    assert runtime._initialized is True


async def _empty_tools():
    return []
