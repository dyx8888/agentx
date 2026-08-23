"""Secret-safe staging probe for the AgentX browser connector.

This probe validates externally observable connector deployment boundaries:
- HTTPS URL shape, unless --allow-http is used for local dry-runs.
- Credential-capable CORS for the configured AgentX frontend origin.
- CORS does not reflect an unconfigured origin.
- Connector status and ingest endpoints reject unauthenticated requests.
- Optional deployment manifest host permissions are narrow and include the backend origin.

It never accepts or prints real cookies, tokens, passwords, platform payloads, or API keys.
Authenticated browser capture, database row inspection, and real platform sample review remain
manual evidence steps in the browser connector runbook.

Usage:
    python tests/performance/browser_connector_staging_probe.py \
      --frontend https://app.example.com \
      --backend https://api.example.com \
      --manifest path/to/packaged/manifest.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = PROJECT_ROOT / "tests" / "reports" / "browser_connector_staging_probe.json"
CONNECTOR_VERSION_HEADER = "x-agentx-connector-version"
NEGATIVE_ORIGIN = "https://evil.example.com"


@dataclass
class ProbeResult:
    name: str
    target: str
    passed: bool
    status_code: int
    ms: float
    detail: str


def _base(url: str) -> str:
    return url.strip().rstrip("/")


def _path(base: str, path: str) -> str:
    return _base(base) + "/" + path.lstrip("/")


def _origin(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _request(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    started = time.perf_counter()
    req = Request(
        url,
        data=data,
        headers={
            "User-Agent": "agentx-browser-connector-staging-probe/1.0",
            **(headers or {}),
        },
        method=method,
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = int(response.status)
            response_headers = {key.lower(): value for key, value in response.headers.items()}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        status = int(exc.code)
        response_headers = {key.lower(): value for key, value in exc.headers.items()}
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return {"status_code": status, "body": body, "headers": response_headers, "ms": elapsed_ms}


def _network_failure(name: str, target: str, exc: BaseException) -> ProbeResult:
    return ProbeResult(name, target, False, 0, 0.0, f"request failed: {type(exc).__name__}")


def _scheme_check(name: str, url: str, allow_http: bool) -> ProbeResult:
    started = time.perf_counter()
    parsed = urlparse(url)
    passed = parsed.scheme == "https" or (allow_http and parsed.scheme == "http")
    detail = "HTTPS URL" if parsed.scheme == "https" else f"scheme is {parsed.scheme!r}"
    return ProbeResult(name, url, passed, 0, round((time.perf_counter() - started) * 1000, 2), detail)


def _safe_connector_payload() -> dict[str, Any]:
    return {
        "connector": {
            "source": "chrome-extension-mv3",
            "extension_id": "staging-probe",
            "version": "0.1.0",
            "mode": "readonly",
        },
        "page": {
            "url": "https://buyin.jinritemai.com/dashboard",
            "title": "AgentX connector staging probe",
            "referrer": None,
        },
        "api": {
            "url": "https://buyin.jinritemai.com/square_pc_api/square/search_feed_author",
            "method": "GET",
            "status_code": 200,
            "matched_rule": "buyin-api",
            "response_mime": "application/json",
            "captured_from": "fetch",
        },
        "data": {
            "kind": "json",
            "value": {"authors": [{"name": "probe-creator", "followers": 1}], "total": 1},
        },
        "policy": {
            "whitelist_rule": "buyin-api",
            "redaction_version": "v1",
            "contains_credentials": False,
            "contains_sensitive_fields": False,
            "platform_write_operation": False,
        },
        "captured_at": "2026-08-13T00:00:00Z",
    }


def check_cors_allows_frontend(backend_url: str, frontend_url: str, timeout: float) -> ProbeResult:
    url = _path(backend_url, "/api/browser-connector/ingest")
    origin = _origin(frontend_url)
    try:
        response = _request(
            url,
            method="OPTIONS",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": f"content-type,{CONNECTOR_VERSION_HEADER}",
            },
            timeout=timeout,
        )
    except (URLError, TimeoutError, OSError) as exc:
        return _network_failure("connector CORS allow frontend", url, exc)

    allow_origin = response["headers"].get("access-control-allow-origin", "")
    allow_credentials = response["headers"].get("access-control-allow-credentials", "").lower()
    allow_methods = response["headers"].get("access-control-allow-methods", "").upper()
    passed = (
        response["status_code"] in {200, 204}
        and allow_origin.rstrip("/") == origin.rstrip("/")
        and allow_credentials == "true"
        and "POST" in allow_methods
    )
    detail = (
        "configured frontend origin can credential POST"
        if passed
        else "expected exact allow-origin, allow-credentials=true, and POST"
    )
    return ProbeResult("connector CORS allow frontend", url, passed, response["status_code"], response["ms"], detail)


def check_cors_rejects_unknown_origin(backend_url: str, timeout: float) -> ProbeResult:
    url = _path(backend_url, "/api/browser-connector/ingest")
    try:
        response = _request(
            url,
            method="OPTIONS",
            headers={
                "Origin": NEGATIVE_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
            timeout=timeout,
        )
    except (URLError, TimeoutError, OSError) as exc:
        return _network_failure("connector CORS reject unknown origin", url, exc)

    allow_origin = response["headers"].get("access-control-allow-origin", "")
    passed = allow_origin.rstrip("/") != NEGATIVE_ORIGIN.rstrip("/")
    detail = "unknown origin was not reflected" if passed else "unknown origin was reflected"
    return ProbeResult(
        "connector CORS reject unknown origin",
        url,
        passed,
        response["status_code"],
        response["ms"],
        detail,
    )


def check_unauthenticated_status_rejected(backend_url: str, timeout: float) -> ProbeResult:
    url = _path(backend_url, "/api/browser-connector/status")
    try:
        response = _request(url, timeout=timeout)
    except (URLError, TimeoutError, OSError) as exc:
        return _network_failure("connector status requires auth", url, exc)

    passed = response["status_code"] in {401, 403}
    detail = "unauthenticated status request rejected" if passed else "expected 401/403 without login"
    return ProbeResult("connector status requires auth", url, passed, response["status_code"], response["ms"], detail)


def check_unauthenticated_ingest_rejected(backend_url: str, timeout: float) -> ProbeResult:
    url = _path(backend_url, "/api/browser-connector/ingest")
    data = json.dumps(_safe_connector_payload()).encode("utf-8")
    try:
        response = _request(
            url,
            method="POST",
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-AgentX-Connector-Version": "0.1.0",
            },
            timeout=timeout,
        )
    except (URLError, TimeoutError, OSError) as exc:
        return _network_failure("connector ingest requires auth", url, exc)

    passed = response["status_code"] in {401, 403}
    detail = "unauthenticated ingest request rejected" if passed else "expected 401/403 without login"
    return ProbeResult("connector ingest requires auth", url, passed, response["status_code"], response["ms"], detail)


def check_manifest_permissions(manifest_path: str, backend_url: str) -> list[ProbeResult]:
    started = time.perf_counter()
    path = Path(manifest_path)
    if not path.exists():
        return [
            ProbeResult(
                "deployment manifest exists",
                str(path),
                False,
                0,
                round((time.perf_counter() - started) * 1000, 2),
                "manifest path not found",
            )
        ]

    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [
            ProbeResult(
                "deployment manifest parses",
                str(path),
                False,
                0,
                round((time.perf_counter() - started) * 1000, 2),
                f"invalid JSON: {exc.__class__.__name__}",
            )
        ]

    host_permissions = manifest.get("host_permissions", [])
    content_matches: list[str] = []
    for item in manifest.get("content_scripts", []):
        if isinstance(item, dict):
            content_matches.extend(str(match) for match in item.get("matches", []))

    backend_origin = _origin(backend_url)
    backend_permission = f"{backend_origin}/*"
    broad_permissions = {"https://*/*", "http://*/*", "<all_urls>"}
    host_permissions_text = [str(item) for item in host_permissions]
    broad = sorted(set(host_permissions_text) & broad_permissions)
    has_backend = backend_permission in host_permissions_text
    has_content_scripts = bool(content_matches)
    has_platform_matches = any("jinritemai.com" in match or "douyin.com" in match for match in content_matches)
    elapsed = round((time.perf_counter() - started) * 1000, 2)

    return [
        ProbeResult(
            "deployment manifest backend permission",
            str(path),
            has_backend,
            0,
            elapsed,
            "backend origin permission present" if has_backend else f"missing {backend_permission}",
        ),
        ProbeResult(
            "deployment manifest host permissions narrow",
            str(path),
            not broad,
            0,
            elapsed,
            "no broad host permissions" if not broad else f"broad permissions: {', '.join(broad)}",
        ),
        ProbeResult(
            "deployment manifest platform matches",
            str(path),
            has_content_scripts and has_platform_matches,
            0,
            elapsed,
            "platform content script matches present" if has_platform_matches else "platform matches missing",
        ),
    ]


def run_probe(
    frontend_url: str,
    backend_url: str,
    *,
    manifest_path: str | None = None,
    allow_http: bool = False,
    timeout: float = 15.0,
) -> dict[str, Any]:
    frontend_url = _base(frontend_url)
    backend_url = _base(backend_url)
    results: list[ProbeResult] = [
        _scheme_check("frontend HTTPS", frontend_url, allow_http),
        _scheme_check("backend HTTPS", backend_url, allow_http),
        check_cors_allows_frontend(backend_url, frontend_url, timeout),
        check_cors_rejects_unknown_origin(backend_url, timeout),
        check_unauthenticated_status_rejected(backend_url, timeout),
        check_unauthenticated_ingest_rejected(backend_url, timeout),
    ]
    if manifest_path:
        results.extend(check_manifest_permissions(manifest_path, backend_url))

    failures = [result for result in results if not result.passed]
    return {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "frontend_url": frontend_url,
            "backend_url": backend_url,
            "manifest_path": manifest_path,
            "secret_values_redacted": True,
            "scope": (
                "browser connector staging HTTP/manifest probe; authenticated browser session, "
                "database row inspection, and real platform sample review remain manual evidence"
            ),
        },
        "summary": {
            "passed": not failures,
            "check_count": len(results),
            "failure_count": len(failures),
        },
        "checks": [asdict(result) for result in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend", required=True, help="AgentX frontend base URL")
    parser.add_argument("--backend", required=True, help="AgentX backend base URL")
    parser.add_argument("--manifest", default="", help="Optional packaged extension manifest path")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--allow-http", action="store_true", help="Allow http:// URLs for local dry-runs only")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    report = run_probe(
        args.frontend,
        args.backend,
        manifest_path=args.manifest or None,
        allow_http=args.allow_http,
        timeout=args.timeout,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("AgentX browser connector staging probe")
    print("=" * 80)
    print(f"passed: {report['summary']['passed']}")
    print(f"checks: {report['summary']['check_count']}  failures: {report['summary']['failure_count']}")
    for check in report["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        print(f"{status} {check['name']}: {check['detail']} ({check['status_code']})")
    print(f"JSON report: {out_path}")
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
