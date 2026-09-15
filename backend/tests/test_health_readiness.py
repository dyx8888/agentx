from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import db
from app.middleware.logging import HealthCheckMiddleware


class _HealthyDb:
    def health_check(self):
        return {"status": "healthy"}


class _UnhealthyDb:
    def health_check(self):
        return {"status": "unhealthy", "error": "db unavailable"}


def _install_fake_db(fake_db):
    previous = db._instance
    db._set_instance(fake_db)
    return previous


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(HealthCheckMiddleware)
    return TestClient(app)


def test_health_returns_healthy_when_database_is_healthy(monkeypatch):
    previous_db = _install_fake_db(_HealthyDb())
    try:
        monkeypatch.delenv("REDIS_URL", raising=False)
        response = _client().get("/health")
    finally:
        db._set_instance(previous_db)

    data = response.json()
    assert response.status_code == 200
    assert data["status"] in {"healthy", "degraded"}
    assert data["overall"] in {"healthy", "degraded"}
    assert data["database"]["status"] == "healthy"


def test_health_returns_503_when_database_is_unhealthy(monkeypatch):
    previous_db = _install_fake_db(_UnhealthyDb())
    try:
        monkeypatch.delenv("REDIS_URL", raising=False)
        response = _client().get("/health")
    finally:
        db._set_instance(previous_db)

    data = response.json()
    assert response.status_code in {200, 503}
    assert data["overall"] in {"degraded", "unhealthy"}
    if "database" in data:
        assert data["database"]["status"] == "unhealthy"


def test_health_alias_path_uses_same_middleware_probe(monkeypatch):
    previous_db = _install_fake_db(_HealthyDb())
    try:
        monkeypatch.delenv("REDIS_URL", raising=False)
        response = _client().get("/health/db")
    finally:
        db._set_instance(previous_db)

    assert response.status_code == 200
    assert response.json()["overall"] in {"healthy", "degraded"}


def test_ready_defaults_to_postgres_for_lightweight_production(monkeypatch):
    previous_db = _install_fake_db(_HealthyDb())
    try:
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("VECTOR_DB", raising=False)
        monkeypatch.delenv("MILVUS_HOST", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)
        client = _client()
        client.app.state.runtime = SimpleNamespace(initialized=True)
        response = client.get("/ready")
    finally:
        db._set_instance(previous_db)

    data = response.json()
    assert response.status_code == 200
    assert data["ready"] is True
    assert data["environment"]["vector_db"] == "postgres"
    assert data["milvus"] == {"status": "not_configured", "backend": "postgres"}


def test_ready_respects_explicit_milvus_backend(monkeypatch):
    previous_db = _install_fake_db(_HealthyDb())
    try:
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("VECTOR_DB", "milvus")
        monkeypatch.delenv("MILVUS_HOST", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)
        client = _client()
        client.app.state.runtime = SimpleNamespace(initialized=True)
        response = client.get("/ready")
    finally:
        db._set_instance(previous_db)

    data = response.json()
    assert response.status_code == 503
    assert data["ready"] is False
    assert data["environment"]["vector_db"] == "milvus"
