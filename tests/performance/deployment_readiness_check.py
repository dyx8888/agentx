"""Deployment readiness checker for AgentX.

The checker is intentionally conservative and secret-safe:
- It never prints environment variable values.
- It flags placeholder/default/fallback-looking values by key name only.
- It can also probe a running backend /ready endpoint.

Usage:
    python tests/performance/deployment_readiness_check.py --env-file backend/.env.production --target local-docker --base http://127.0.0.1:8000
    python tests/performance/deployment_readiness_check.py --env-file backend/.env.production --target cloud --base https://api.example.com
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = PROJECT_ROOT / "tests" / "reports" / "deployment_readiness_check.json"

REQUIRED_KEYS = (
    "ENV",
    "JWT_SECRET_KEY",
    "ENCRYPTION_KEY",
    "CORS_ORIGINS",
    "DATABASE_URL",
    "REDIS_URL",
    "VECTOR_DB",
    "MILVUS_HOST",
    "MILVUS_PORT",
    "MILVUS_COLLECTION",
)

RECOMMENDED_KEYS = (
    "FRONTEND_URL",
    "COOKIE_SECURE",
    "ALLOW_PLATFORM_MOCK_FALLBACK",
    "ALLOW_ENTERPRISE_MOCK_INTEGRATIONS",
    "LOG_TO_FILE",
    "LOG_MAX_BYTES",
    "LOG_BACKUP_COUNT",
    "EMBEDDING_MODE",
    "GRAPH_RAG_DYNAMIC_EXTRACTION_MODE",
)

SECRET_KEYS = (
    "JWT_SECRET_KEY",
    "ENCRYPTION_KEY",
    "TOKENRHYTHM_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "EMBEDDING_API_KEY",
    "SMTP_PASSWORD",
    "DOUYIN_STAR_API_KEY",
    "DOUYIN_STAR_API_SECRET",
)

MODEL_API_KEY_BY_MODEL = {
    "deepseek": "DEEPSEEK_API_KEY",
    "deepseek-chat": "DEEPSEEK_API_KEY",
    "deepseek_reasoner": "DEEPSEEK_API_KEY",
    "glm52": "TOKENRHYTHM_API_KEY",
    "tokenrhythm": "TOKENRHYTHM_API_KEY",
}

PLACEHOLDER_RE = re.compile(
    r"(<[^>]+>|your-|changeme|change-me|default|example\.com|your-domain|user:pass)",
    re.IGNORECASE,
)


def parse_env_file(path: Path) -> tuple[dict[str, str], dict[str, int]]:
    values: dict[str, str] = {}
    counts: dict[str, int] = {}
    if not path.exists():
        return values, counts

    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        counts[key] = counts.get(key, 0) + 1
        values[key] = value.strip().strip('"').strip("'")
    return values, counts


def add_issue(issues: list[dict[str, str]], severity: str, key: str, message: str) -> None:
    issues.append({"severity": severity, "key": key, "message": message})


def looks_placeholder(value: str) -> bool:
    return not value or bool(PLACEHOLDER_RE.search(value))


def detect_runtime_secret_names() -> set[str]:
    """Return secret names present in the current process without reading values."""
    return {key for key in SECRET_KEYS if os.getenv(key)}


def configured_model_key(values: dict[str, str]) -> str:
    """Resolve the model key the backend/evaluation path will try first."""
    return (
        values.get("MODEL_GATEWAY_DEFAULT")
        or values.get("AGENT_EVAL_MODEL")
        or values.get("EVALUATION_MODEL")
        or "deepseek"
    ).strip()


def check_env(
    values: dict[str, str],
    counts: dict[str, int],
    target: str,
    runtime_secrets: set[str] | None = None,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    runtime_secrets = runtime_secrets or set()

    for key, count in sorted(counts.items()):
        if count > 1:
            add_issue(issues, "P1", key, f"duplicate environment variable name ({count} entries)")

    for key in REQUIRED_KEYS:
        value = values.get(key, "")
        if key in SECRET_KEYS and key in runtime_secrets and not value:
            continue
        if not value:
            add_issue(issues, "P0", key, "missing required production variable")
        elif looks_placeholder(value):
            add_issue(issues, "P0", key, "value looks like a placeholder/default")

    model_key = configured_model_key(values)
    model_api_key = MODEL_API_KEY_BY_MODEL.get(model_key, "DEEPSEEK_API_KEY")
    model_api_value = values.get(model_api_key, "")
    if model_api_key in runtime_secrets and not model_api_value:
        pass
    elif not model_api_value:
        add_issue(
            issues,
            "P0",
            model_api_key,
            f"missing API key for configured model '{model_key}'",
        )
    elif looks_placeholder(model_api_value):
        add_issue(
            issues,
            "P0",
            model_api_key,
            f"API key for configured model '{model_key}' looks like a placeholder/default",
        )

    for key in RECOMMENDED_KEYS:
        if not values.get(key, ""):
            add_issue(issues, "P2", key, "recommended variable is not set")

    env = values.get("ENV", "").lower()
    if env != "prod":
        add_issue(issues, "P0", "ENV", "production deployment should use ENV=prod")

    cors = values.get("CORS_ORIGINS", "")
    if "*" in cors:
        add_issue(issues, "P0", "CORS_ORIGINS", 'production CORS must not include "*"')

    database_url = values.get("DATABASE_URL", "").lower()
    if database_url and not database_url.startswith("postgresql"):
        add_issue(issues, "P0", "DATABASE_URL", "production database should be PostgreSQL")
    if "sqlite" in database_url:
        add_issue(issues, "P0", "DATABASE_URL", "SQLite is a fallback/development database")

    vector_db = values.get("VECTOR_DB", "").lower()
    if vector_db != "milvus":
        add_issue(issues, "P0", "VECTOR_DB", "production RAG validation expects VECTOR_DB=milvus")

    if values.get("ALLOW_PLATFORM_MOCK_FALLBACK", "").lower() != "false":
        add_issue(
            issues,
            "P0",
            "ALLOW_PLATFORM_MOCK_FALLBACK",
            "production must not silently use mock/demo platform data",
        )
    if values.get("ALLOW_ENTERPRISE_MOCK_INTEGRATIONS", "").lower() != "false":
        add_issue(
            issues,
            "P0",
            "ALLOW_ENTERPRISE_MOCK_INTEGRATIONS",
            "production must not silently use mock ERP/WMS/customer-service data",
        )

    if target == "cloud":
        local_like = {"localhost", "127.0.0.1", "host.docker.internal"}
        for key in ("MILVUS_HOST", "REDIS_URL", "DATABASE_URL"):
            value = values.get(key, "").lower()
            if any(token in value for token in local_like):
                add_issue(issues, "P1", key, "cloud deployment should not point to localhost")

    cookie_secure = values.get("COOKIE_SECURE", "").lower()
    if target == "cloud" and cookie_secure != "true":
        add_issue(issues, "P1", "COOKIE_SECURE", "HTTPS cloud deployment should use secure cookies")

    if target == "cloud":
        for key in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"):
            value = values.get(key, "")
            if key in SECRET_KEYS and key in runtime_secrets and not value:
                continue
            if not value:
                add_issue(issues, "P0", key, "cloud password reset email requires real SMTP configuration")
            elif looks_placeholder(value):
                add_issue(issues, "P0", key, "SMTP configuration looks like a placeholder/default")

        smtp_host = values.get("SMTP_HOST", "").lower()
        smtp_port = values.get("SMTP_PORT", "")
        if "mailhog" in smtp_host or "localhost" in smtp_host or smtp_host == "127.0.0.1" or smtp_port == "1025":
            add_issue(issues, "P0", "SMTP_HOST", "cloud password reset email must not use MailHog or local SMTP")

    for key in SECRET_KEYS:
        value = values.get(key, "")
        if value and len(value) < 16:
            add_issue(issues, "P1", key, "secret-looking variable is unusually short")

    return issues


def probe_health(base: str, timeout: float) -> dict[str, Any]:
    """Probe the strict readiness endpoint and preserve non-200 response bodies."""
    url = base.rstrip("/") + "/ready"
    started = time.perf_counter()
    status_code = 0
    try:
        with urlopen(url, timeout=timeout) as response:
            status_code = response.status
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        status_code = exc.code
        body = exc.read().decode("utf-8")
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    parsed = json.loads(body)
    return {"url": url, "status_code": status_code, "ms": elapsed_ms, "body": parsed}


def check_health(health: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    body = health.get("body", {})
    env = body.get("environment", {}) if isinstance(body, dict) else {}
    if health.get("status_code") != 200:
        add_issue(issues, "P0", "/ready", f"status code is {health.get('status_code')!r}")
    if body.get("ready") is not True:
        add_issue(issues, "P0", "/ready", f"ready is {body.get('ready')!r}")
    if body.get("overall") != "healthy":
        add_issue(issues, "P0", "/ready", f"overall is {body.get('overall')!r}")
    if body.get("database", {}).get("status") != "healthy":
        add_issue(issues, "P0", "database", "database is not healthy")
    if body.get("redis", {}).get("status") != "healthy":
        add_issue(issues, "P0", "redis", "redis is not healthy")
    if body.get("milvus", {}).get("status") != "healthy":
        add_issue(issues, "P0", "milvus", "milvus is not healthy")
    if body.get("chat_agent", {}).get("status") != "ready":
        add_issue(issues, "P0", "chat_agent", "chat runtime is not ready")
    if env.get("vector_db") != "milvus" or not env.get("milvus_configured"):
        add_issue(issues, "P0", "vector_db", "readiness endpoint does not prove Milvus mode")
    return issues


def summarize(issues: list[dict[str, str]]) -> dict[str, Any]:
    p0 = [i for i in issues if i["severity"] == "P0"]
    p1 = [i for i in issues if i["severity"] == "P1"]
    p2 = [i for i in issues if i["severity"] == "P2"]
    return {
        "passed": not p0,
        "p0_count": len(p0),
        "p1_count": len(p1),
        "p2_count": len(p2),
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default="backend/.env.production")
    parser.add_argument("--target", choices=["local-docker", "cloud"], default="cloud")
    parser.add_argument("--base", default="", help="Optional backend base URL to probe /ready")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument(
        "--runtime-secret",
        action="append",
        default=[],
        help=(
            "Secret variable name supplied by the runtime/deployment platform "
            "instead of the env file. The value is never read or printed."
        ),
    )
    args = parser.parse_args()

    env_path = Path(args.env_file)
    values, counts = parse_env_file(env_path)
    runtime_secrets = detect_runtime_secret_names() | {
        str(name).strip() for name in args.runtime_secret if str(name).strip()
    }
    issues = check_env(values, counts, args.target, runtime_secrets=runtime_secrets)
    health: dict[str, Any] | None = None

    if args.base:
        try:
            health = probe_health(args.base, args.timeout)
            issues.extend(check_health(health))
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            add_issue(issues, "P0", "/ready", f"readiness probe failed: {type(exc).__name__}")

    summary = summarize(issues)
    report = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "purpose": "secret-safe deployment readiness check",
            "env_file": str(env_path),
            "target": args.target,
            "base": args.base,
        },
        "summary": summary,
        "health": health,
        "checked_keys": {
            "required": list(REQUIRED_KEYS),
            "recommended": list(RECOMMENDED_KEYS),
            "configured_model": configured_model_key(values),
            "model_api_key_required": MODEL_API_KEY_BY_MODEL.get(
                configured_model_key(values), "DEEPSEEK_API_KEY"
            ),
            "runtime_secret_names": sorted(runtime_secrets),
            "secret_values_redacted": True,
        },
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Deployment readiness check")
    print("=" * 80)
    print(f"passed: {summary['passed']}")
    print(f"P0: {summary['p0_count']}  P1: {summary['p1_count']}  P2: {summary['p2_count']}")
    for issue in issues:
        print(f"{issue['severity']} {issue['key']}: {issue['message']}")
    print(f"JSON report: {out_path}")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
