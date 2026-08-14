from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.feedback as feedback_api


def _build_feedback_client(monkeypatch, *, db_path=None):
    app = FastAPI()
    app.dependency_overrides[feedback_api.get_current_active_user] = lambda: SimpleNamespace(
        id=7,
        company_id=239,
    )

    if db_path is not None:
        db = feedback_api.FeedbackDB(str(db_path))
        monkeypatch.setattr(feedback_api, "get_feedback_db", lambda: db)
    else:
        db = None

    app.include_router(feedback_api.router, prefix="/api/feedback")
    return app, db


@pytest.fixture
def feedback_client(monkeypatch, tmp_path):
    app, db = _build_feedback_client(monkeypatch, db_path=tmp_path / "feedback.db")

    with TestClient(app) as client:
        yield client, db

    app.dependency_overrides.clear()


def test_feedback_stats_route_is_available_and_empty(feedback_client):
    client, _ = feedback_client

    response = client.get("/api/feedback/stats")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["stats"] == []
    assert payload["total"] == 0


def test_feedback_stats_returns_unavailable_when_schema_missing(monkeypatch, tmp_path):
    app, _ = _build_feedback_client(monkeypatch)
    monkeypatch.setattr(
        feedback_api,
        "get_feedback_db",
        lambda: SimpleNamespace(db_path=str(tmp_path / "feedback_without_schema.db")),
    )

    with TestClient(app) as client:
        response = client.get("/api/feedback/stats")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["stats"] == []
    assert payload["total"] == 0
    assert payload["reason"] == "feedback_storage_unavailable"


def test_feedback_post_rejects_missing_feedback_content(feedback_client):
    client, _ = feedback_client

    response = client.post("/api/feedback/", json={})

    assert response.status_code == 400
    assert "Feedback must include" in response.json()["detail"]


def test_feedback_post_write_error_is_not_reported_as_success(monkeypatch):
    app, _ = _build_feedback_client(monkeypatch)

    def fail_store_feedback(_data):
        raise RuntimeError("feedback store unavailable")

    monkeypatch.setattr(feedback_api, "store_feedback", fail_store_feedback)

    with TestClient(app) as client:
        response = client.post(
            "/api/feedback/",
            json={"rating": 1, "comment": "useful"},
        )

    assert response.status_code == 500
    assert response.json().get("status") != "ok"
