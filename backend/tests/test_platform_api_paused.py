import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.companies as companies_api
import app.api.oauth_router as oauth_api


def _user(*, company_id=239, is_admin=True):
    return SimpleNamespace(id=7, username="tester", company_id=company_id, is_admin=is_admin)


def _serialized(payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _assert_paused(response):
    assert response.status_code == 503
    payload = response.json()
    assert payload["detail"]["code"] == "platform_api_paused"
    assert "浏览器连接器" in payload["detail"]["message"]
    assert "secret-that-must-not-appear" not in _serialized(payload)


def _oauth_client(monkeypatch):
    app = FastAPI()
    app.dependency_overrides[oauth_api.get_current_active_user] = lambda: _user()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("paused OAuth route must not touch platform runtime")

    monkeypatch.setattr(oauth_api, "_create_state", fail_if_called)
    monkeypatch.setattr(oauth_api, "_validate_state", fail_if_called)
    monkeypatch.setattr(oauth_api, "_build_adapter_from_credentials", fail_if_called)
    monkeypatch.setattr(oauth_api, "_store_token_to_db", fail_if_called)

    app.include_router(oauth_api.router, prefix="/api/oauth")
    return TestClient(app)


def test_oauth_authorize_defaults_to_platform_api_paused(monkeypatch):
    client = _oauth_client(monkeypatch)

    response = client.get("/api/oauth/authorize/douyin_shop")

    _assert_paused(response)


def test_oauth_callback_get_defaults_to_platform_api_paused(monkeypatch):
    client = _oauth_client(monkeypatch)

    response = client.get("/api/oauth/callback/douyin_shop?code=fake-code&state=fake-state")

    _assert_paused(response)


def test_oauth_callback_post_defaults_to_platform_api_paused(monkeypatch):
    client = _oauth_client(monkeypatch)

    response = client.post(
        "/api/oauth/callback/douyin_shop",
        json={"code": "fake-code", "state": "fake-state"},
    )

    _assert_paused(response)


def test_platform_credential_verify_defaults_to_platform_api_paused(monkeypatch):
    app = FastAPI()
    app.dependency_overrides[companies_api.get_current_active_user] = lambda: _user()

    class DBMustNotBeTouched:
        def get_company(self, company_id):
            raise AssertionError("paused verify must not read stored platform credentials")

    monkeypatch.setattr(companies_api, "db", DBMustNotBeTouched())
    monkeypatch.setitem(
        companies_api.PLATFORM_ADAPTERS,
        "douyin_shop",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("paused verify must not instantiate platform adapters")
        ),
    )

    app.include_router(companies_api.router, prefix="/api/admin/companies")
    client = TestClient(app)

    response = client.post("/api/admin/companies/239/credentials/douyin_shop/verify")

    _assert_paused(response)
