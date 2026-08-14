from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.evolution as evolution_api


def _client(monkeypatch, current_user=None, analyzer_cls=None):
    app = FastAPI()
    if current_user is not None:
        app.dependency_overrides[evolution_api.get_current_active_user] = (
            lambda: current_user
        )
    if analyzer_cls is not None:
        monkeypatch.setattr(evolution_api, "EvolutionAnalyzer", analyzer_cls)
    app.include_router(evolution_api.router, prefix="/api/admin/evolution")
    return TestClient(app)


def _admin_user():
    return SimpleNamespace(id=1, company_id=239, is_admin=True)


class EmptyAnalyzer:
    def get_company_evolution_report(self, company_id, days):
        assert company_id == 239
        assert days == 7
        return []


class BrokenAnalyzer:
    def get_company_evolution_report(self, *_args, **_kwargs):
        raise RuntimeError("feedback store unavailable")


class BrokenAnalyzerInit:
    def __init__(self):
        raise RuntimeError("evolution analyzer unavailable")


def test_evolution_report_route_is_available_and_empty(monkeypatch):
    client = _client(monkeypatch, _admin_user(), EmptyAnalyzer)

    response = client.get("/api/admin/evolution/report")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["reports"] == []
    assert payload["high_modification_agents"] == []
    assert payload["analysis_period_days"] == 7


def test_evolution_report_storage_unavailable_returns_empty_state(monkeypatch):
    client = _client(monkeypatch, _admin_user(), BrokenAnalyzer)

    response = client.get("/api/admin/evolution/report")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["reason"] == "evolution_report_unavailable"
    assert payload["reports"] == []
    assert payload["high_modification_agents"] == []


def test_evolution_report_analyzer_init_failure_returns_empty_state(monkeypatch):
    client = _client(monkeypatch, _admin_user(), BrokenAnalyzerInit)

    response = client.get("/api/admin/evolution/report")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["reason"] == "evolution_report_unavailable"
    assert payload["reports"] == []
    assert payload["high_modification_agents"] == []


def test_evolution_report_requires_authenticated_user(monkeypatch):
    client = _client(monkeypatch, current_user=None, analyzer_cls=EmptyAnalyzer)

    response = client.get("/api/admin/evolution/report")

    assert response.status_code in {401, 403}
