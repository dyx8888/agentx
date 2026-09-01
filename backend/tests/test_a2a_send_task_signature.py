import pytest

from app.communication.hierarchical import HierarchicalOrchestrator
from app.communication.hierarchical import SubTask as HierarchicalSubTask
from app.communication.master_dispatcher import MasterDispatcher, SubTask as MasterSubTask
from app.communication.parallel import ParallelAgentDispatcher, ParallelTask
from app.communication.pipeline_tracker import MixedModeDispatcher
from app.perception.context_package import ContextPackage


class StrictA2AAdapter:
    def __init__(self):
        self.calls = []

    def send_task(
        self,
        target_agent_name,
        task_message,
        task_type="general",
        payload=None,
    ):
        self.calls.append(
            {
                "target_agent_name": target_agent_name,
                "task_message": task_message,
                "task_type": task_type,
                "payload": payload,
            }
        )
        return {
            "success": True,
            "task_id": f"task-{len(self.calls)}",
            "response": f"accepted: {task_message}",
        }


@pytest.mark.asyncio
async def test_parallel_dispatcher_uses_task_message_keyword():
    adapter = StrictA2AAdapter()
    dispatcher = ParallelAgentDispatcher(a2a_adapter=adapter, global_timeout=5)

    result = await dispatcher.dispatch(
        [ParallelTask(target_agent="brand_bd", task_description="find KOLs")]
    )

    assert result.completed == 1
    assert adapter.calls == [
        {
            "target_agent_name": "brand_bd",
            "task_message": "find KOLs",
            "task_type": "general",
            "payload": None,
        }
    ]


@pytest.mark.asyncio
async def test_hierarchical_orchestrator_uses_task_message_keyword():
    adapter = StrictA2AAdapter()
    orchestrator = HierarchicalOrchestrator(a2a_adapter=adapter)
    task = HierarchicalSubTask(
        id="h1",
        description="prepare subtask",
        assigned_agent="product_selector",
        depth=0,
    )

    result = await orchestrator._execute_subtask(task, depth=0)

    assert result.status == "completed"
    assert adapter.calls == [
        {
            "target_agent_name": "product_selector",
            "task_message": "prepare subtask",
            "task_type": "subtask",
            "payload": None,
        }
    ]


@pytest.mark.asyncio
async def test_mixed_mode_dispatcher_uses_task_message_keyword(monkeypatch):
    adapter = StrictA2AAdapter()

    import app.communication.a2a_adapter as a2a_adapter_module

    monkeypatch.setattr(a2a_adapter_module, "get_a2a_adapter", lambda: adapter)
    dispatcher = MixedModeDispatcher()

    result = await dispatcher._execute_single(
        {"agent": "warehouse", "task": "check inventory", "type": "lookup"}
    )

    assert result["success"] is True
    assert adapter.calls == [
        {
            "target_agent_name": "warehouse",
            "task_message": "check inventory",
            "task_type": "lookup",
            "payload": None,
        }
    ]


@pytest.mark.asyncio
async def test_master_dispatcher_delegate_uses_task_message_keyword():
    adapter = StrictA2AAdapter()
    dispatcher = MasterDispatcher(a2a_adapter=adapter)
    task = MasterSubTask(
        task_id="m1",
        description="summarize campaign",
        agent_name="smart_ad_delivery",
    )

    result = await dispatcher._delegate(task, results={})

    assert result["success"] is True
    assert adapter.calls == [
            {
                "target_agent_name": "smart_ad_delivery",
                "task_message": "summarize campaign",
                "task_type": "subtask",
                "payload": None,
            }
        ]


@pytest.mark.asyncio
async def test_master_dispatcher_runtime_receives_selected_model_provider():
    class FakeRuntime:
        def __init__(self):
            self.calls = []

        async def run(self, **kwargs):
            self.calls.append(kwargs)
            return {"success": True, "response": "ok"}

    runtime = FakeRuntime()
    dispatcher = MasterDispatcher(agent_runtime=runtime)
    dispatcher._context = ContextPackage(
        raw_input="summarize campaign",
        rewritten_query="summarize campaign",
        company_id="65",
        intent_entities={"company_id": "65", "model_provider": "custom_proxy"},
    )
    task = MasterSubTask(task_id="m1", description="summarize campaign")

    result = await dispatcher._master_execute(task, results={})

    assert result["success"] is True
    assert runtime.calls == [
        {
            "message": "summarize campaign",
            "agent_name": "master",
            "company_id": "65",
            "model_key": "custom_proxy",
        }
    ]


@pytest.mark.asyncio
async def test_master_dispatcher_llm_complete_uses_selected_model_provider():
    class FakeResponse:
        content = '{"passed": true, "issues": []}'

    class FakeLLM:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, messages, **kwargs):
            self.calls.append(kwargs)
            return FakeResponse()

    class FakeGateway:
        def __init__(self):
            self.calls = []
            self.llm = FakeLLM()

        def get_llm(self, **kwargs):
            self.calls.append(kwargs)
            return self.llm

    gateway = FakeGateway()
    dispatcher = MasterDispatcher(model_gateway=gateway)
    dispatcher._context = ContextPackage(
        raw_input="review result",
        rewritten_query="review result",
        company_id="65",
        intent_entities={"company_id": "65", "model_provider": "custom_proxy"},
    )

    content = await dispatcher._llm_complete("system", "user")

    assert content == '{"passed": true, "issues": []}'
    assert gateway.calls == [{"model_key": "custom_proxy", "company_id": 65}]
    assert gateway.llm.calls == [{"company_id": 65}]
