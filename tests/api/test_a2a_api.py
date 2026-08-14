from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.a2a as a2a_api


class FakeA2AAdapter:
    def __init__(self):
        self.sent_tasks = []

    def discover_agents(self, company_id):
        return [
            {
                "name": "brand_bd",
                "description": "Brand BD agent",
                "capabilities": ["kol_search", "outreach_generation"],
                "company_id": company_id,
                "status": "active",
                "registered_at": "2026-08-13T00:00:00Z",
                "version": "1.0.0",
                "protocol": "a2a",
                "url": "/api/a2a/agents/brand_bd",
            }
        ]

    def send_task(self, *, target_agent_name, task_message, task_type, payload):
        self.sent_tasks.append(
            {
                "target_agent_name": target_agent_name,
                "task_message": task_message,
                "task_type": task_type,
                "payload": payload,
            }
        )
        return {
            "success": True,
            "task_id": "task-123",
            "message": "Task queued for review",
            "timestamp": "2026-08-13T00:00:00Z",
        }


@pytest.fixture
def a2a_client(monkeypatch):
    fake_adapter = FakeA2AAdapter()
    app = FastAPI()
    app.dependency_overrides[a2a_api.get_current_active_user] = lambda: SimpleNamespace(
        id=7,
        company_id=239,
    )
    monkeypatch.setattr(a2a_api, "get_a2a_adapter", lambda: fake_adapter)
    app.include_router(a2a_api.router, prefix="/api")

    with TestClient(app) as client:
        yield client, fake_adapter

    app.dependency_overrides.clear()


def _endpoint_values(payload):
    return list(payload["endpoints"].values())


def test_a2a_agents_discovery_is_available_under_api_prefix(a2a_client):
    client, _ = a2a_client

    response = client.get("/api/a2a/agents")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["count"] == 1
    assert payload["agents"][0]["company_id"] == 239
    assert payload["endpoints"]["discovery"] == "/api/a2a/agents"
    assert all(value.startswith("/api/a2a/") for value in _endpoint_values(payload))


def test_a2a_well_known_paths_match_actual_mount(a2a_client):
    client, _ = a2a_client

    response = client.get("/api/a2a/.well-known/agent.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["endpoints"]["well_known"] == "/api/a2a/.well-known/agent.json"
    assert payload["endpoints"]["delegate"] == "/api/a2a/delegate"
    assert all(value.startswith("/api/a2a/") for value in _endpoint_values(payload))
    assert not any(value.startswith("/a2a/") for value in _endpoint_values(payload))
    assert not any(value.startswith("/agent/") for value in _endpoint_values(payload))


def test_a2a_health_is_available_under_api_prefix(a2a_client):
    client, _ = a2a_client

    response = client.get("/api/a2a/health")

    assert response.status_code == 200
    assert response.json()["service"] == "a2a"
    assert response.json()["status"] == "healthy"


def test_a2a_delegate_missing_required_fields_returns_client_error(a2a_client):
    client, _ = a2a_client

    response = client.post("/api/a2a/delegate", json={})

    assert response.status_code in {400, 422}
    assert "target_agent" in str(response.json())
    assert "task" in str(response.json())


def test_a2a_delegate_uses_adapter_for_valid_local_contract(a2a_client):
    client, fake_adapter = a2a_client

    response = client.post(
        "/api/a2a/delegate",
        json={"target_agent": "brand_bd", "message": "draft outreach"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["target_agent"] == "brand_bd"
    assert fake_adapter.sent_tasks == [
        {
            "target_agent_name": "brand_bd",
            "task_message": "draft outreach",
            "task_type": "general",
            "payload": None,
        }
    ]
