"""Completion boundary audit for the AgentX public demo.

This audit separates local demo readiness from public completion. It should
pass when the display branch is locally clean, reviewable, and safe to push,
while still reporting hosted-demo requirements as pending until real public
URLs and cloud resources exist.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = PROJECT_ROOT / "tests" / "reports" / "public_demo_completion_audit.json"

REQUIRED_TRACKED_FILES = {
    ".github/workflows/public-demo-quick-gates.yml",
    "README.md",
    "backend/.env.production.example",
    "deploy/render.example.yaml",
    "docs/db-migration-readiness-2026-08-11.md",
    "docs/deferred-worktree-triage-2026-08-11.md",
    "docs/demo-data/README.md",
    "docs/demo-data/knowledge_demo_seed.csv",
    "docs/demo-data/kol_demo_seed.csv",
    "docs/interview-demo-guide-2026-08-11.md",
    "docs/public-demo-deployment-plan-2026-08-11.md",
    "docs/public-demo-deployment-runbook-2026-08-11.md",
    "docs/public-demo-readiness-2026-08-11.md",
    "docs/public-demo-smoke-template-2026-08-11.md",
    "docs/public-demo-visual-evidence-plan-2026-08-11.md",
    "docs/public-security-review-2026-08-11.md",
    "docs/trusted-path-local-closure-2026-08-10.md",
    "frontend/.env.example",
    "frontend/vercel.json",
    "tests/performance/deployment_readiness_check.py",
    "tests/performance/public_demo_pre_push_audit.py",
    "tests/performance/public_demo_security_audit.py",
    "tests/performance/public_demo_smoke.py",
}

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


@dataclass
class CompletionCheck:
    name: str
    status: str
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


def list_tracked(git: GitRunner) -> set[str]:
    result = git(["ls-files"])
    if result.returncode != 0:
        return set()
    return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}


def pass_check(name: str, detail: str) -> CompletionCheck:
    return CompletionCheck(name, "pass", detail)


def fail_check(name: str, detail: str) -> CompletionCheck:
    return CompletionCheck(name, "fail", detail)


def pending_check(name: str, detail: str) -> CompletionCheck:
    return CompletionCheck(name, "pending_external", detail)


def check_branch(git: GitRunner, expected_branch: str) -> CompletionCheck:
    result = git(["branch", "--show-current"])
    branch = result.stdout.strip()
    if result.returncode == 0 and branch == expected_branch:
        return pass_check("display branch", f"branch={branch!r}")
    return fail_check("display branch", f"branch={branch!r}, expected={expected_branch!r}")


def check_clean_worktree(git: GitRunner) -> CompletionCheck:
    result = git(["status", "--porcelain=v1"])
    dirty = [line for line in result.stdout.splitlines() if line.strip()]
    if result.returncode == 0 and not dirty:
        return pass_check("clean worktree", "tracked worktree is clean")
    return fail_check("clean worktree", f"{len(dirty)} dirty item(s)")


def check_tag(git: GitRunner, tag: str) -> CompletionCheck:
    head = git(["rev-parse", "HEAD"])
    tag_target = git(["rev-list", "-n", "1", tag])
    if (
        head.returncode == 0
        and tag_target.returncode == 0
        and head.stdout.strip() == tag_target.stdout.strip()
    ):
        return pass_check("baseline tag", f"{tag} points to HEAD {head.stdout[:12]}")
    return fail_check("baseline tag", f"{tag} does not point to HEAD")


def _ls_remote_sha(result: GitResult) -> str:
    if result.returncode != 0:
        return ""
    first_line = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    if not first_line:
        return ""
    return first_line.split(maxsplit=1)[0]


def check_remote_push(git: GitRunner, expected_branch: str, tag: str) -> CompletionCheck:
    head = git(["rev-parse", "HEAD"])
    tag_target = git(["rev-list", "-n", "1", tag])
    branch_ref = git(["ls-remote", "--heads", "origin", expected_branch])
    tag_ref = git(["ls-remote", "--tags", "origin", tag])

    if branch_ref.returncode != 0 or tag_ref.returncode != 0:
        return pending_check(
            "display branch push",
            "remote branch/tag could not be verified; push or remote access still pending",
        )

    branch_sha = _ls_remote_sha(branch_ref)
    tag_sha = _ls_remote_sha(tag_ref)
    head_sha = head.stdout.strip()
    tag_target_sha = tag_target.stdout.strip()
    if (
        head.returncode == 0
        and tag_target.returncode == 0
        and branch_sha == head_sha
        and tag_sha == tag_target_sha
        and tag_target_sha == head_sha
    ):
        return pass_check("display branch push", f"remote branch and {tag} point to HEAD {head_sha[:12]}")

    return pending_check(
        "display branch push",
        "remote branch/tag exists but does not match the current local baseline",
    )


def check_required_files(tracked: set[str]) -> CompletionCheck:
    missing = sorted(REQUIRED_TRACKED_FILES - tracked)
    if not missing:
        return pass_check("required demo artifacts tracked", "all required docs, templates, and audit scripts are tracked")
    return fail_check("required demo artifacts tracked", ", ".join(missing[:20]))


def is_forbidden_public_demo_path(path: str) -> bool:
    normalized = path.strip().replace("\\", "/")
    return (
        normalized in FORBIDDEN_PUBLIC_DEMO_EXACT_PATHS
        or normalized.endswith(".bak")
        or any(normalized.startswith(prefix) for prefix in FORBIDDEN_PUBLIC_DEMO_PREFIXES)
    )


def check_forbidden_public_demo_files(tracked: set[str]) -> CompletionCheck:
    found = sorted(path for path in tracked if is_forbidden_public_demo_path(path))
    if not found:
        return pass_check("debug/generated public-demo files", "0 forbidden public-demo file(s)")
    return fail_check("debug/generated public-demo files", ", ".join(found[:20]))


def is_runtime_artifact_path(path: str) -> bool:
    normalized = path.strip().replace("\\", "/")
    return normalized in RUNTIME_ARTIFACT_EXACT_PATHS or any(
        normalized.startswith(prefix) for prefix in RUNTIME_ARTIFACT_PREFIXES
    )


def check_history_artifacts(git: GitRunner) -> CompletionCheck:
    result = git(["rev-list", "--objects", "HEAD"])
    history_paths: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        path = parts[1]
        if is_runtime_artifact_path(path):
            history_paths.append(path)

    if result.returncode == 0 and not history_paths:
        return pass_check("runtime artifact history", "0 reachable runtime artifact path(s)")
    if result.returncode != 0:
        return fail_check("runtime artifact history", "could not inspect branch history")
    return fail_check("runtime artifact history", ", ".join(history_paths[:20]))


def check_readme_status(read_text: TextReader) -> list[CompletionCheck]:
    try:
        readme = read_text("README.md")
    except OSError:
        return [fail_check("README status", "README.md missing")]

    checks: list[CompletionCheck] = []
    checks.append(
        pass_check("README scope", "public-demo candidate wording present")
        if "public-demo candidate" in readme
        else fail_check("README scope", "public-demo candidate wording missing")
    )
    checks.append(
        pass_check("selected deployment path", "Vercel frontend, Render backend, Neon Postgres")
        if "Vercel frontend, Render backend, Neon Postgres" in readme
        else fail_check("selected deployment path", "selected provider path missing")
    )
    checks.append(
        pass_check("quick gate evidence", "backend, frontend, and security evidence present")
        if all(
            marker in readme
            for marker in (
                "39 passed, 85 skipped",
                "38 passed, 5 skipped, 1 warning",
                "12 passed files / 71 passed tests",
                "Filled sensitive config placeholder count: `0`",
            )
        )
        else fail_check("quick gate evidence", "README quick gate evidence is stale or incomplete")
    )
    if "Online demo: not deployed yet." in readme:
        checks.append(pending_check("public URL", "online demo URL has not been deployed yet"))
    else:
        checks.append(pass_check("public URL", "README no longer marks online demo as not deployed"))
    if "Public smoke test: not verified yet." in readme:
        checks.append(pending_check("public smoke", "public HTTPS smoke still needs real URLs"))
    else:
        checks.append(pass_check("public smoke", "README no longer marks public smoke as unverified"))
    return checks


def check_docs(read_text: TextReader) -> list[CompletionCheck]:
    checks: list[CompletionCheck] = []
    docs_to_markers = {
        "docs/public-demo-readiness-2026-08-11.md": (
            "Not Yet Proven",
            "Deferred Items",
            "2fa89b9",
        ),
        "docs/public-demo-deployment-runbook-2026-08-11.md": (
            "Completion Rule",
            "Vercel",
            "Render",
            "Neon",
            "docs/public-demo-visual-evidence-plan-2026-08-11.md",
            "60-90 second recording",
        ),
        "docs/public-demo-smoke-template-2026-08-11.md": (
            "Frontend URL: `TBD`",
            "Backend URL: `TBD`",
            "High-risk action",
        ),
        "docs/public-demo-visual-evidence-plan-2026-08-11.md": (
            "Capture Rules",
            "Required Screenshots",
            "Recording Script",
        ),
        "docs/interview-demo-guide-2026-08-11.md": (
            "3-Minute Version",
            "10-Minute Version",
            "Screenshot",
        ),
        "docs/demo-data/README.md": (
            "fictional demo data",
            "Do not use real customers",
        ),
    }
    for path, markers in docs_to_markers.items():
        try:
            text = read_text(path)
        except OSError:
            checks.append(fail_check(f"doc markers: {path}", "file missing"))
            continue
        missing = [marker for marker in markers if marker not in text]
        if missing:
            checks.append(fail_check(f"doc markers: {path}", ", ".join(missing)))
        else:
            checks.append(pass_check(f"doc markers: {path}", "required markers present"))
    return checks


def _check_text_markers(read_text: TextReader, path: str, name: str, markers: tuple[str, ...]) -> CompletionCheck:
    try:
        text = read_text(path)
    except OSError:
        return fail_check(name, f"{path} missing")
    missing = [marker for marker in markers if marker not in text]
    if missing:
        return fail_check(name, ", ".join(missing))
    return pass_check(name, "required markers present")


def check_deployment_templates(read_text: TextReader) -> list[CompletionCheck]:
    checks = [
        _check_text_markers(
            read_text,
            "deploy/render.example.yaml",
            "deployment template: Render",
            (
                "runtime: python",
                "rootDir: .",
                "buildCommand: python -m pip install --upgrade pip && python -m pip install -r backend/requirements.txt",
                "startCommand: PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port $PORT",
                "healthCheckPath: /health",
                "key: DATABASE_URL",
                "key: JWT_SECRET_KEY",
                "key: CORS_ORIGINS",
                "key: COOKIE_SECURE",
                'value: "true"',
                "key: ENABLE_PUBLIC_DOCS",
                'value: "false"',
                "key: ENABLE_EVOLUTION_API",
                'value: "false"',
            ),
        ),
        _check_text_markers(
            read_text,
            "backend/.env.production.example",
            "deployment template: backend env",
            (
                "ENVIRONMENT=production",
                "ENV=prod",
                "DATABASE_URL=",
                "JWT_SECRET_KEY=",
                "FRONTEND_URL=https://your-frontend.example.com",
                "CORS_ORIGINS=https://your-frontend.example.com",
                "COOKIE_SECURE=true",
                "ENABLE_PUBLIC_DOCS=false",
                "ENABLE_EVOLUTION_API=false",
            ),
        ),
        _check_text_markers(
            read_text,
            "frontend/.env.example",
            "deployment template: frontend env",
            (
                "VITE_API_BASE_URL=/api",
                "VITE_WS_BASE=",
                "VITE_DEMO_ENABLED=false",
                "VITE_DEMO_PASSWORD=",
            ),
        ),
    ]

    try:
        vercel = json.loads(read_text("frontend/vercel.json"))
    except (OSError, json.JSONDecodeError):
        checks.append(fail_check("deployment template: Vercel", "frontend/vercel.json missing or invalid JSON"))
    else:
        expected = {
            "framework": "vite",
            "installCommand": "npm ci",
            "buildCommand": "npm run build",
            "outputDirectory": "dist",
        }
        mismatches = [key for key, value in expected.items() if vercel.get(key) != value]
        rewrites = vercel.get("rewrites", [])
        has_spa_rewrite = any(
            isinstance(rewrite, dict)
            and rewrite.get("source") == "/(.*)"
            and rewrite.get("destination") == "/index.html"
            for rewrite in rewrites
        )
        if mismatches or not has_spa_rewrite:
            detail = ", ".join(mismatches + ([] if has_spa_rewrite else ["rewrites"]))
            checks.append(fail_check("deployment template: Vercel", detail))
        else:
            checks.append(pass_check("deployment template: Vercel", "required settings present"))
    return checks


def run_audit(
    *,
    expected_branch: str,
    baseline_tag: str,
    git: GitRunner = run_git,
    read_text: TextReader = read_tracked_text,
) -> dict:
    tracked = list_tracked(git)
    checks = [
        check_branch(git, expected_branch),
        check_clean_worktree(git),
        check_tag(git, baseline_tag),
        check_required_files(tracked),
        check_forbidden_public_demo_files(tracked),
        check_history_artifacts(git),
        *check_readme_status(read_text),
        *check_docs(read_text),
        *check_deployment_templates(read_text),
        check_remote_push(git, expected_branch, baseline_tag),
        pending_check("managed Postgres migration", "requires Neon or another managed Postgres database"),
        pending_check("cloud deployment", "requires Vercel, Render, and Neon resources"),
        pending_check("browser screenshots and recording", "capture after local/public smoke; do not commit generated media"),
    ]
    failures = [check for check in checks if check.status == "fail"]
    pending = [check for check in checks if check.status == "pending_external"]
    return {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "purpose": "public demo completion boundary audit",
            "expected_branch": expected_branch,
            "baseline_tag": baseline_tag,
            "secret_values_redacted": True,
        },
        "summary": {
            "local_ready": not failures,
            "public_complete": not failures and not pending,
            "check_count": len(checks),
            "failure_count": len(failures),
            "pending_external_count": len(pending),
        },
        "checks": [asdict(check) for check in checks],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-branch", default="codex/public-demo-20260810")
    parser.add_argument("--baseline-tag", default="public-demo-local-20260811-v4")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    report = run_audit(expected_branch=args.expected_branch, baseline_tag=args.baseline_tag)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("AgentX public demo completion audit")
    print("=" * 80)
    print(f"local_ready: {report['summary']['local_ready']}")
    print(f"public_complete: {report['summary']['public_complete']}")
    print(
        "checks: "
        f"{report['summary']['check_count']}  "
        f"failures: {report['summary']['failure_count']}  "
        f"pending_external: {report['summary']['pending_external_count']}"
    )
    for check in report["checks"]:
        print(f"{check['status'].upper()} {check['name']}: {check['detail']}")
    print(f"JSON report: {out_path}")
    return 0 if report["summary"]["local_ready"] else 1


if __name__ == "__main__":
    sys.exit(main())


