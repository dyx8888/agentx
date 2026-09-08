"""Integration coverage for explicit, tenant-bound browser capture jobs."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _user(user_id=7, company_id=42):
    return SimpleNamespace(id=user_id, company_id=company_id, username=f"user-{user_id}", disabled=False)


def _payload():
    return {
        "connector": {"source": "chrome-extension-mv3", "mode": "readonly"},
        "page": {"url": "https://www.xiaohongshu.com/explore/safe-test", "title": "公开测试页面", "referrer": None},
        "api": {
            "url": "https://www.xiaohongshu.com/explore/safe-test",
            "method": "GET",
            "status_code": 200,
            "matched_rule": "generic-web-page",
            "response_mime": "text/html",
            "captured_from": "fetch",
        },
        "data": {
            "kind": "generic_web_page",
            "title": "公开测试页面",
            "headings": ["公开内容"],
            "visible_text": "这是用于当前会话的公开页面采集测试。",
        },
        "policy": {
            "whitelist_rule": "generic-web-page",
            "contains_credentials": False,
            "contains_sensitive_fields": False,
            "platform_write_operation": False,
        },
    }


@pytest.fixture
def db_session():
    from app.database.models import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _client(db_session, current_user):
    from app.api.browser_connector import router
    from app.auth import get_current_active_user
    from app.database.core import get_db

    app = FastAPI()
    app.include_router(router, prefix="/api/browser-connector")

    async def mock_user():
        return current_user

    def mock_db():
        yield db_session

    app.dependency_overrides[get_current_active_user] = mock_user
    app.dependency_overrides[get_db] = mock_db
    return TestClient(app)


def _conversation(db_session, *, conversation_id=101, user_id=7, company_id=42):
    from app.database.models import Conversation

    conversation = Conversation(
        id=conversation_id,
        user_id=user_id,
        company_id=company_id,
        title="采集任务测试",
        status="active",
        message_count=0,
    )
    db_session.add(conversation)
    db_session.commit()
    return conversation


def _create_job(client, conversation_id=101):
    response = client.post(
        "/api/browser-connector/capture-jobs",
        json={
            "conversation_id": conversation_id,
            "target_url": "https://www.xiaohongshu.com/explore",
            "purpose": "competitor_evidence",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_capture_job_binds_owner_conversation_and_excludes_ticket_from_job_response(db_session):
    _conversation(db_session)
    created = _create_job(_client(db_session, _user()))

    assert created["job"]["conversation_id"] == 101
    assert created["job"]["status"] == "pending"
    assert created["job"]["purpose"] == "competitor_evidence"
    assert created["job"]["target_host"] == "www.xiaohongshu.com"
    assert "capability_ticket" not in created["job"]
    assert len(created["capability_ticket"]) >= 16


def test_ingest_with_job_marks_captured_and_generates_on_platform_draft(db_session):
    _conversation(db_session)
    client = _client(db_session, _user())
    created = _create_job(client)
    payload = _payload()
    payload.update(
        {
            "capture_job_id": created["job"]["id"],
            "capability_ticket": created["capability_ticket"],
            "company_id": 999,
            "user_id": 999,
            "conversation_id": 999,
        }
    )

    accepted = client.post("/api/browser-connector/ingest", json=payload)
    assert accepted.status_code == 202
    assert accepted.json()["capture_job_id"] == created["job"]["id"]
    assert accepted.json()["capture_status"] == "captured"
    assert accepted.json()["classification"] == "competitor_evidence"

    job = client.get(f"/api/browser-connector/capture-jobs/{created['job']['id']}")
    assert job.status_code == 200
    assert job.json()["status"] == "captured"
    assert job.json()["evidence"]["classification"] == "competitor_evidence"

    classified = client.post(
        f"/api/browser-connector/capture-jobs/{created['job']['id']}/classify"
    )
    assert classified.status_code == 200
    assert classified.json()["status"] == "classified"

    draft = client.post(
        f"/api/browser-connector/capture-jobs/{created['job']['id']}/draft",
        json={"draft_kind": "analysis_summary"},
    )
    assert draft.status_code == 200
    assert draft.json()["job"]["status"] == "draft_ready"
    assert "仅站内" in draft.json()["content"]


def test_capture_ticket_cannot_be_replayed_and_wrong_owner_is_rejected(db_session):
    _conversation(db_session)
    owner_client = _client(db_session, _user())
    created = _create_job(owner_client)
    payload = _payload()
    payload.update({"capture_job_id": created["job"]["id"], "capability_ticket": created["capability_ticket"]})

    intruder = _client(db_session, _user(user_id=8, company_id=42))
    assert intruder.post("/api/browser-connector/ingest", json=payload).status_code == 403
    assert owner_client.post("/api/browser-connector/ingest", json=payload).status_code == 202
    assert owner_client.post("/api/browser-connector/ingest", json=payload).status_code == 403


def test_capture_job_rejects_expired_ticket_and_target_mismatch(db_session):
    from app.database.models import CaptureJob

    _conversation(db_session)
    client = _client(db_session, _user())
    created = _create_job(client)
    job = db_session.query(CaptureJob).filter(CaptureJob.id == created["job"]["id"]).one()
    job.ticket_expires_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()

    expired_payload = _payload()
    expired_payload.update({"capture_job_id": job.id, "capability_ticket": created["capability_ticket"]})
    assert client.post("/api/browser-connector/ingest", json=expired_payload).status_code == 403

    created = _create_job(client)
    mismatch_payload = _payload()
    mismatch_payload["page"]["url"] = "https://www.xiaohongshu.com/search_result/safe-test"
    mismatch_payload["api"]["url"] = "https://www.xiaohongshu.com/search_result/safe-test"
    mismatch_payload.update({"capture_job_id": created["job"]["id"], "capability_ticket": created["capability_ticket"]})
    assert client.post("/api/browser-connector/ingest", json=mismatch_payload).status_code == 403


def test_capture_job_rejects_unrelated_subdomain_with_same_country_suffix(db_session):
    _conversation(db_session)
    client = _client(db_session, _user())
    created = client.post(
        "/api/browser-connector/capture-jobs",
        json={
            "conversation_id": 101,
            "target_url": "https://shop.example.co.uk/catalog",
            "purpose": "generic_evidence",
        },
    ).json()
    payload = _payload()
    payload["page"]["url"] = "https://shop.example.co.uk/catalog/item"
    payload["api"]["url"] = "https://other.co.uk/public/catalog"
    payload.update({"capture_job_id": created["job"]["id"], "capability_ticket": created["capability_ticket"]})

    assert client.post("/api/browser-connector/ingest", json=payload).status_code == 403


def test_capture_jobs_stay_scoped_to_current_tenant_and_user(db_session):
    _conversation(db_session)
    owner_client = _client(db_session, _user())
    created = _create_job(owner_client)

    other_company = _client(db_session, _user(user_id=9, company_id=43))
    assert other_company.get(f"/api/browser-connector/capture-jobs/{created['job']['id']}").status_code == 404
    assert other_company.get("/api/browser-connector/capture-jobs").json()["items"] == []


def test_jobless_ingest_keeps_legacy_pending_capture_path(db_session):
    client = _client(db_session, _user())
    response = client.post("/api/browser-connector/ingest", json=_payload())
    assert response.status_code == 202
    assert response.json()["capture_job_id"] is None
