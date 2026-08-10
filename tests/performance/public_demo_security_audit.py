"""Repository security audit for the AgentX public demo branch.

This audit is local-only and secret-safe. It checks tracked repository content
for public-demo blockers before a branch is pushed or deployed.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = PROJECT_ROOT / "tests" / "reports" / "public_demo_security_audit.json"

RUNTIME_ARTIFACT_PREFIXES = (
    "backend/data/",
    "reports/",
    "tests/reports/",
    "frontend/screenshots/",
    "perf_",
)
RUNTIME_ARTIFACT_EXACT_PATHS = {
    "backend/.coverage",
    "backend/data",
    "reports",
    "tests/reports",
    "frontend/screenshots",
}
FORBIDDEN_PUBLIC_DEMO_PREFIXES = (
    "frontend/test-results/",
)
FORBIDDEN_PUBLIC_DEMO_EXACT_PATHS = {
    "backend/app/evolution/suggester.py.bak",
    "backend/debug_agent.py",
    "backend/debug_chat_agent.py",
    "backend/debug_import.py",
    "backend/debug_tools.py",
    "backend/setup_test_agents.py",
    "backend/simple_chat_test.py",
    "backend/verify_startup.py",
    "frontend/test-output.txt",
}

ALLOWED_ENV_TEMPLATES = {
    "backend/.env.example",
    "backend/.env.production.example",
    "backend/config/.env.example",
    "frontend/.env.example",
}

PRODUCTION_TEMPLATE_REQUIRED_KEYS = {
    "ENVIRONMENT",
    "ENV",
    "DATABASE_URL",
    "JWT_SECRET_KEY",
    "FRONTEND_URL",
    "CORS_ORIGINS",
    "COOKIE_SECURE",
    "ENABLE_PUBLIC_DOCS",
    "ENABLE_EVOLUTION_API",
}

SENSITIVE_CONFIG_FILES = {
    "backend/.env.example",
    "backend/.env.production.example",
    "backend/config/.env.example",
    "backend/docker-compose.yml",
    "deploy/render.example.yaml",
    "frontend/.env.example",
}

NON_SECRET_KEYS = {
    "COOKIE_SECURE",
    "ENABLE_PUBLIC_DOCS",
    "ENABLE_EVOLUTION_API",
    "CORS_ORIGINS",
    "FRONTEND_URL",
    "ENV",
    "ENVIRONMENT",
    "MILVUS_HOST",
    "MILVUS_PORT",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_FROM",
    "OAUTH_REDIRECT_BASE_URL",
    "VITE_API_BASE_URL",
    "VITE_WS_BASE",
    "VITE_DEMO_ENABLED",
}

SENSITIVE_KEY_MARKERS = (
    "SECRET",
    "PASSWORD",
    "TOKEN",
    "API_KEY",
    "APP_KEY",
    "CLIENT_ID",
    "CLIENT_SECRET",
    "DATABASE_URL",
    "REDIS_URL",
)

PLACEHOLDER_MARKERS = (
    "your_",
    "your-",
    "replace-with",
    "example",
    "placeholder",
    "change-me",
    "local-only",
    "user:password",
    "<",
    ">",
    "${",
)

SECRET_PATTERNS = (
    r"AKIA[0-9A-Z]{16}",
    r"AIza[0-9A-Za-z_-]{35}",
    r"xox[baprs]-[0-9A-Za-z-]{10,}",
    r"ghp_[0-9A-Za-z]{36}",
    r"-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----",
)


@dataclass
class AuditCheck:
    name: str
    passed: bool
    detail: str


@dataclass
class GitResult:
    returncode: int
    stdout: str
    stderr: str


GitRunner = Callable[[list[str]], GitResult]
TextReader = Callable[[str], str]


def run_git(args: list[str]) -> GitResult:
    proc = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return GitResult(proc.returncode, proc.stdout.strip(), proc.stderr.strip())


def read_tracked_text(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8", errors="replace")


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def is_sensitive_key(key: str) -> bool:
    upper = key.strip().upper()
    if upper in NON_SECRET_KEYS:
        return False
    return any(marker in upper for marker in SENSITIVE_KEY_MARKERS)


def is_unfilled_placeholder(value: str) -> bool:
    normalized = value.strip().strip('"').strip("'")
    if normalized == "":
        return True
    lowered = normalized.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def is_allowed_local_service_value(key: str, value: str) -> bool:
    upper = key.strip().upper()
    normalized = value.strip().strip('"').strip("'").lower()
    if upper == "REDIS_URL":
        return bool(re.fullmatch(r"redis://(localhost|127\.0\.0\.1|redis):\d+(/\d+)?", normalized))
    return False


def list_tracked(git: GitRunner) -> list[str]:
    result = git(["ls-files"])
    if result.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def check_runtime_artifacts(tracked: list[str]) -> AuditCheck:
    found = [
        path
        for path in tracked
        if is_runtime_artifact_path(path)
    ]
    return AuditCheck(
        "runtime artifacts not tracked",
        not found,
        "0 tracked runtime artifact(s)" if not found else ", ".join(found[:20]),
    )


def is_runtime_artifact_path(path: str) -> bool:
    normalized = path.strip().replace("\\", "/")
    return normalized in RUNTIME_ARTIFACT_EXACT_PATHS or any(
        normalized.startswith(prefix) for prefix in RUNTIME_ARTIFACT_PREFIXES
    )


def is_forbidden_public_demo_path(path: str) -> bool:
    normalized = path.strip().replace("\\", "/")
    return (
        normalized in FORBIDDEN_PUBLIC_DEMO_EXACT_PATHS
        or normalized.endswith(".bak")
        or any(normalized.startswith(prefix) for prefix in FORBIDDEN_PUBLIC_DEMO_PREFIXES)
    )


def check_forbidden_public_demo_files(tracked: list[str]) -> AuditCheck:
    found = [path for path in tracked if is_forbidden_public_demo_path(path)]
    return AuditCheck(
        "debug and generated public-demo files not tracked",
        not found,
        "0 forbidden public-demo file(s)" if not found else ", ".join(found[:20]),
    )


def check_env_files(tracked: list[str]) -> AuditCheck:
    env_files = [
        path
        for path in tracked
        if Path(path).name == ".env" or Path(path).name.startswith(".env.")
    ]
    unexpected = [path for path in env_files if path not in ALLOWED_ENV_TEMPLATES]
    return AuditCheck(
        "only env templates tracked",
        not unexpected,
        "only .env example templates are tracked" if not unexpected else ", ".join(unexpected),
    )


def check_secret_patterns(tracked: list[str], read_text: TextReader) -> AuditCheck:
    patterns = [re.compile(pattern) for pattern in SECRET_PATTERNS]
    matches: list[str] = []
    for path in tracked:
        try:
            text = read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        if any(pattern.search(text) for pattern in patterns):
            matches.append(path)
    return AuditCheck(
        "high-confidence secret patterns",
        not matches,
        "0 high-confidence match(es)" if not matches else ", ".join(matches[:20]),
    )


def collect_env_style_assignments(path: str, text: str) -> list[tuple[str, str]]:
    assignments: list[tuple[str, str]] = []
    current_render_key: str | None = None

    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if path.endswith((".yml", ".yaml")):
            key_match = re.match(r"-?\s*key:\s*([A-Za-z0-9_]+)\s*$", stripped)
            if key_match:
                current_render_key = key_match.group(1)
                continue

            value_match = re.match(r"value:\s*(.+?)\s*$", stripped)
            if value_match and current_render_key:
                assignments.append((current_render_key, value_match.group(1)))
                continue

        assignment_match = re.match(r"-?\s*([A-Za-z0-9_]+)\s*[:=]\s*(.*?)\s*$", stripped)
        if assignment_match:
            assignments.append((assignment_match.group(1), assignment_match.group(2)))

    return assignments


def check_sensitive_config_placeholders(
    tracked: list[str],
    read_text: TextReader,
) -> AuditCheck:
    filled: list[str] = []
    for path in tracked:
        normalized_path = path.replace("\\", "/")
        if normalized_path not in SENSITIVE_CONFIG_FILES:
            continue
        try:
            text = read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        for key, value in collect_env_style_assignments(normalized_path, text):
            if (
                is_sensitive_key(key)
                and not is_unfilled_placeholder(value)
                and not is_allowed_local_service_value(key, value)
            ):
                filled.append(f"{normalized_path}:{key}")

    return AuditCheck(
        "sensitive config placeholders are not filled",
        not filled,
        "all sensitive config values are blank or placeholders" if not filled else ", ".join(filled[:20]),
    )


def check_production_template(read_text: TextReader) -> list[AuditCheck]:
    try:
        env = parse_env(read_text("backend/.env.production.example"))
    except OSError:
        return [AuditCheck("production env template exists", False, "backend/.env.production.example missing")]

    missing = sorted(PRODUCTION_TEMPLATE_REQUIRED_KEYS - set(env))
    checks = [
        AuditCheck(
            "production env template required keys",
            not missing,
            "all required keys present" if not missing else ", ".join(missing),
        ),
        AuditCheck(
            "production docs disabled by default",
            env.get("ENABLE_PUBLIC_DOCS", "").lower() == "false",
            f"ENABLE_PUBLIC_DOCS={env.get('ENABLE_PUBLIC_DOCS', '')!r}",
        ),
        AuditCheck(
            "production evolution api disabled by default",
            env.get("ENABLE_EVOLUTION_API", "").lower() == "false",
            f"ENABLE_EVOLUTION_API={env.get('ENABLE_EVOLUTION_API', '')!r}",
        ),
        AuditCheck(
            "production cookies secure",
            env.get("COOKIE_SECURE", "").lower() == "true",
            f"COOKIE_SECURE={env.get('COOKIE_SECURE', '')!r}",
        ),
        AuditCheck(
            "production CORS is explicit",
            bool(env.get("CORS_ORIGINS")) and "*" not in env.get("CORS_ORIGINS", ""),
            "CORS_ORIGINS is explicit and not wildcard",
        ),
        AuditCheck(
            "production secrets are not filled",
            env.get("JWT_SECRET_KEY", "") == "" and env.get("DATABASE_URL", "") == "",
            "JWT_SECRET_KEY and DATABASE_URL are blank placeholders",
        ),
    ]
    return checks


def check_frontend_template(read_text: TextReader) -> list[AuditCheck]:
    try:
        env = parse_env(read_text("frontend/.env.example"))
    except OSError:
        return [AuditCheck("frontend env template exists", False, "frontend/.env.example missing")]

    return [
        AuditCheck(
            "frontend demo login disabled by default",
            env.get("VITE_DEMO_ENABLED", "").lower() == "false",
            f"VITE_DEMO_ENABLED={env.get('VITE_DEMO_ENABLED', '')!r}",
        ),
        AuditCheck(
            "frontend demo password not filled",
            env.get("VITE_DEMO_PASSWORD", "") == "",
            "VITE_DEMO_PASSWORD is blank",
        ),
    ]


def run_audit(git: GitRunner = run_git, read_text: TextReader = read_tracked_text) -> dict:
    tracked = list_tracked(git)
    checks = [
        check_runtime_artifacts(tracked),
        check_forbidden_public_demo_files(tracked),
        check_env_files(tracked),
        check_secret_patterns(tracked, read_text),
        check_sensitive_config_placeholders(tracked, read_text),
        *check_production_template(read_text),
        *check_frontend_template(read_text),
    ]
    failures = [check for check in checks if not check.passed]
    return {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "purpose": "local repository security audit for public demo readiness",
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

    print("AgentX public demo security audit")
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
