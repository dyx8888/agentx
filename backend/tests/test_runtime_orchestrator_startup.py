import asyncio
from types import SimpleNamespace

from app.services.model_gateway import ModelApiKeyMissingError


def _patch_missing_key_runtime(monkeypatch, orchestrator):
    class MissingKeyGateway:
        def get_default_model(self):
            return "deepseek"

        def get_llm(self, *args, **kwargs):
            raise ModelApiKeyMissingError(
                model_key="deepseek",
                provider="deepseek",
                env_keys=("DEEPSEEK_API_KEY",),
            )

    async def no_tools(self, ctx):
        return []

    graph_builds = []

    class ExplodingGraph:
        async def ainvoke(self, *args, **kwargs):
            raise AssertionError("graph should not run when model config is missing")

        async def astream(self, *args, **kwargs):
            raise AssertionError("graph should not stream when model config is missing")
            yield {}

    monkeypatch.setattr(
        orchestrator,
        "get_global_model_gateway",
        lambda: MissingKeyGateway(),
    )
    monkeypatch.setattr(orchestrator, "MemoryManager", lambda: object())
    monkeypatch.setattr(orchestrator.ToolLoader, "load", no_tools)

    def build_graph(self):
        graph_builds.append("built")
        self.graph = ExplodingGraph()

    monkeypatch.setattr(orchestrator.AgentRuntime, "_build_graph", build_graph)
    return graph_builds


def test_agent_runtime_initializes_degraded_without_global_llm_key(monkeypatch):
    import app.runtime.orchestrator as orchestrator

    graph_builds = _patch_missing_key_runtime(monkeypatch, orchestrator)

    runtime = orchestrator.AgentRuntime()

    asyncio.run(runtime.initialize(SimpleNamespace(agent_name="brand_bd", capabilities=[])))

    assert runtime.llm is None
    assert runtime.model_status == {
        "status": "model_config_required",
        "code": "model_api_key_missing",
        "model": "deepseek",
        "provider": "deepseek",
        "env_keys": ["DEEPSEEK_API_KEY"],
    }
    assert runtime._initialized is True
    assert graph_builds == ["built"]


def test_agent_runtime_run_returns_model_config_required_without_graph(monkeypatch):
    import app.runtime.orchestrator as orchestrator

    graph_builds = _patch_missing_key_runtime(monkeypatch, orchestrator)
    runtime = orchestrator.AgentRuntime()

    result = asyncio.run(runtime.run("hello", agent_name="brand_bd", company_id="1"))

    assert graph_builds == ["built"]
    assert result["success"] is False
    assert result["error"]["code"] == "model_api_key_missing"
    assert result["error"]["requires_config"] is True
    assert result["error"]["config_target"] == "llm_api_key"
    assert result["error"]["model"] == "deepseek"
    assert result["reflection"]["passed"] is False
    assert result["step_results"][0]["status"] == "blocked"


def test_agent_runtime_run_stream_yields_model_config_required_without_graph(monkeypatch):
    import app.runtime.orchestrator as orchestrator

    graph_builds = _patch_missing_key_runtime(monkeypatch, orchestrator)
    runtime = orchestrator.AgentRuntime()

    async def collect_events():
        events = []
        async for event in runtime.run_stream("hello", agent_name="brand_bd", company_id="1"):
            events.append(event)
        return events

    events = asyncio.run(collect_events())

    assert graph_builds == ["built"]
    assert events[0]["type"] == "error"
    assert events[0]["code"] == "model_api_key_missing"
    assert events[0]["requires_config"] is True
    assert events[0]["config_target"] == "llm_api_key"
    assert events[0]["model"] == "deepseek"
    assert events[1] == {"type": "done"}


