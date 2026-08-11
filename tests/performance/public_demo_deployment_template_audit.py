"""Structured deployment-template audit for the AgentX public demo.

This audit checks the deployable templates that will be copied into Vercel,
Render, and provider secret stores. It intentionally avoids provider APIs and
never prints real secret values.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = PROJECT_ROOT / "tests" / "reports" / "public_demo_deployment_template_audit.json"


@dataclass
class AuditCheck:
    name: str
    passed: bool
    detail: str


TextReader = Callable[[str], str]


def read_text(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8", errors="replace")


def pass_check(name: str, detail: str) -> AuditCheck:
    return AuditCheck(name, True, detail)


def fail_check(name: str, detail: str) -> AuditCheck:
    return AuditCheck(name, False, detail)


def _clean(value: str) -> str:
    return value.strip().strip('"').strip("'")


def _line_has(text: str, key: str, value: str) -> bool:
    pattern = re.compile(rf"^\s*(?:-\s*)?{re.escape(key)}:\s*{re.escape(value)}\s*$", re.MULTILINE)
    return bool(pattern.search(text))


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = _clean(value)
    return values


def parse_render_env_vars(text: str) -> dict[str, dict[str, str]]:
    env: dict[str, dict[str, str]] = {}
    current_key: str | None = None
    for raw in text.splitlines():
        stripped = raw.strip()
        key_match = re.match(r"-\s*key:\s*([A-Za-z0-9_]+)\s*$", stripped)
        if key_match:
            current_key = key_match.group(1)
            env[current_key] = {}
            continue
        if not current_key:
            continue
        value_match = re.match(r"(value|sync):\s*(.+?)\s*$", stripped)
        if value_match:
            env[current_key][value_match.group(1)] = _clean(value_match.group(2))
    return env


def check_render_blueprint(read: TextReader) -> list[AuditCheck]:
    try:
        text = read("render.yaml")
    except OSError:
        return [fail_check("Render blueprint exists", "render.yaml missing")]

    required_lines = {
        "type": "web",
        "runtime": "python",
        "rootDir": ".",
        "buildCommand": "python -m pip install --upgrade pip && python -m pip install -r backend/requirements.txt",
        "startCommand": "PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port $PORT",
        "healthCheckPath": "/health",
        "autoDeploy": "false",
    }
    missing = [f"{key}: {value}" for key, value in required_lines.items() if not _line_has(text, key, value)]
    checks = [
        pass_check("Render blueprint service shape", "required service settings present")
        if not missing
        else fail_check("Render blueprint service shape", ", ".join(missing))
    ]

    env = parse_render_env_vars(text)
    required_values = {
        "ENVIRONMENT": "production",
        "ENV": "prod",
        "COOKIE_SECURE": "true",
        "ENABLE_PUBLIC_DOCS": "false",
        "ENABLE_EVOLUTION_API": "false",
    }
    bad_values = [
        f"{key}={env.get(key, {}).get('value', '<missing>')}"
        for key, expected in required_values.items()
        if env.get(key, {}).get("value") != expected
    ]
    checks.append(
        pass_check("Render blueprint production toggles", "production safety toggles are explicit")
        if not bad_values
        else fail_check("Render blueprint production toggles", ", ".join(bad_values))
    )

    externalized = (
        "DATABASE_URL",
        "JWT_SECRET_KEY",
        "FRONTEND_URL",
        "CORS_ORIGINS",
        "REDIS_URL",
        "MILVUS_HOST",
        "SMTP_HOST",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM",
        "OAUTH_REDIRECT_BASE_URL",
    )
    bad_externalized = [
        key
        for key in externalized
        if env.get(key, {}).get("sync") != "false" or "value" in env.get(key, {})
    ]
    checks.append(
        pass_check("Render blueprint externalized runtime values", "runtime URLs and secrets use sync:false")
        if not bad_externalized
        else fail_check("Render blueprint externalized runtime values", ", ".join(bad_externalized))
    )
    return checks


def check_vercel_config(read: TextReader) -> AuditCheck:
    try:
        data: dict[str, Any] = json.loads(read("frontend/vercel.json"))
    except (OSError, json.JSONDecodeError) as exc:
        return fail_check("Vercel config", f"frontend/vercel.json invalid: {type(exc).__name__}")

    expected = {
        "framework": "vite",
        "installCommand": "npm ci",
        "buildCommand": "npm run build",
        "outputDirectory": "dist",
    }
    mismatches = [key for key, value in expected.items() if data.get(key) != value]
    rewrites = data.get("rewrites", [])
    has_spa_rewrite = any(
        isinstance(rewrite, dict)
        and rewrite.get("source") == "/(.*)"
        and rewrite.get("destination") == "/index.html"
        for rewrite in rewrites
    )
    if mismatches or not has_spa_rewrite:
        return fail_check("Vercel config", ", ".join(mismatches + ([] if has_spa_rewrite else ["spa rewrite"])))
    return pass_check("Vercel config", "Vite build and SPA rewrite are configured")


def check_backend_env_template(read: TextReader) -> AuditCheck:
    try:
        env = parse_env(read("backend/.env.production.example"))
    except OSError:
        return fail_check("Backend production env template", "backend/.env.production.example missing")

    required = {
        "ENVIRONMENT": "production",
        "ENV": "prod",
        "COOKIE_SECURE": "true",
        "ENABLE_PUBLIC_DOCS": "false",
        "ENABLE_EVOLUTION_API": "false",
    }
    bad = [f"{key}={env.get(key, '<missing>')}" for key, value in required.items() if env.get(key) != value]
    if env.get("DATABASE_URL", None) != "":
        bad.append("DATABASE_URL is filled")
    if env.get("JWT_SECRET_KEY", None) != "":
        bad.append("JWT_SECRET_KEY is filled")
    if "*" in env.get("CORS_ORIGINS", ""):
        bad.append("CORS_ORIGINS contains wildcard")
    if bad:
        return fail_check("Backend production env template", ", ".join(bad))
    return pass_check("Backend production env template", "required production keys are safe placeholders")


def check_frontend_env_template(read: TextReader) -> AuditCheck:
    try:
        env = parse_env(read("frontend/.env.example"))
    except OSError:
        return fail_check("Frontend env template", "frontend/.env.example missing")

    bad: list[str] = []
    if env.get("VITE_API_BASE_URL") != "/api":
        bad.append("VITE_API_BASE_URL should default to /api")
    if env.get("VITE_DEMO_ENABLED") != "false":
        bad.append("VITE_DEMO_ENABLED should be false")
    if env.get("VITE_DEMO_PASSWORD", None) != "":
        bad.append("VITE_DEMO_PASSWORD should be blank")
    if bad:
        return fail_check("Frontend env template", ", ".join(bad))
    return pass_check("Frontend env template", "demo login is disabled and password is blank")


def run_audit(read: TextReader = read_text) -> dict:
    checks = [
        *check_render_blueprint(read),
        check_vercel_config(read),
        check_backend_env_template(read),
        check_frontend_env_template(read),
    ]
    failures = [check for check in checks if not check.passed]
    return {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "purpose": "public demo deployment template audit",
            "secret_values_redacted": True,
        },
        "summary": {
            "passed": not failures,
            "check_count": len(checks),
            "failure_count": len(failures),
        },
        "checks": [asdict(check) for check in checks],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    report = run_audit()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("AgentX public demo deployment template audit")
    print("=" * 80)
    print(f"passed: {report['summary']['passed']}")
    print(f"checks: {report['summary']['check_count']}  failures: {report['summary']['failure_count']}")
    for check in report["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        print(f"{status} {check['name']}: {check['detail']}")
    print(f"JSON report: {out_path}")
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
