"""Business integration tests for browser connector normalized records."""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _user(user_id=7, company_id=42):
    return SimpleNamespace(id=user_id, company_id=company_id, username=f"user-{user_id}", disabled=False)


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


@pytest.fixture(autouse=True)
def browser_connector_rollout_gate(monkeypatch):
    monkeypatch.delenv("FEATURE_BROWSER_CONNECTOR", raising=False)
    monkeypatch.setenv("FEATURE_BROWSER_CONNECTOR_TENANT_IDS", "42")


@pytest.fixture
def client(db_session):
    from app.api.browser_connector import router as browser_connector_router
    from app.auth import get_current_active_user
    from app.database.core import get_db

    app = FastAPI()
    app.include_router(browser_connector_router, prefix="/api/browser-connector")

    async def mock_get_user():
        return _user()

    def mock_get_db():
        yield db_session

    app.dependency_overrides[get_current_active_user] = mock_get_user
    app.dependency_overrides[get_db] = mock_get_db
    return TestClient(app)


def _add_event(db_session, payload, *, event_id=101, company_id=42, matched_rule="buyin-api"):
    from app.database.models import BrowserConnectorEvent

    event = BrowserConnectorEvent(
        id=event_id,
        company_id=company_id,
        user_id=7,
        source="chrome-extension-mv3",
        platform="douyin",
        matched_rule=matched_rule,
        api_url_hash=f"{event_id:064x}"[-64:],
        api_method="GET",
        status_code=200,
        response_mime="application/json",
        sanitized_payload_json=json.dumps(payload, ensure_ascii=False),
        payload_hash=f"{event_id + 1000:064x}"[-64:],
        captured_at=datetime(2026, 8, 13),
        created_at=datetime(2026, 8, 13),
    )
    db_session.add(event)
    db_session.commit()
    return event


def _creator_payload(name="美妆达人A", uid="dy-a"):
    return {
        "kind": "json",
        "value": {
            "authors": [
                {
                    "nickname": name,
                    "uid": uid,
                    "fans_count": "1.2万",
                    "interaction_rate": "4.5%",
                    "category": "美妆",
                    "avg_play_count": 50000,
                    "city": "杭州",
                    "is_verified": "已认证",
                }
            ]
        },
    }


def _knowledge_payload():
    return {
        "kind": "json",
        "value": {
            "insights": [
                {
                    "title": "直播复盘",
                    "summary": "达人短视频先种草再开播时，转化率明显提升。",
                    "tags": "livestream,creator",
                }
            ]
        },
    }


def _campaign_payload():
    return {
        "kind": "json",
        "value": {
            "campaigns": [
                {
                    "campaign_id": "qc-1",
                    "campaign_name": "夏季投放",
                    "impressions": 1000,
                    "clicks": 50,
                    "orders": 5,
                    "spend": 250,
                    "gmv": 1000,
                }
            ]
        },
    }


def test_records_preview_is_tenant_scoped(client, db_session):
    _add_event(db_session, _creator_payload(), event_id=101, company_id=42)
    _add_event(db_session, _creator_payload(name="别家公司达人", uid="dy-other"), event_id=102, company_id=99)

    response = client.get("/api/browser-connector/records?kind=creator_profile")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["records"][0]["company_id"] == 42
    assert data["records"][0]["record"]["name"] == "美妆达人A"
    assert data["records"][0]["record"]["data_source"] == "browser_connector"


def test_import_kols_requires_explicit_non_dry_run_and_marks_connector_source(client, db_session):
    _add_event(db_session, _creator_payload(), event_id=101, company_id=42)

    dry_run = client.post("/api/browser-connector/import/kols", json={"event_ids": [101]})
    assert dry_run.status_code == 200
    assert dry_run.json()["dry_run"] is True
    assert dry_run.json()["imported"] == 1

    from app.database.models import KolProfile

    assert db_session.query(KolProfile).count() == 0

    imported = client.post(
        "/api/browser-connector/import/kols",
        json={"event_ids": [101], "dry_run": False},
    )

    assert imported.status_code == 200
    assert imported.json()["imported"] == 1
    kol = db_session.query(KolProfile).one()
    assert kol.company_id == 42
    assert kol.name == "美妆达人A"
    assert kol.platform_uid == "dy-a"
    assert kol.followers == 12000
    assert kol.engagement_rate == 4.5
    assert kol.data_source == "browser_connector"
    assert "browser_connector_event:101" in kol.contact_info

    updated = client.post(
        "/api/browser-connector/import/kols",
        json={"event_ids": [101], "dry_run": False},
    )
    assert updated.json()["updated"] == 1
    assert db_session.query(KolProfile).count() == 1


def test_import_knowledge_calls_existing_knowledge_ingest_after_confirmation(
    client, db_session, monkeypatch
):
    _add_event(db_session, _knowledge_payload(), event_id=201, company_id=42)
    calls = []

    def fake_add_knowledge(**kwargs):
        calls.append(kwargs)
        return json.dumps({"status": "ok", "data": {"doc_id": "doc-201"}})

    monkeypatch.setattr("app.api.knowledge.add_knowledge", fake_add_knowledge)
    monkeypatch.setattr("app.api.knowledge._invalidate_result_cache_for_company", lambda company_id: 0)

    dry_run = client.post("/api/browser-connector/import/knowledge", json={"event_ids": [201]})
    assert dry_run.status_code == 200
    assert dry_run.json()["dry_run"] is True
    assert calls == []

    imported = client.post(
        "/api/browser-connector/import/knowledge",
        json={"event_ids": [201], "dry_run": False},
    )

    assert imported.status_code == 200
    assert imported.json()["imported"] == 1
    assert imported.json()["doc_ids"] == ["doc-201"]
    assert calls[0]["company_id"] == "42"
    assert "转化率明显提升" in calls[0]["text"]
    assert calls[0]["metadata"]["source"] == "browser_connector"
    assert calls[0]["metadata"]["external_id"] == "browser_connector_event:201"


def test_campaign_snapshots_are_read_only_analysis_records(client, db_session):
    _add_event(db_session, _campaign_payload(), event_id=301, company_id=42, matched_rule="oceanengine-api")

    response = client.get("/api/browser-connector/analytics/campaign-snapshots")

    assert response.status_code == 200
    data = response.json()
    assert data["read_only"] is True
    assert data["total"] == 1
    snapshot = data["records"][0]["record"]
    assert snapshot["campaign_id"] == "qc-1"
    assert snapshot["ctr"] == 0.05
    assert snapshot["cpa"] == 50
    assert snapshot["roi"] == 4
    assert "auto_execute" not in snapshot
