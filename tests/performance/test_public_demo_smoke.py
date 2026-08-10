import json
from urllib.error import HTTPError

from tests.performance import public_demo_smoke as smoke


class _Headers(dict):
    def items(self):
        return super().items()


class _Response:
    def __init__(self, status=200, body="", headers=None):
        self.status = status
        self._body = body.encode("utf-8")
        self.headers = _Headers(headers or {})

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body

    def close(self):
        return None


def _http_error(url, status, body="", headers=None):
    return HTTPError(url, status, "error", _Headers(headers or {}), _Response(status, body, headers))


def test_public_demo_smoke_passes_for_expected_public_contract(monkeypatch):
    def fake_urlopen(req, timeout):
        url = req.full_url
        method = req.get_method()
        if url in {"https://app.example.com/", "https://app.example.com/login", "https://app.example.com/settings"}:
            return _Response(200, "<!doctype html><html><body>AgentX</body></html>")
        if url == "https://api.example.com/health":
            return _Response(200, json.dumps({"overall": "healthy", "database": {"status": "healthy"}}))
        if url == "https://api.example.com/api/auth/token":
            raise _http_error(url, 401, json.dumps({"detail": "Incorrect username or password"}))
        if url == "https://api.example.com/api/auth/users/me" and method == "OPTIONS":
            return _Response(200, "", {"access-control-allow-origin": "https://app.example.com"})
        if url in {"https://api.example.com/docs", "https://api.example.com/openapi.json"}:
            raise _http_error(url, 404, "not found")
        raise AssertionError(url)

    monkeypatch.setattr(smoke, "urlopen", fake_urlopen)

    report = smoke.run_smoke("https://app.example.com", "https://api.example.com")

    assert report["summary"]["passed"] is True
    assert report["summary"]["failure_count"] == 0
    assert any(check["name"] == "frontend /settings" for check in report["checks"])


def test_public_demo_smoke_rejects_http_without_override(monkeypatch):
    monkeypatch.setattr(smoke, "urlopen", lambda *_args, **_kwargs: _Response(200, "<html></html>"))

    report = smoke.run_smoke("http://app.example.com", "https://api.example.com")
    failed = {check["name"] for check in report["checks"] if not check["passed"]}

    assert "frontend HTTPS" in failed


def test_public_demo_smoke_fails_when_docs_are_public(monkeypatch):
    def fake_urlopen(req, timeout):
        url = req.full_url
        method = req.get_method()
        if url in {"https://app.example.com/", "https://app.example.com/login", "https://app.example.com/settings"}:
            return _Response(200, "<html></html>")
        if url == "https://api.example.com/health":
            return _Response(200, json.dumps({"overall": "healthy", "database": {"status": "healthy"}}))
        if url == "https://api.example.com/api/auth/token":
            raise _http_error(url, 401, "bad credentials")
        if url == "https://api.example.com/api/auth/users/me" and method == "OPTIONS":
            return _Response(200, "", {"access-control-allow-origin": "https://app.example.com"})
        if url in {"https://api.example.com/docs", "https://api.example.com/openapi.json"}:
            return _Response(200, "<html>Swagger UI</html>")
        raise AssertionError(url)

    monkeypatch.setattr(smoke, "urlopen", fake_urlopen)

    report = smoke.run_smoke("https://app.example.com", "https://api.example.com")
    failed = {check["name"] for check in report["checks"] if not check["passed"]}

    assert "public docs /docs" in failed
    assert "public docs /openapi.json" in failed


def test_public_demo_smoke_fails_on_cors_mismatch(monkeypatch):
    def fake_urlopen(req, timeout):
        url = req.full_url
        method = req.get_method()
        if url in {"https://app.example.com/", "https://app.example.com/login", "https://app.example.com/settings"}:
            return _Response(200, "<html></html>")
        if url == "https://api.example.com/health":
            return _Response(200, json.dumps({"overall": "healthy", "database": {"status": "healthy"}}))
        if url == "https://api.example.com/api/auth/token":
            raise _http_error(url, 401, "bad credentials")
        if url == "https://api.example.com/api/auth/users/me" and method == "OPTIONS":
            return _Response(200, "", {"access-control-allow-origin": "https://other.example.com"})
        if url in {"https://api.example.com/docs", "https://api.example.com/openapi.json"}:
            raise _http_error(url, 404, "not found")
        raise AssertionError(url)

    monkeypatch.setattr(smoke, "urlopen", fake_urlopen)

    report = smoke.run_smoke("https://app.example.com", "https://api.example.com")
    failed = {check["name"] for check in report["checks"] if not check["passed"]}

    assert "CORS preflight" in failed


def test_public_demo_smoke_fails_when_settings_route_is_not_rewritten(monkeypatch):
    def fake_urlopen(req, timeout):
        url = req.full_url
        method = req.get_method()
        if url in {"https://app.example.com/", "https://app.example.com/login"}:
            return _Response(200, "<html></html>")
        if url == "https://app.example.com/settings":
            raise _http_error(url, 404, "not found")
        if url == "https://api.example.com/health":
            return _Response(200, json.dumps({"overall": "healthy", "database": {"status": "healthy"}}))
        if url == "https://api.example.com/api/auth/token":
            raise _http_error(url, 401, "bad credentials")
        if url == "https://api.example.com/api/auth/users/me" and method == "OPTIONS":
            return _Response(200, "", {"access-control-allow-origin": "https://app.example.com"})
        if url in {"https://api.example.com/docs", "https://api.example.com/openapi.json"}:
            raise _http_error(url, 404, "not found")
        raise AssertionError(url)

    monkeypatch.setattr(smoke, "urlopen", fake_urlopen)

    report = smoke.run_smoke("https://app.example.com", "https://api.example.com")
    failed = {check["name"] for check in report["checks"] if not check["passed"]}

    assert "frontend /settings" in failed
