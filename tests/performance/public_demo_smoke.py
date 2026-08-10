"""Secret-safe public demo smoke checker for AgentX.

The checker is intentionally small and conservative:
- It never accepts or prints real account credentials.
- It verifies public HTTPS reachability, backend health, auth failure behavior,
  CORS, public docs exposure, and core SPA route shell delivery.
- It records JSON evidence that can be attached to the public smoke document.

Usage:
    python tests/performance/public_demo_smoke.py --frontend https://app.example.com --backend https://api.example.com
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
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = PROJECT_ROOT / "tests" / "reports" / "public_demo_smoke.json"


@dataclass
class ProbeResult:
    name: str
    url: str
    passed: bool
    status_code: int
    ms: float
    detail: str


def _base(url: str) -> str:
    return url.strip().rstrip("/")


def _path(base: str, path: str) -> str:
    return _base(base) + "/" + path.lstrip("/")


def _scheme_check(name: str, url: str, allow_http: bool) -> ProbeResult:
    started = time.perf_counter()
    parsed = urlparse(url)
    passed = parsed.scheme == "https" or (allow_http and parsed.scheme == "http")
    detail = "HTTPS URL" if parsed.scheme == "https" else f"scheme is {parsed.scheme!r}"
    return ProbeResult(name, url, passed, 0, round((time.perf_counter() - started) * 1000, 2), detail)


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
            "User-Agent": "agentx-public-demo-smoke/1.0",
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


def _network_failure(name: str, url: str, exc: BaseException) -> ProbeResult:
    return ProbeResult(name, url, False, 0, 0.0, f"request failed: {type(exc).__name__}")


def check_frontend_shell(frontend_url: str, path: str, timeout: float) -> ProbeResult:
    url = _path(frontend_url, path)
    try:
        response = _request(url, timeout=timeout)
    except (URLError, TimeoutError, OSError) as exc:
        return _network_failure(f"frontend {path}", url, exc)

    body = response["body"].strip().lower()
    passed = response["status_code"] == 200 and ("<html" in body or "<!doctype html" in body)
    detail = "HTML shell returned" if passed else "expected HTTP 200 HTML shell"
    return ProbeResult(f"frontend {path}", url, passed, response["status_code"], response["ms"], detail)


def check_backend_health(backend_url: str, timeout: float) -> ProbeResult:
    url = _path(backend_url, "/health")
    try:
        response = _request(url, timeout=timeout)
    except (URLError, TimeoutError, OSError) as exc:
        return _network_failure("backend /health", url, exc)

    detail = "health JSON returned"
    passed = False
    try:
        body = json.loads(response["body"])
        status = body.get("overall") or body.get("status")
        passed = response["status_code"] == 200 and status in {"healthy", "degraded"}
        if not passed:
            detail = f"health status is {status!r}"
    except json.JSONDecodeError:
        detail = "health response is not JSON"
    return ProbeResult("backend /health", url, passed, response["status_code"], response["ms"], detail)


def check_auth_failure(backend_url: str, timeout: float) -> ProbeResult:
    url = _path(backend_url, "/api/auth/token")
    form = urlencode(
        {
            "username": "__agentx_public_smoke_invalid__",
            "password": "__invalid_public_smoke_password__",
        }
    ).encode("utf-8")
    try:
        response = _request(
            url,
            method="POST",
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
        )
    except (URLError, TimeoutError, OSError) as exc:
        return _network_failure("auth invalid login", url, exc)

    passed = response["status_code"] in {400, 401, 403} and bool(response["body"].strip())
    detail = "invalid credentials returned clear auth error" if passed else "expected 400/401/403 with error body"
    return ProbeResult("auth invalid login", url, passed, response["status_code"], response["ms"], detail)


def check_docs_disabled(backend_url: str, timeout: float) -> list[ProbeResult]:
    results: list[ProbeResult] = []
    for path in ("/docs", "/openapi.json"):
        url = _path(backend_url, path)
        try:
            response = _request(url, timeout=timeout)
        except (URLError, TimeoutError, OSError) as exc:
            results.append(_network_failure(f"public docs {path}", url, exc))
            continue
        passed = response["status_code"] in {401, 403, 404}
        detail = "not publicly exposed" if passed else "expected docs/openapi to be disabled publicly"
        results.append(ProbeResult(f"public docs {path}", url, passed, response["status_code"], response["ms"], detail))
    return results


def check_cors(backend_url: str, frontend_url: str, timeout: float) -> ProbeResult:
    url = _path(backend_url, "/api/auth/users/me")
    origin = _base(frontend_url)
    try:
        response = _request(
            url,
            method="OPTIONS",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
            timeout=timeout,
        )
    except (URLError, TimeoutError, OSError) as exc:
        return _network_failure("CORS preflight", url, exc)

    allow_origin = response["headers"].get("access-control-allow-origin", "")
    passed = response["status_code"] in {200, 204} and allow_origin.rstrip("/") == origin.rstrip("/")
    detail = "CORS allows configured frontend origin" if passed else "frontend origin not allowed by CORS"
    return ProbeResult("CORS preflight", url, passed, response["status_code"], response["ms"], detail)


def run_smoke(frontend_url: str, backend_url: str, *, allow_http: bool = False, timeout: float = 15.0) -> dict[str, Any]:
    frontend_url = _base(frontend_url)
    backend_url = _base(backend_url)
    results: list[ProbeResult] = [
        _scheme_check("frontend HTTPS", frontend_url, allow_http),
        _scheme_check("backend HTTPS", backend_url, allow_http),
        check_frontend_shell(frontend_url, "/", timeout),
        check_frontend_shell(frontend_url, "/login", timeout),
        check_frontend_shell(frontend_url, "/settings", timeout),
        check_backend_health(backend_url, timeout),
        check_auth_failure(backend_url, timeout),
        check_cors(backend_url, frontend_url, timeout),
        *check_docs_disabled(backend_url, timeout),
    ]
    failures = [result for result in results if not result.passed]
    return {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "frontend_url": frontend_url,
            "backend_url": backend_url,
            "secret_values_redacted": True,
            "scope": "public demo HTTP smoke; authenticated browser screenshots remain a separate manual evidence step",
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
    parser.add_argument("--frontend", required=True, help="Public frontend base URL")
    parser.add_argument("--backend", required=True, help="Public backend base URL")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--allow-http", action="store_true", help="Allow http:// URLs for local dry-runs only")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    report = run_smoke(args.frontend, args.backend, allow_http=args.allow_http, timeout=args.timeout)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("AgentX public demo smoke")
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
