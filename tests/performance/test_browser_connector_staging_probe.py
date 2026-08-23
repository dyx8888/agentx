import json
from urllib.error import HTTPError

from tests.performance import browser_connector_staging_probe as probe


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


def _fake_success_urlopen(req, timeout):
    url = req.full_url
    method = req.get_method()
    if url == "https://api.example.com/api/browser-connector/ingest" and method == "OPTIONS":
        origin = req.headers.get("Origin")
        if origin == "https://app.example.com":
            return _Response(
                200,
                "",
                {
                    "access-control-allow-origin": "https://app.example.com",
                    "access-control-allow-credentials": "true",
                    "access-control-allow-methods": "GET, POST, OPTIONS",
                },
            )
        raise _http_error(url, 400, "", {"access-control-allow-credentials": "true"})
    if url == "https://api.example.com/api/browser-connector/status" and method == "GET":
        raise _http_error(url, 401, json.dumps({"detail": "Not authenticated"}))
    if url == "https://api.example.com/api/browser-connector/ingest" and method == "POST":
        raise _http_error(url, 401, json.dumps({"detail": "Not authenticated"}))
    raise AssertionError(url)


def test_browser_connector_staging_probe_passes_expected_contract(monkeypatch, tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "manifest_version": 3,
                "host_permissions": ["https://api.example.com/*"],
                "content_scripts": [
                    {
                        "matches": [
                            "https://buyin.jinritemai.com/*",
                            "https://www.douyin.com/*",
                        ],
                        "js": ["src/content-script.js"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(probe, "urlopen", _fake_success_urlopen)

    report = probe.run_probe(
        "https://app.example.com",
        "https://api.example.com",
        manifest_path=str(manifest),
    )

    assert report["summary"]["passed"] is True
    assert report["summary"]["failure_count"] == 0
    assert any(check["name"] == "connector ingest requires auth" for check in report["checks"])


def test_browser_connector_staging_probe_fails_when_cors_reflects_unknown_origin(monkeypatch):
    def fake_urlopen(req, timeout):
        url = req.full_url
        method = req.get_method()
        if url == "https://api.example.com/api/browser-connector/ingest" and method == "OPTIONS":
            return _Response(
                200,
                "",
                {
                    "access-control-allow-origin": req.headers.get("Origin", ""),
                    "access-control-allow-credentials": "true",
                    "access-control-allow-methods": "GET, POST, OPTIONS",
                },
            )
        if url == "https://api.example.com/api/browser-connector/status":
            raise _http_error(url, 401, "auth required")
        if url == "https://api.example.com/api/browser-connector/ingest" and method == "POST":
            raise _http_error(url, 401, "auth required")
        raise AssertionError(url)

    monkeypatch.setattr(probe, "urlopen", fake_urlopen)

    report = probe.run_probe("https://app.example.com", "https://api.example.com")
    failed = {check["name"] for check in report["checks"] if not check["passed"]}

    assert "connector CORS reject unknown origin" in failed


def test_browser_connector_staging_probe_fails_when_unauthenticated_ingest_succeeds(monkeypatch):
    def fake_urlopen(req, timeout):
        url = req.full_url
        method = req.get_method()
        if url == "https://api.example.com/api/browser-connector/ingest" and method == "OPTIONS":
            return _Response(
                200,
                "",
                {
                    "access-control-allow-origin": "https://app.example.com",
                    "access-control-allow-credentials": "true",
                    "access-control-allow-methods": "GET, POST, OPTIONS",
                },
            )
        if url == "https://api.example.com/api/browser-connector/status":
            raise _http_error(url, 401, "auth required")
        if url == "https://api.example.com/api/browser-connector/ingest" and method == "POST":
            return _Response(202, json.dumps({"accepted": True}))
        raise AssertionError(url)

    monkeypatch.setattr(probe, "urlopen", fake_urlopen)

    report = probe.run_probe("https://app.example.com", "https://api.example.com")
    failed = {check["name"] for check in report["checks"] if not check["passed"]}

    assert "connector ingest requires auth" in failed


def test_manifest_probe_rejects_broad_host_permissions(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "manifest_version": 3,
                "host_permissions": ["https://api.example.com/*", "https://*/*"],
                "content_scripts": [{"matches": ["https://buyin.jinritemai.com/*"], "js": []}],
            }
        ),
        encoding="utf-8",
    )

    results = probe.check_manifest_permissions(str(manifest), "https://api.example.com")
    failed = {result.name for result in results if not result.passed}

    assert "deployment manifest host permissions narrow" in failed


def test_manifest_probe_requires_backend_origin_permission(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "manifest_version": 3,
                "host_permissions": ["https://other.example.com/*"],
                "content_scripts": [{"matches": ["https://buyin.jinritemai.com/*"], "js": []}],
            }
        ),
        encoding="utf-8",
    )

    results = probe.check_manifest_permissions(str(manifest), "https://api.example.com")
    failed = {result.name for result in results if not result.passed}

    assert "deployment manifest backend permission" in failed
