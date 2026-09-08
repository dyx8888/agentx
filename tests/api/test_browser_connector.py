"""
Tests for the AgentX browser connector ingest MVP.
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


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


def _extension_payload():
    return {
        "connector": {
            "source": "chrome-extension-mv3",
            "extension_id": "local-dev-extension",
            "version": "0.1.0",
            "mode": "readonly",
        },
        "page": {
            "url": "https://buyin.jinritemai.com/dashboard",
            "title": "精选联盟达人广场",
            "referrer": None,
        },
        "api": {
            "url": "https://buyin.jinritemai.com/square_pc_api/square/search_feed_author",
            "method": "GET",
            "status_code": 200,
            "matched_rule": "buyin-api",
            "response_mime": "application/json",
            "captured_from": "fetch",
        },
        "data": {
            "kind": "json",
            "value": {
                "authors": [
                    {"name": "creator-a", "followers": 12000},
                    {"name": "creator-b", "followers": 8000},
                ],
                "total": 2,
            },
        },
        "policy": {
            "whitelist_rule": "buyin-api",
            "redaction_version": "v1",
            "contains_credentials": False,
            "contains_sensitive_fields": False,
            "platform_write_operation": False,
        },
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


@pytest.fixture
def mock_current_user():
    return SimpleNamespace(id=7, company_id=42, username="owner", disabled=False)


@pytest.fixture(autouse=True)
def browser_connector_rollout_gate(monkeypatch):
    monkeypatch.delenv("FEATURE_BROWSER_CONNECTOR", raising=False)
    monkeypatch.setenv("FEATURE_BROWSER_CONNECTOR_TENANT_IDS", "42")


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


@pytest.fixture
def client(mock_current_user, db_session):
    from app.api.browser_connector import router as browser_connector_router
    from app.auth import get_current_active_user
    from app.database.core import get_db

    app = FastAPI()
    app.include_router(
        browser_connector_router,
        prefix="/api/browser-connector",
        tags=["browser-connector"],
    )

    async def mock_get_user():
        return mock_current_user

    def mock_get_db():
        yield db_session

    app.dependency_overrides[get_current_active_user] = mock_get_user
    app.dependency_overrides[get_db] = mock_get_db
    return TestClient(app)


def test_ingest_requires_authentication(db_session):
    from app.api.browser_connector import router as browser_connector_router
    from app.database.core import get_db

    app = FastAPI()
    app.include_router(browser_connector_router, prefix="/api/browser-connector")

    def mock_get_db():
        yield db_session

    app.dependency_overrides[get_db] = mock_get_db

    response = TestClient(app).post("/api/browser-connector/ingest", json=_valid_payload())

    assert response.status_code in {401, 403}


def test_ingest_binds_authenticated_user_and_tenant(client):
    response = client.post("/api/browser-connector/ingest", json=_valid_payload())

    assert response.status_code == 202
    data = response.json()
    assert data["accepted"] is True
    assert data["tenant_id"] == 42
    assert data["company_id"] == 42
    assert data["user_id"] == 7
    assert data["matched_rule"] == "partner-kol-list"
    assert data["data_shape"] == "object"
    assert "items" not in data


def test_ingest_allows_tenant_bound_user_without_rollout_allowlist(monkeypatch, db_session):
    from app.api.browser_connector import router as browser_connector_router
    from app.auth import get_current_active_user
    from app.database.core import get_db

    monkeypatch.delenv("FEATURE_BROWSER_CONNECTOR", raising=False)
    monkeypatch.setenv("FEATURE_BROWSER_CONNECTOR_TENANT_IDS", "")
    app = FastAPI()
    app.include_router(browser_connector_router, prefix="/api/browser-connector")

    async def mock_get_user():
        return SimpleNamespace(id=8, company_id=77, username="non-pilot", disabled=False)

    def mock_get_db():
        yield db_session

    app.dependency_overrides[get_current_active_user] = mock_get_user
    app.dependency_overrides[get_db] = mock_get_db

    response = TestClient(app).post("/api/browser-connector/ingest", json=_valid_payload())

    assert response.status_code == 202
    data = response.json()
    assert data["accepted"] is True
    assert data["company_id"] == 77
    assert data["tenant_id"] == 77
    assert data["user_id"] == 8


def test_ingest_returns_explicit_disabled_when_emergency_switch_is_off(monkeypatch, db_session):
    from app.api.browser_connector import router as browser_connector_router
    from app.auth import get_current_active_user
    from app.database.core import get_db

    monkeypatch.setenv("FEATURE_BROWSER_CONNECTOR", "false")
    monkeypatch.setenv("FEATURE_BROWSER_CONNECTOR_TENANT_IDS", "")
    app = FastAPI()
    app.include_router(browser_connector_router, prefix="/api/browser-connector")

    async def mock_get_user():
        return SimpleNamespace(id=8, company_id=77, username="disabled", disabled=False)

    def mock_get_db():
        yield db_session

    app.dependency_overrides[get_current_active_user] = mock_get_user
    app.dependency_overrides[get_db] = mock_get_db

    response = TestClient(app).post("/api/browser-connector/ingest", json=_valid_payload())

    assert response.status_code == 403
    assert "browser_connector_disabled" in response.text


def test_global_rollout_flag_allows_non_allowlisted_tenant(monkeypatch, db_session):
    from app.api.browser_connector import router as browser_connector_router
    from app.auth import get_current_active_user
    from app.database.core import get_db

    monkeypatch.setenv("FEATURE_BROWSER_CONNECTOR_TENANT_IDS", "")
    monkeypatch.setenv("FEATURE_BROWSER_CONNECTOR", "true")
    app = FastAPI()
    app.include_router(browser_connector_router, prefix="/api/browser-connector")

    async def mock_get_user():
        return SimpleNamespace(id=8, company_id=77, username="enabled", disabled=False)

    def mock_get_db():
        yield db_session

    app.dependency_overrides[get_current_active_user] = mock_get_user
    app.dependency_overrides[get_db] = mock_get_db

    response = TestClient(app).post("/api/browser-connector/ingest", json=_valid_payload())

    assert response.status_code == 202
    assert response.json()["company_id"] == 77


def test_status_returns_enabled_for_rollout_tenant(client):
    response = client.get("/api/browser-connector/status")

    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True
    assert data["reason"] == "enabled"
    assert data["feature"] == "browser_connector"
    assert data["tenant_id"] == 42
    assert data["company_id"] == 42
    assert data["user_id"] == 7


def test_status_returns_enabled_without_record_lookup_allowlist(monkeypatch, db_session):
    from app.api.browser_connector import router as browser_connector_router
    from app.auth import get_current_active_user
    from app.database.core import get_db

    monkeypatch.delenv("FEATURE_BROWSER_CONNECTOR", raising=False)
    monkeypatch.setenv("FEATURE_BROWSER_CONNECTOR_TENANT_IDS", "")
    app = FastAPI()
    app.include_router(browser_connector_router, prefix="/api/browser-connector")

    async def mock_get_user():
        return SimpleNamespace(id=8, company_id=77, username="non-pilot", disabled=False)

    def mock_get_db():
        yield db_session

    app.dependency_overrides[get_current_active_user] = mock_get_user
    app.dependency_overrides[get_db] = mock_get_db

    response = TestClient(app).get("/api/browser-connector/status")

    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True
    assert data["reason"] == "enabled"
    assert data["company_id"] == 77


def test_status_returns_tenant_required_for_tenantless_user(monkeypatch, db_session):
    from app.api.browser_connector import router as browser_connector_router
    from app.auth import get_current_active_user
    from app.database.core import get_db

    app = FastAPI()
    app.include_router(browser_connector_router, prefix="/api/browser-connector")

    async def mock_get_user():
        return SimpleNamespace(id=9, company_id=None, username="tenantless", disabled=False)

    def mock_get_db():
        yield db_session

    app.dependency_overrides[get_current_active_user] = mock_get_user
    app.dependency_overrides[get_db] = mock_get_db

    response = TestClient(app).get("/api/browser-connector/status")

    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is False
    assert data["reason"] == "tenant_required"
    assert data["company_id"] is None


def test_ingest_accepts_extension_payload_contract(client):
    response = client.post("/api/browser-connector/ingest", json=_extension_payload())

    assert response.status_code == 202
    data = response.json()
    assert data["accepted"] is True
    assert data["tenant_id"] == 42
    assert data["user_id"] == 7
    assert data["matched_rule"] == "buyin-api"
    assert data["data_shape"] == "object"


def test_client_identity_fields_are_ignored(client):
    payload = _valid_payload()
    payload.update({"tenant_id": 999, "company_id": 888, "user_id": 777})

    response = client.post("/api/browser-connector/ingest", json=payload)

    assert response.status_code == 202
    data = response.json()
    assert data["tenant_id"] == 42
    assert data["company_id"] == 42
    assert data["user_id"] == 7


@pytest.mark.parametrize(
    "sensitive_key",
    [
        "cookie",
        "token",
        "authorization",
        "password",
        "captcha",
        "payment",
        "card",
        "secret",
        "credential",
        "session",
    ],
)
def test_sensitive_payload_key_markers_are_rejected(client, sensitive_key):
    payload = _valid_payload()
    payload["data"]["items"][0][sensitive_key] = "do-not-accept"

    response = client.post("/api/browser-connector/ingest", json=payload)

    assert response.status_code == 422
    assert "sensitive fields" in response.text


def test_policy_rejects_credentials_and_platform_writes(client):
    payload = _valid_payload()
    payload["policy"]["contains_credentials"] = True

    response = client.post("/api/browser-connector/ingest", json=payload)

    assert response.status_code == 422
    assert "credentials" in response.text

    payload = _valid_payload()
    payload["policy"]["platform_write_operation"] = True

    response = client.post("/api/browser-connector/ingest", json=payload)

    assert response.status_code == 422
    assert "read-only" in response.text


def test_sensitive_query_keys_are_rejected(client):
    payload = _valid_payload()
    payload["api"]["url"] = "https://partner.example.com/api/kols?token=abc"

    response = client.post("/api/browser-connector/ingest", json=payload)

    assert response.status_code == 422
    assert "sensitive query keys" in response.text


def test_only_structured_data_is_accepted(client):
    payload = _valid_payload()
    payload["data"] = "raw text is not a structured capture"

    response = client.post("/api/browser-connector/ingest", json=payload)

    assert response.status_code == 422


def test_main_app_registers_browser_connector_route():
    repo_root = Path(__file__).resolve().parents[2]
    main_text = (repo_root / "backend" / "app" / "main.py").read_text(encoding="utf-8")

    assert "browser_connector_router" in main_text
    assert 'prefix="/api/browser-connector"' in main_text


def test_browser_connector_has_no_platform_write_automation_entrypoints():
    repo_root = Path(__file__).resolve().parents[2]
    api_text = (repo_root / "backend" / "app" / "api" / "browser_connector.py").read_text(
        encoding="utf-8"
    )
    service_text = (
        repo_root / "backend" / "app" / "services" / "browser_connector_business.py"
    ).read_text(encoding="utf-8")
    combined = f"{api_text}\n{service_text}".lower()

    forbidden_entrypoints = [
        "execute_stop_loss_action",
        "auto_execute",
        "send_invitation",
        "send_message",
        "update_budget",
        "submit_order",
        "create_order",
        "cancel_order",
        "refund_order",
        "platform_write_request",
    ]
    for entrypoint in forbidden_entrypoints:
        assert entrypoint not in combined

    route_matches = set(
        re.findall(r"@router\.(get|post|put|patch|delete)\(\s*(?:\n\s*)?[\"']([^\"']+)[\"']", api_text)
    )
    assert route_matches == {
        ("get", "/status"),
        ("post", "/ingest"),
        ("post", "/capture-jobs"),
        ("get", "/capture-jobs"),
        ("get", "/capture-jobs/{job_id}"),
        ("post", "/capture-jobs/{job_id}/ticket"),
        ("post", "/capture-jobs/{job_id}/classify"),
        ("post", "/capture-jobs/{job_id}/draft"),
        ("get", "/records"),
        ("post", "/import/kols"),
        ("post", "/import/knowledge"),
        ("get", "/analytics/campaign-snapshots"),
    }
    assert "put" not in {method for method, _ in route_matches}
    assert "patch" not in {method for method, _ in route_matches}
    assert "delete" not in {method for method, _ in route_matches}

    assert "platform_write_operation" in api_text
    assert "Browser connector ingest is read-only" in api_text
