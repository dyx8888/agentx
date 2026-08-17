from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    return TestClient(app)


def _set_auth_cookie_headers(response):
    return response.headers.get_list("set-cookie")


def test_logout_accepts_empty_json_body_and_clears_auth_cookies():
    response = _client().post("/api/auth/token/logout", json={})

    cookies = _set_auth_cookie_headers(response)

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert any(cookie.startswith("access_token=") and "Max-Age=0" in cookie for cookie in cookies)
    assert any(cookie.startswith("refresh_token=") and "Max-Age=0" in cookie for cookie in cookies)


def test_logout_accepts_no_body_and_clears_auth_cookies():
    response = _client().post("/api/auth/token/logout")

    cookies = _set_auth_cookie_headers(response)

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert any(cookie.startswith("access_token=") and "Max-Age=0" in cookie for cookie in cookies)
    assert any(cookie.startswith("refresh_token=") and "Max-Age=0" in cookie for cookie in cookies)


def test_logout_cookie_only_mode_does_not_require_refresh_token_body(monkeypatch):
    monkeypatch.setattr(
        auth_router,
        "decode_refresh_token",
        lambda token: ("smoke-user", None, 0) if token == "cookie-refresh-token" else None,
    )

    response = _client().post(
        "/api/auth/token/logout",
        cookies={
            "access_token": "cookie-access-token",
            "refresh_token": "cookie-refresh-token",
        },
    )

    cookies = _set_auth_cookie_headers(response)

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert any(cookie.startswith("access_token=") and "Max-Age=0" in cookie for cookie in cookies)
    assert any(cookie.startswith("refresh_token=") and "Max-Age=0" in cookie for cookie in cookies)
