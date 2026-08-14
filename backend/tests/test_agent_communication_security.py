from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.agent_communication as agent_api


class FakeAgent:
    def __init__(self, agent_id: int, company_id: int, name: str = "agent"):
        self.id = agent_id
        self.company_id = company_id
        self.name = name
        self.description = f"{name} description"
        self.tools_json = "[]"


class FakeDB:
    def __init__(self):
        self.agents = {
            1: FakeAgent(1, 239, "source"),
            2: FakeAgent(2, 239, "target"),
        }

    def get_agent(self, agent_id):
        return self.agents.get(agent_id)

    def get_agents_by_company(self, company_id):
        return [agent for agent in self.agents.values() if agent.company_id == company_id]


@pytest.fixture
def agent_client():
    app = FastAPI()
    current_user = SimpleNamespace(id=7, company_id=239)
    app.dependency_overrides[agent_api.get_current_active_user] = lambda: current_user
    app.include_router(agent_api.router, prefix="/api/agent")

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def test_agent_communication_routes_require_integer_agent_id(agent_client):
    delegate_response = agent_client.post(
        "/api/agent/not-an-int/delegate",
        json={"task": "delegate task", "target_agent_id": 2},
    )
    colleagues_response = agent_client.get("/api/agent/not-an-int/colleagues")

    assert delegate_response.status_code == 404
    assert colleagues_response.status_code == 404


def test_delegate_failure_logs_and_hides_internal_error(agent_client, monkeypatch):
    fake_logger = SimpleNamespace(exception=MagicMock())

    def raise_internal_error():
        raise RuntimeError("secret-token-value")

    monkeypatch.setattr(agent_api, "db", FakeDB())
    monkeypatch.setattr(agent_api, "logger", fake_logger)
    monkeypatch.setattr(agent_api, "get_global_model_gateway", raise_internal_error)

    response = agent_client.post(
        "/api/agent/1/delegate",
        json={"task": "delegate task", "target_agent_id": 2},
    )

    assert response.status_code == 200
    assert response.json() == {"success": False, "result": None, "error": "Delegation failed"}
    assert "secret-token-value" not in response.text
    fake_logger.exception.assert_called_once_with("delegate_task_failed")


def test_delegate_uses_async_llm_invocation(agent_client, monkeypatch):
    fake_bound_llm = MagicMock()

    async def ainvoke(messages):
        fake_bound_llm.ainvoke_messages = messages
        return SimpleNamespace(content="delegated result", tool_calls=[])

    def invoke(_messages):
        raise AssertionError("sync invoke should not be used")

    fake_bound_llm.ainvoke = MagicMock(side_effect=ainvoke)
    fake_bound_llm.invoke = MagicMock(side_effect=invoke)

    class FakeLLM:
        def bind_tools(self, tools):
            assert tools == []
            return fake_bound_llm

    class FakeModelGateway:
        def get_llm(self):
            return FakeLLM()

    class FakeGraph:
        def __init__(self, agent_node):
            self.agent_node = agent_node

        async def astream_events(self, state, version):
            assert version == "v1"
            result = await self.agent_node(state)
            yield {"event": "on_chat_model_end", "data": {"output": result["messages"][0]}}

    def build_fake_graph(agent_node, tools, model_gateway):
        assert tools == []
        assert isinstance(model_gateway, FakeModelGateway)
        return FakeGraph(agent_node), model_gateway

    monkeypatch.setattr(agent_api, "db", FakeDB())
    monkeypatch.setattr(agent_api.registry, "get_tools_by_names", lambda names: [])
    monkeypatch.setattr(agent_api, "get_global_model_gateway", lambda: FakeModelGateway())
    monkeypatch.setattr(agent_api, "build_reaction_graph", build_fake_graph)
    monkeypatch.setattr(agent_api, "build_system_message", lambda _context: "system")

    response = agent_client.post(
        "/api/agent/1/delegate",
        json={"task": "delegate task", "target_agent_id": 2},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["result"] == "delegated result"
    fake_bound_llm.ainvoke.assert_called_once()
    fake_bound_llm.invoke.assert_not_called()
