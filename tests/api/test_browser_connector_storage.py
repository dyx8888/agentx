"""
Storage tests for sanitized browser connector capture events.
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _payload():
    return {
        "connector": {
            "source": "chrome-extension-mv3",
            "extension_id": "local-dev-extension",
            "version": "0.1.0",
            "mode": "readonly",
        },
        "page": {
            "url": "https://buyin.jinritemai.com/dashboard",
            "title": "AgentX connector storage test",
            "referrer": None,
        },
        "api": {
            "url": "https://buyin.jinritemai.com/square_pc_api/square/search_feed_author?page=1",
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


def _user(user_id=7, company_id=42):
    return SimpleNamespace(id=user_id, company_id=company_id, username=f"user-{user_id}", disabled=False)


@pytest.fixture(autouse=True)
def browser_connector_rollout_gate(monkeypatch):
    monkeypatch.delenv("FEATURE_BROWSER_CONNECTOR", raising=False)
    monkeypatch.setenv("FEATURE_BROWSER_CONNECTOR_TENANT_IDS", "42,99")


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


def _client(db_session, current_user):
    from app.api.browser_connector import router as browser_connector_router
    from app.auth import get_current_active_user
    from app.database.core import get_db

    app = FastAPI()
    app.include_router(browser_connector_router, prefix="/api/browser-connector")

    async def mock_get_user():
        return current_user

    def mock_get_db():
        yield db_session

    app.dependency_overrides[get_current_active_user] = mock_get_user
    app.dependency_overrides[get_db] = mock_get_db
    return TestClient(app)


def test_ingest_persists_sanitized_event_bound_to_tenant_and_user(db_session):
    from app.database.models import BrowserConnectorEvent

    response = _client(db_session, _user()).post("/api/browser-connector/ingest", json=_payload())

    assert response.status_code == 202
    data = response.json()
    assert data["event_id"] is not None
    assert data["duplicate"] is False

    event = db_session.query(BrowserConnectorEvent).one()
    assert event.id == data["event_id"]
    assert event.company_id == 42
    assert event.user_id == 7
    assert event.source == "chrome-extension-mv3"
    assert event.platform == "douyin"
    assert event.matched_rule == "buyin-api"
    assert event.api_method == "GET"
    assert event.status_code == 200
    assert event.response_mime == "application/json"
    assert len(event.api_url_hash) == 64
    assert len(event.payload_hash) == 64

    stored_payload = json.loads(event.sanitized_payload_json)
    assert stored_payload["value"]["authors"][0]["name"] == "creator-a"
    serialized_event = json.dumps(
        {
            "api_url_hash": event.api_url_hash,
            "payload_hash": event.payload_hash,
            "sanitized_payload_json": event.sanitized_payload_json,
        },
        ensure_ascii=False,
    )
    assert "page=1" not in serialized_event
    assert "token" not in serialized_event.lower()
    assert "password" not in serialized_event.lower()
    assert "cookie" not in serialized_event.lower()


def test_repeated_payload_returns_existing_event_without_duplicate_row(db_session):
    client = _client(db_session, _user())

    first = client.post("/api/browser-connector/ingest", json=_payload())
    second = client.post("/api/browser-connector/ingest", json=_payload())

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["duplicate"] is True
    assert second.json()["event_id"] == first.json()["event_id"]

    from app.database.models import BrowserConnectorEvent

    assert db_session.query(BrowserConnectorEvent).count() == 1


def test_same_payload_is_isolated_by_company(db_session):
    client_a = _client(db_session, _user(user_id=7, company_id=42))
    client_b = _client(db_session, _user(user_id=8, company_id=99))

    assert client_a.post("/api/browser-connector/ingest", json=_payload()).status_code == 202
    assert client_b.post("/api/browser-connector/ingest", json=_payload()).status_code == 202

    from app.database.models import BrowserConnectorEvent
    from app.services.browser_connector_capture import list_browser_connector_events

    assert db_session.query(BrowserConnectorEvent).count() == 2
    assert [event.company_id for event in list_browser_connector_events(db_session, company_id=42)] == [42]
    assert [event.company_id for event in list_browser_connector_events(db_session, company_id=99)] == [99]


def test_storage_safety_rejection_returns_validation_error(db_session):
    payload = _payload()
    payload["data"]["value"]["otp"] = "must-not-store"

    response = _client(db_session, _user()).post("/api/browser-connector/ingest", json=payload)

    assert response.status_code == 422
    assert "sensitive connector field" in response.text


def test_storage_layer_rejects_sensitive_fields_even_if_called_directly(db_session):
    from app.services.browser_connector_capture import store_browser_connector_capture

    unsafe_request = SimpleNamespace(
        connector=SimpleNamespace(source="chrome-extension-mv3"),
        api=SimpleNamespace(
            url="https://buyin.jinritemai.com/square_pc_api/square/search_feed_author",
            method="GET",
            status_code=200,
            matched_rule="buyin-api",
            response_mime="application/json",
        ),
        data={"items": [{"name": "creator-a", "password": "must-not-store"}]},
        captured_at=datetime.now(timezone.utc),
    )

    with pytest.raises(ValueError, match="sensitive connector field"):
        store_browser_connector_capture(db_session, unsafe_request, _user())
