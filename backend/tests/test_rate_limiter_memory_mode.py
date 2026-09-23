from app.middleware.rate_limiter import setup_rate_limiter


def test_rate_limiter_without_redis_uses_direct_memory_mode(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("RATE_LIMIT_REDIS_URL", raising=False)

    class App:
        def __init__(self):
            self.middleware = None

        def add_middleware(self, middleware, **kwargs):
            self.middleware = (middleware, kwargs)

    app = App()
    setup_rate_limiter(app)

    assert app.middleware[1]["redis_client"] is None
