import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.api.browser_connector as browser_connector


def _user(*, user_id=7, company_id=239):
    return SimpleNamespace(id=user_id, username="connector_user", company_id=company_id)


def _request_with_spoofed_identity():
    return browser_connector.BrowserConnectorIngestRequest(
        connector={
            "source": "chrome-extension-mv3",
            "version": "0.1.0",
            "mode": "readonly",
        },
        page={"url": "https://buyin.jinritemai.com/square"},
        api={
            "url": "https://buyin.jinritemai.com/square_pc_api/square/search_feed_author",
            "method": "GET",
            "status_code": 200,
            "matched_rule": "buyin-api",
            "captured_from": "fetch",
        },
        data={"items": [{"nickname": "Safe Creator"}]},
        policy={
            "whitelist_rule": "buyin-api",
            "contains_credentials": False,
            "contains_sensitive_fields": False,
            "platform_write_operation": False,
        },
        tenant_id=999,
        company_id=999,
        user_id=999,
    )


def test_browser_connector_enabled_for_tenant_bound_user_without_allowlist(monkeypatch):
    monkeypatch.delenv("FEATURE_BROWSER_CONNECTOR", raising=False)

    company_id, enabled, reason = browser_connector._browser_connector_rollout_state(
        _user(company_id=239)
    )

    assert company_id == 239
    assert enabled is True
    assert reason == "enabled"
    assert browser_connector._require_browser_connector_enabled(_user(company_id=239)) == 239


def test_browser_connector_emergency_switch_can_disable_all_users(monkeypatch):
    monkeypatch.setenv("FEATURE_BROWSER_CONNECTOR", "false")

    company_id, enabled, reason = browser_connector._browser_connector_rollout_state(
        _user(company_id=239)
    )

    assert company_id == 239
    assert enabled is False
    assert reason == "browser_connector_disabled"
    with pytest.raises(HTTPException) as exc_info:
        browser_connector._require_browser_connector_enabled(_user(company_id=239))
    assert exc_info.value.status_code == 403
    assert "browser_connector_disabled" in str(exc_info.value.detail)


def test_browser_connector_requires_tenant_bound_user(monkeypatch):
    monkeypatch.delenv("FEATURE_BROWSER_CONNECTOR", raising=False)

    company_id, enabled, reason = browser_connector._browser_connector_rollout_state(
        _user(company_id=None)
    )

    assert company_id is None
    assert enabled is False
    assert reason == "tenant_required"
    with pytest.raises(HTTPException) as exc_info:
        browser_connector._require_browser_connector_enabled(_user(company_id=None))
    assert exc_info.value.status_code == 403
    assert "tenant-bound user" in str(exc_info.value.detail)


def test_browser_connector_ingest_binds_identity_from_current_user(monkeypatch):
    monkeypatch.delenv("FEATURE_BROWSER_CONNECTOR", raising=False)
    current_user = _user(user_id=7, company_id=239)
    request = _request_with_spoofed_identity()
    captured = {}

    def fake_store(db, ingest_request, user):
        captured["db"] = db
        captured["request"] = ingest_request
        captured["user"] = user
        return SimpleNamespace(event=SimpleNamespace(id=55), duplicate=False)

    monkeypatch.setattr(browser_connector, "store_browser_connector_capture", fake_store)

    response = asyncio.run(
        browser_connector.ingest_browser_connector_payload(
            request=request,
            current_user=current_user,
            db=object(),
        )
    )

    assert captured["user"] is current_user
    assert response.accepted is True
    assert response.company_id == 239
    assert response.tenant_id == 239
    assert response.user_id == 7
    assert response.event_id == 55
