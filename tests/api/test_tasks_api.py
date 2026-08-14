from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.tasks as tasks_api
import app.database.core as database_core


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class FakeConnection:
    def __init__(self, rows, seen_params):
        self._rows = rows
        self._seen_params = seen_params

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, _statement, params):
        self._seen_params.append(dict(params))
        company_id = params["company_id"]
        return FakeResult([row for row in self._rows if row[1] == company_id])


class FakeEngine:
    def __init__(self, rows):
        self.rows = rows
        self.seen_params = []

    def connect(self):
        return FakeConnection(self.rows, self.seen_params)


class BrokenEngine:
    def connect(self):
        raise RuntimeError("tasks schema unavailable")


def _user(company_id=239):
    return SimpleNamespace(id=7, company_id=company_id, is_admin=False)


def _client(monkeypatch, current_user=None, engine=None):
    app = FastAPI()
    if current_user is not None:
        app.dependency_overrides[tasks_api.get_current_active_user] = lambda: current_user
    if engine is not None:
        monkeypatch.setattr(database_core, "get_engine", lambda: engine)
    app.include_router(tasks_api.router, prefix="/api/tasks")
    return TestClient(app)


def test_pending_tasks_route_is_available_and_empty(monkeypatch):
    engine = FakeEngine(rows=[])
    client = _client(monkeypatch, _user(), engine)

    response = client.get("/api/tasks/pending")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["tasks"] == []
    assert payload["total"] == 0
    assert engine.seen_params == [{"company_id": 239}]


def test_pending_tasks_are_filtered_by_current_company(monkeypatch):
    engine = FakeEngine(
        rows=[
            (
                1,
                239,
                None,
                "brand_bd",
                "draft outreach",
                datetime(2026, 8, 13, 10, 0, 0),
            ),
            (
                2,
                777,
                None,
                "customer_service",
                "refund order",
                datetime(2026, 8, 13, 11, 0, 0),
            ),
        ]
    )
    client = _client(monkeypatch, _user(company_id=239), engine)

    response = client.get("/api/tasks/pending")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["total"] == 1
    assert [task["id"] for task in payload["tasks"]] == [1]
    assert payload["tasks"][0]["company_id"] == 239
    assert "refund order" not in str(payload)
    assert engine.seen_params == [{"company_id": 239}]


def test_pending_tasks_db_unavailable_returns_controlled_empty_state(monkeypatch):
    client = _client(monkeypatch, _user(), BrokenEngine())

    response = client.get("/api/tasks/pending")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["reason"] == "pending_tasks_unavailable"
    assert payload["tasks"] == []
    assert payload["total"] == 0


def test_pending_tasks_requires_authenticated_user(monkeypatch):
    client = _client(monkeypatch, current_user=None, engine=FakeEngine(rows=[]))

    response = client.get("/api/tasks/pending")

    assert response.status_code in {401, 403}
