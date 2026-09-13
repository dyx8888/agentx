from types import SimpleNamespace


def test_get_agent_by_name_uses_registry_module_aliases():
    from app.agent import get_agent_by_name

    prompt, tools = get_agent_by_name("content_operation")

    assert "内容运营" in prompt
    assert "generate_script" in tools


def test_get_agent_by_name_accepts_display_name():
    from app.agent import get_agent_by_name

    prompt, tools = get_agent_by_name("数据分析")

    assert "数据分析" in prompt
    assert "calculate_metrics" in tools


def test_schedule_task_requires_explicit_company_for_registry_agent(monkeypatch):
    import app.agent as agent_module
    from app.database import db

    calls = []
    fake_db = SimpleNamespace(
        get_agent_by_name=lambda _name: None,
        get_company=lambda company_id: SimpleNamespace(id=company_id),
        create_task=lambda **kwargs: calls.append(kwargs) or 17,
    )
    monkeypatch.setattr(db, "_instance", fake_db, raising=False)

    tool = next(tool for tool in agent_module.get_tenant_core_tools(42) if tool.name == "schedule_task")
    result = tool.invoke({"target_agent_name": "内容运营", "task": "整理公开素材"})

    assert result == "Task scheduled for content_operation. Task ID: 17"
    assert calls == [
        {
            "company_id": 42,
            "source_agent_id": None,
            "target_agent_name": "content_operation",
            "task_description": "整理公开素材",
        }
    ]


def test_schedule_task_rejects_agent_from_another_company(monkeypatch):
    import app.agent as agent_module
    from app.database import db

    fake_db = SimpleNamespace(
        get_agent_by_name=lambda _name: SimpleNamespace(name="brand_bd", company_id=7),
        get_company=lambda _company_id: SimpleNamespace(id=239),
        create_task=lambda **_kwargs: 17,
    )
    monkeypatch.setattr(db, "_instance", fake_db, raising=False)

    tool = next(tool for tool in agent_module.get_tenant_core_tools(239) if tool.name == "schedule_task")
    result = tool.invoke({"target_agent_name": "brand_bd", "task": "整理公开素材"})

    assert result == "Agent 'brand_bd' not found."


def test_schedule_task_rejects_adapter_that_ignores_company_filter(monkeypatch):
    import app.agent as agent_module
    from app.database import db

    fake_db = SimpleNamespace(
        get_agent_by_name=lambda _name, company_id=None: SimpleNamespace(
            name="brand_bd", company_id=7
        ),
        get_company=lambda _company_id: SimpleNamespace(id=239),
        create_task=lambda **_kwargs: 17,
    )
    monkeypatch.setattr(db, "_instance", fake_db, raising=False)

    tool = next(tool for tool in agent_module.get_tenant_core_tools(239) if tool.name == "schedule_task")
    result = tool.invoke({"target_agent_name": "brand_bd", "task": "整理公开素材"})

    assert result == "Agent 'brand_bd' not found."


def test_a2a_delegate_rejects_agent_from_another_company():
    from app.communication.a2a_adapter import A2AAdapter

    class Database:
        def get_agent_by_name(self, _name):
            return SimpleNamespace(name="brand_bd", company_id=7)

    adapter = A2AAdapter(Database())

    result = adapter.send_task("brand_bd", "整理公开素材", company_id=239)

    assert result == {"success": False, "error": "Agent not found"}


def test_a2a_task_persistence_uses_resolved_company_id():
    from app.communication.a2a_adapter import A2AAdapter

    class Database:
        def __init__(self):
            self.created = None

        def create_a2a_message(self, **kwargs):
            self.created = kwargs
            return "task_abc"

    database = Database()
    adapter = A2AAdapter(database)
    adapter._get_redis = lambda: None

    task_id = adapter._store_task(
        {
            "sender": "a2a_service",
            "recipient": "brand_bd",
            "description": "整理公开素材",
            "type": "general",
            "payload": {},
            "company_id": 239,
        }
    )

    assert task_id == "task_abc"
    assert database.created["company_id"] == 239
