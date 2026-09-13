from types import SimpleNamespace


def _tool_named(tools, name):
    return next(tool for tool in tools if tool.name == name)


def test_core_tool_schemas_do_not_expose_company_id():
    from app.agent import get_core_tools

    for tool in get_core_tools():
        if tool.name in {"schedule_task", "a2a_delegate_task"}:
            assert "company_id" not in tool.args


def test_tenant_bound_a2a_tool_injects_company_id(monkeypatch):
    import app.communication.a2a_adapter as adapter_module
    from app.agent import get_tenant_core_tools

    calls = []

    class FakeAdapter:
        def send_task(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {"success": True, "task_id": "task-1"}

    monkeypatch.setattr(adapter_module, "get_a2a_adapter", lambda: FakeAdapter())
    tool = _tool_named(get_tenant_core_tools(239), "a2a_delegate_task")

    result = tool.invoke(
        {
            "target_agent_name": "brand_bd",
            "task": "draft outreach",
            "task_type": "general",
        }
    )

    assert "Task ID: task-1" in result
    assert calls == [
        (
            ("brand_bd", "draft outreach", "general"),
            {"company_id": 239},
        )
    ]


def test_tenant_bound_schedule_tool_uses_trusted_company(monkeypatch):
    import app.database as database_module
    from app.agent import get_tenant_core_tools

    calls = []

    class FakeDB:
        def get_agent_by_name(self, name, company_id=None):
            calls.append(("lookup", name, company_id))
            return SimpleNamespace(name="brand_bd", company_id=239)

        def create_task(self, **kwargs):
            calls.append(("create", kwargs))
            return 7

    monkeypatch.setattr(database_module, "db", FakeDB())
    tool = _tool_named(get_tenant_core_tools(239), "schedule_task")

    result = tool.invoke({"target_agent_name": "brand_bd", "task": "find creators"})

    assert "Task ID: 7" in result
    assert calls == [
        ("lookup", "brand_bd", 239),
        (
            "create",
            {
                "company_id": 239,
                "source_agent_id": None,
                "target_agent_name": "brand_bd",
                "task_description": "find creators",
            },
        ),
    ]
