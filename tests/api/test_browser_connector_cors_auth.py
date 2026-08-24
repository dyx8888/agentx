"""
Local CORS and auth contract tests for the browser connector.
"""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ALLOWED_ORIGIN = "https://agentx-demo.example.com"
UNKNOWN_ORIGIN = "https://evil.example.com"


def _valid_payload():
    return {
        "connector": {
            "source": "agentx-browser-extension",
            "extension_id": "local-dev",
            "version": "0.1.0",
            "mode": "readonly",
        },
        "page": {
            "url": "https://partner.example.com/dashboard",
            "title": "Partner dashboard",
            "referrer": "https://partner.example.com/",
        },
        "api": {
            "url": "https://partner.example.com/api/kols?page=1",
            "method": "GET",
            "status_code": 200,
            "matched_rule": "partner-kol-list",
            "response_mime": "application/json",
            "captured_from": "fetch",
        },
        "data": {
            "items": [
                {"name": "creator-a", "followers": 12000},
                {"name": "creator-b", "followers": 8000},
            ],
            "total": 2,
        },
        "policy": {
            "whitelist_rule": "partner-kol-list",
            "redaction_version": "v1",
            "contains_credentials": False,
            "contains_sensitive_fields": False,
            "platform_write_operation": False,
        },
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


@pytest.fixture(autouse=True)
def browser_connector_rollout_gate(monkeypatch):
    monkeypatch.setenv("FEATURE_BROWSER_CONNECTOR", "false")
    monkeypatch.setenv("FEATURE_BROWSER_CONNECTOR_TENANT_IDS", "42")
    monkeypatch.delenv("FEATURE_BROWSER_CONNECTOR_USER_IDS", raising=False)


@pytest.fixture
def db_session():
    from app.database.models import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _build_client(db_session, *, current_user=None, origins=None):
    from app.api.browser_connector import router as browser_connector_router
    from app.auth import get_current_active_user
    from app.database.core import get_db

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or [ALLOWED_ORIGIN],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(browser_connector_router, prefix="/api/browser-connector")

    def mock_get_db():
        yield db_session

    app.dependency_overrides[get_db] = mock_get_db
    if current_user is not None:
        app.dependency_overrides[get_current_active_user] = lambda: current_user

    return TestClient(app)


def _user(*, user_id=7, company_id=42, username="owner"):
    return SimpleNamespace(id=user_id, company_id=company_id, username=username, disabled=False)


def test_unknown_origin_is_not_reflected_for_connector_status(db_session):
    client = _build_client(db_session, current_user=_user())

    response = client.get(
        "/api/browser-connector/status",
        headers={"Origin": UNKNOWN_ORIGIN},
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") != UNKNOWN_ORIGIN
    assert "access-control-allow-origin" not in response.headers


def test_allowed_origin_allows_credentials_for_connector_preflight(db_session):
    client = _build_client(db_session, current_user=_user())

    response = client.options(
        "/api/browser-connector/ingest",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


def test_unknown_origin_preflight_is_rejected_for_connector_ingest(db_session):
    client = _build_client(db_session, current_user=_user())

    response = client.options(
        "/api/browser-connector/ingest",
        headers={
            "Origin": UNKNOWN_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code in {400, 403}
    assert response.headers.get("access-control-allow-origin") != UNKNOWN_ORIGIN


def test_ingest_without_login_is_rejected(db_session):
    client = _build_client(db_session)

    response = client.post("/api/browser-connector/ingest", json=_valid_payload())

    assert response.status_code in {401, 403}


def test_ingest_rejects_non_pilot_tenant(monkeypatch, db_session):
    monkeypatch.setenv("FEATURE_BROWSER_CONNECTOR_TENANT_IDS", "42")
    client = _build_client(
        db_session,
        current_user=_user(user_id=8, company_id=77, username="non-pilot"),
    )

    response = client.post("/api/browser-connector/ingest", json=_valid_payload())

    assert response.status_code == 403
    assert "browser_connector_disabled" in response.text


def test_status_returns_enabled_for_authorized_tenant(db_session):
    client = _build_client(db_session, current_user=_user())

    response = client.get("/api/browser-connector/status")

    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True
    assert data["reason"] == "enabled"
    assert data["tenant_id"] == 42


def test_ingest_allows_authorized_tenant(db_session):
    client = _build_client(db_session, current_user=_user())

    response = client.post("/api/browser-connector/ingest", json=_valid_payload())

    assert response.status_code == 202
    data = response.json()
    assert data["accepted"] is True
    assert data["tenant_id"] == 42
    assert data["company_id"] == 42
    assert data["user_id"] == 7


def test_main_app_production_cors_contract_rejects_wildcard_origins():
    repo_root = Path(__file__).resolve().parents[2]
    main_text = (repo_root / "backend" / "app" / "main.py").read_text(encoding="utf-8")

    assert 'CORS_ORIGINS cannot contain \'*\' in production' in main_text
    assert "allow_credentials=True" in main_text
    assert '"*" in origins' in main_text
