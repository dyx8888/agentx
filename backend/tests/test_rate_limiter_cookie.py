from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.rate_limiter import RateLimiterMiddleware


def _build_app(monkeypatch, *, user_limit=2, llm_limit=10, ip_limit=100):
    monkeypatch.setenv("TEST_MODE", "false")
    monkeypatch.setattr(RateLimiterMiddleware, "USER_LIMIT", user_limit)
    monkeypatch.setattr(RateLimiterMiddleware, "LLM_LIMIT", llm_limit)
    monkeypatch.setattr(RateLimiterMiddleware, "IP_LIMIT", ip_limit)
    monkeypatch.setattr(RateLimiterMiddleware, "WINDOW_SECONDS", 60)

    def fake_decode(token):
        if token == "header-token":
            return {"sub": "header-user", "company_id": 43}
        return None

    monkeypatch.setattr("app.auth.decode_access_token", fake_decode)

    app = FastAPI()
    app.add_middleware(RateLimiterMiddleware)

    @app.get("/public")
    async def public():
        return {"ok": True}

    @app.get("/private")
    async def private():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    @app.post("/api/chat/")
    async def chat():
        return {"ok": True}

    return app


def test_unauthenticated_requests_are_handled_without_auth_identity(monkeypatch):
    app = _build_app(monkeypatch, user_limit=2, ip_limit=100)
    client = TestClient(app)

    responses = [client.get("/public") for _ in range(3)]

    assert [response.status_code for response in responses[:2]] == [200, 200]
    assert responses[-1].status_code in {200, 429}
    if responses[-1].status_code == 429:
        assert responses[-1].headers["X-RateLimit-Limit"] == "2"


def test_bearer_access_token_is_used_for_user_rate_limit(monkeypatch):
    app = _build_app(monkeypatch, user_limit=2)
    client = TestClient(app)
    headers = {"Authorization": "Bearer header-token"}

    responses = [client.get("/private", headers=headers) for _ in range(3)]

    assert [response.status_code for response in responses] == [200, 200, 429]
    assert responses[0].headers["X-RateLimit-Limit"] == "2"


def test_bearer_access_token_is_used_for_llm_company_rate_limit(monkeypatch):
    app = _build_app(monkeypatch, user_limit=10, llm_limit=1)
    client = TestClient(app)
    headers = {"Authorization": "Bearer header-token"}

    first = client.post("/api/chat/", headers=headers)
    second = client.post("/api/chat/", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"] == "LLM调用过于频繁，请稍后再试"


def test_health_probe_is_not_rate_limited(monkeypatch):
    app = _build_app(monkeypatch, user_limit=1, ip_limit=2)
    client = TestClient(app)
    headers = {"Authorization": "Bearer header-token"}

    responses = [client.get("/health", headers=headers) for _ in range(4)]

    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    assert all("X-RateLimit-Limit" not in response.headers for response in responses)