def test_agent_runtime_uses_company_model_config_after_global_key_degraded(monkeypatch):
    import app.runtime.orchestrator as orchestrator

    class CompanyGateway:
        def __init__(self):
            self.calls = []

        def get_default_model(self):
            return "deepseek"

        def get_llm(self, *args, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("company_id") == 42:
                return "company-llm"
            raise ModelApiKeyMissingError(
                model_key="deepseek",
                provider="deepseek",
                env_keys=("DEEPSEEK_API_KEY",),
            )

    async def no_tools(self, ctx):
        return []

    class FakeGraph:
        def __init__(self, runtime):
            self.runtime = runtime

        async def ainvoke(self, state, config):
            assert self.runtime.llm == "company-llm"
            return {
                "messages": state["messages"],
                "step_results": [{"status": "ok"}],
                "reflection": {"passed": True},
                "plan": {"steps": []},
                "working_memory": state["working_memory"],
            }

    gateway = CompanyGateway()
    monkeypatch.setattr(orchestrator, "get_global_model_gateway", lambda: gateway)
    monkeypatch.setattr(orchestrator, "MemoryManager", lambda: object())
    monkeypatch.setattr(orchestrator.ToolLoader, "load", no_tools)
    monkeypatch.setattr(
        orchestrator.AgentRuntime,
        "_build_graph",
        lambda self: setattr(self, "graph", FakeGraph(self)),
    )

    runtime = orchestrator.AgentRuntime()

    result = asyncio.run(runtime.run("hello", agent_name="brand_bd", company_id="42"))

    assert gateway.calls == [{}, {"model_key": "deepseek", "company_id": 42}]
    assert runtime.llm is None
    assert runtime.model_status["status"] == "model_config_required"
    assert result["success"] is True


def test_agent_runtime_uses_selected_company_model_key(monkeypatch):
    import app.runtime.orchestrator as orchestrator

    class CompanyGateway:
        def __init__(self):
            self.calls = []

        def get_default_model(self):
            return "deepseek"

        def get_llm(self, *args, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("company_id") == 42:
                return "company-llm"
            raise ModelApiKeyMissingError(
                model_key="deepseek",
                provider="deepseek",
                env_keys=("DEEPSEEK_API_KEY",),
            )

    async def no_tools(self, ctx):
        return []

    class FakeGraph:
        def __init__(self, runtime):
            self.runtime = runtime

        async def ainvoke(self, state, config):
            assert self.runtime.llm == "company-llm"
            return {
                "messages": state["messages"],
                "step_results": [{"status": "ok"}],
                "reflection": {"passed": True},
                "plan": {"steps": []},
                "working_memory": state["working_memory"],
            }

    gateway = CompanyGateway()
    monkeypatch.setattr(orchestrator, "get_global_model_gateway", lambda: gateway)
    monkeypatch.setattr(orchestrator, "MemoryManager", lambda: object())
    monkeypatch.setattr(orchestrator.ToolLoader, "load", no_tools)
    monkeypatch.setattr(
        orchestrator.AgentRuntime,
        "_build_graph",
        lambda self: setattr(self, "graph", FakeGraph(self)),
    )

    runtime = orchestrator.AgentRuntime()

    result = asyncio.run(
        runtime.run(
            "hello",
            agent_name="brand_bd",
            company_id="42",
            model_key="custom_proxy",
        )
    )

    assert gateway.calls == [{}, {"model_key": "custom_proxy", "company_id": 42}]
    assert result["success"] is True


def test_agent_runtime_reinitializes_tools_when_tenant_changes(monkeypatch):
    import app.runtime.orchestrator as orchestrator

    runtime = orchestrator.AgentRuntime()
    initialized = []

    async def fake_initialize(ctx):
        initialized.append((ctx.company_id, ctx.agent_name, tuple(ctx.capabilities or [])))
        runtime._initialized = True
        runtime._initialized_context_key = runtime._context_key(ctx)

    monkeypatch.setattr(runtime, "initialize", fake_initialize)

    async def exercise():
        await runtime._ensure_runtime_context(
            orchestrator.ToolLoadContext(
                company_id="company-a",
                agent_name="master",
                trace_id="t1",
                capabilities=["core"],
            )
        )
        await runtime._ensure_runtime_context(
            orchestrator.ToolLoadContext(
                company_id="company-a",
                agent_name="master",
                trace_id="t2",
                capabilities=["core"],
            )
        )
        await runtime._ensure_runtime_context(
            orchestrator.ToolLoadContext(
                company_id="company-b",
                agent_name="master",
                trace_id="t3",
                capabilities=["core"],
            )
        )

    asyncio.run(exercise())

    assert initialized == [
        ("company-a", "master", ("core",)),
        ("company-b", "master", ("core",)),
    ]
