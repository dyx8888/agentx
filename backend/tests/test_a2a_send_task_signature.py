import pytest

from app.communication.hierarchical import HierarchicalOrchestrator
from app.communication.hierarchical import SubTask as HierarchicalSubTask
from app.communication.master_dispatcher import MasterDispatcher, SubTask as MasterSubTask
from app.communication.parallel import ParallelAgentDispatcher, ParallelTask
from app.communication.pipeline_tracker import MixedModeDispatcher


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
