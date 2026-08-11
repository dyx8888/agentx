"""Cloud prerequisite audit for the AgentX public demo.

This audit is intentionally local-only. It checks whether this machine has the
minimum tooling or environment variables needed to move from a verified public
demo branch to hosted Vercel, Render, and Neon resources. It does not call
provider APIs and it never prints secret values.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = PROJECT_ROOT / "tests" / "reports" / "public_demo_cloud_prereq_audit.json"


CommandExists = Callable[[str], bool]
EnvGet = Callable[[str], str | None]


@dataclass
class CloudPrereqCheck:
    name: str
    status: str
    detail: str


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def env_get(name: str) -> str | None:
    return os.environ.get(name)


def pass_check(name: str, detail: str) -> CloudPrereqCheck:
    return CloudPrereqCheck(name, "pass", detail)


def fail_check(name: str, detail: str) -> CloudPrereqCheck:
    return CloudPrereqCheck(name, "fail", detail)


def pending_check(name: str, detail: str) -> CloudPrereqCheck:
    return CloudPrereqCheck(name, "pending_external", detail)


def _is_set(value: str | None) -> bool:
    return bool(value and value.strip())


def _set_state(get_env: EnvGet, name: str) -> str:
    return "SET" if _is_set(get_env(name)) else "NOT_SET"


def check_vercel_access(has_command: CommandExists, get_env: EnvGet) -> CloudPrereqCheck:
    if has_command("vercel") or _is_set(get_env("VERCEL_TOKEN")):
        return pass_check("Vercel access", "vercel CLI or VERCEL_TOKEN is available")
    return pending_check("Vercel access", "vercel CLI and VERCEL_TOKEN are not available")


def check_render_access(has_command: CommandExists, get_env: EnvGet) -> CloudPrereqCheck:
    if has_command("render") or _is_set(get_env("RENDER_API_KEY")):
        return pass_check("Render access", "render CLI or RENDER_API_KEY is available")
    return pending_check("Render access", "render CLI and RENDER_API_KEY are not available")


def check_neon_access(has_command: CommandExists, get_env: EnvGet) -> CloudPrereqCheck:
    if has_command("neon") or _is_set(get_env("NEON_API_KEY")) or _is_set(get_env("DATABASE_URL")):
        return pass_check("Managed Postgres access", "neon CLI, NEON_API_KEY, or DATABASE_URL is available")
    return pending_check("Managed Postgres access", "neon CLI, NEON_API_KEY, and DATABASE_URL are not available")


def check_runtime_env(get_env: EnvGet) -> CloudPrereqCheck:
    required = ("DATABASE_URL", "JWT_SECRET_KEY", "FRONTEND_URL", "CORS_ORIGINS")
    missing = [name for name in required if not _is_set(get_env(name))]
    if missing:
        return pending_check("Production runtime env", "missing " + ", ".join(missing))

    cors = get_env("CORS_ORIGINS") or ""
    frontend = get_env("FRONTEND_URL") or ""
    if "*" in cors:
        return fail_check("Production runtime env", "CORS_ORIGINS contains wildcard")
    if not frontend.startswith("https://"):
        return fail_check("Production runtime env", "FRONTEND_URL must be https")
    if not cors.startswith("https://"):
        return fail_check("Production runtime env", "CORS_ORIGINS must be https")
    return pass_check("Production runtime env", "required production variables are present and non-secret values are safe")


def run_audit(
    *,
    has_command: CommandExists = command_exists,
    get_env: EnvGet = env_get,
) -> dict:
    checks = [
        check_vercel_access(has_command, get_env),
        check_render_access(has_command, get_env),
        check_neon_access(has_command, get_env),
        check_runtime_env(get_env),
    ]
    failures = [check for check in checks if check.status == "fail"]
    pending = [check for check in checks if check.status == "pending_external"]
    return {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "purpose": "public demo cloud prerequisite audit",
            "secret_values_redacted": True,
            "provider_api_calls": False,
        },
        "summary": {
            "ready_for_automated_cloud_deploy": not failures and not pending,
            "check_count": len(checks),
            "failure_count": len(failures),
            "pending_external_count": len(pending),
            "env_state": {
                name: _set_state(get_env, name)
                for name in (
                    "VERCEL_TOKEN",
                    "RENDER_API_KEY",
                    "NEON_API_KEY",
                    "DATABASE_URL",
                    "JWT_SECRET_KEY",
                    "FRONTEND_URL",
                    "CORS_ORIGINS",
                )
            },
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

    print("AgentX public demo cloud prerequisite audit")
    print("=" * 80)
    print(f"ready_for_automated_cloud_deploy: {report['summary']['ready_for_automated_cloud_deploy']}")
    print(
        "checks: "
        f"{report['summary']['check_count']}  "
        f"failures: {report['summary']['failure_count']}  "
        f"pending_external: {report['summary']['pending_external_count']}"
    )
    for check in report["checks"]:
        print(f"{check['status'].upper()} {check['name']}: {check['detail']}")
    print(f"env_state: {json.dumps(report['summary']['env_state'], sort_keys=True)}")
    print(f"JSON report: {out_path}")
    return 0 if not report["summary"]["failure_count"] else 1


if __name__ == "__main__":
    sys.exit(main())
