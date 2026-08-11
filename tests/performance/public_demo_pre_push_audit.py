"""Pre-push audit for the AgentX public demo branch.

This script checks local Git state before the branch is pushed to a public
remote. It does not contact external services and it does not print secret
values.

Usage:
    python tests/performance/public_demo_pre_push_audit.py
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
DEFAULT_OUT = PROJECT_ROOT / "tests" / "reports" / "public_demo_pre_push_audit.json"

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

SECRET_PATTERNS = (
    r"AKIA[0-9A-Z]{16}",
    r"AIza[0-9A-Za-z_-]{35}",
    r"xox[baprs]-[0-9A-Za-z-]{10,}",
    r"ghp_[0-9A-Za-z]{36}",
    r"-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----",
)

PUBLIC_DEMO_WORKFLOW = ".github/workflows/public-demo-quick-gates.yml"
LEGACY_HEAVY_WORKFLOWS = (
    ".github/workflows/backend-ci.yml",
    ".github/workflows/evaluation.yml",
)
HEAVY_WORKFLOW_PATTERN = r"docker|compose|down -v|prune|no-cache"


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


def check_branch(git: GitRunner, expected_branch: str) -> AuditCheck:
    result = git(["branch", "--show-current"])
    branch = result.stdout.strip()
    return AuditCheck(
        "display branch",
        result.returncode == 0 and branch == expected_branch,
        f"branch={branch!r}, expected={expected_branch!r}",
    )


def check_clean_worktree(git: GitRunner) -> AuditCheck:
    result = git(["status", "--porcelain=v1"])
    dirty = [line for line in result.stdout.splitlines() if line.strip()]
    return AuditCheck(
        "clean worktree",
        result.returncode == 0 and not dirty,
        "clean" if not dirty else f"{len(dirty)} dirty item(s)",
    )


def check_tag_points_to_head(git: GitRunner, tag: str) -> AuditCheck:
    head = git(["rev-parse", "HEAD"])
    tag_target = git(["rev-list", "-n", "1", tag])
    passed = (
        head.returncode == 0
        and tag_target.returncode == 0
        and head.stdout.strip() == tag_target.stdout.strip()
    )
    return AuditCheck(
        "baseline tag points to HEAD",
        passed,
        f"tag={tag!r}, head={head.stdout[:12]}, tag_target={tag_target.stdout[:12]}",
    )


def check_tracked_artifacts(git: GitRunner) -> AuditCheck:
    result = git(["ls-files"])
    tracked = [
        path
        for path in result.stdout.splitlines()
        if is_runtime_artifact_path(path)
    ]
    return AuditCheck(
        "runtime artifacts not tracked",
        result.returncode == 0 and not tracked,
        "0 tracked runtime artifact(s)" if not tracked else ", ".join(tracked[:20]),
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


def check_forbidden_public_demo_files(git: GitRunner) -> AuditCheck:
    result = git(["ls-files"])
    found = [
        path
        for path in result.stdout.splitlines()
        if is_forbidden_public_demo_path(path)
    ]
    return AuditCheck(
        "debug and generated public-demo files not tracked",
        result.returncode == 0 and not found,
        "0 forbidden public-demo file(s)" if not found else ", ".join(found[:20]),
    )


def check_history_artifacts(git: GitRunner) -> AuditCheck:
    result = git(["rev-list", "--objects", "HEAD"])
    history_paths: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        path = parts[1]
        if is_runtime_artifact_path(path):
            history_paths.append(path)

    return AuditCheck(
        "runtime artifacts not reachable in branch history",
        result.returncode == 0 and not history_paths,
        "0 reachable runtime artifact path(s)" if not history_paths else ", ".join(history_paths[:20]),
    )


def check_high_confidence_secrets(git: GitRunner) -> AuditCheck:
    pattern = "|".join(f"({p})" for p in SECRET_PATTERNS)
    result = git(["grep", "-n", "-I", "-E", pattern])
    if result.returncode == 1:
        return AuditCheck("high-confidence secret scan", True, "0 high-confidence match(es)")
    match_count = len([line for line in result.stdout.splitlines() if line.strip()])
    return AuditCheck(
        "high-confidence secret scan",
        False,
        f"{match_count} high-confidence match(es); inspect git grep output locally",
    )


def check_docs_public_status(git: GitRunner) -> AuditCheck:
    result = git(["grep", "-n", "Online demo: not deployed yet.", "README.md"])
    return AuditCheck(
        "README does not overclaim public deployment",
        result.returncode == 0,
        "README marks online demo as not deployed" if result.returncode == 0 else "README public demo status needs review",
    )


def check_public_demo_workflow(git: GitRunner, expected_branch: str) -> AuditCheck:
    branch_match = git(["grep", "-n", expected_branch, PUBLIC_DEMO_WORKFLOW])
    heavy_match = git(["grep", "-n", "-I", "-E", HEAVY_WORKFLOW_PATTERN, PUBLIC_DEMO_WORKFLOW])
    passed = branch_match.returncode == 0 and heavy_match.returncode == 1
    if passed:
        detail = "public-demo workflow targets display branch and has no Docker/full-smoke command"
    elif branch_match.returncode != 0:
        detail = f"{PUBLIC_DEMO_WORKFLOW} does not target {expected_branch!r}"
    else:
        detail = f"{PUBLIC_DEMO_WORKFLOW} contains Docker/full-smoke-looking command text"
    return AuditCheck("public-demo workflow scope", passed, detail)


def check_legacy_workflows_skip_display_branch(git: GitRunner, expected_branch: str) -> AuditCheck:
    result = git(["grep", "-n", expected_branch, *LEGACY_HEAVY_WORKFLOWS])
    passed = result.returncode == 1
    return AuditCheck(
        "legacy heavy workflows skip display branch",
        passed,
        (
            "backend/evaluation workflows do not target the display branch"
            if passed
            else "legacy backend/evaluation workflow targets the display branch"
        ),
    )


def run_audit(
    *,
    expected_branch: str,
    baseline_tag: str,
    git: GitRunner = run_git,
) -> dict:
    checks = [
        check_branch(git, expected_branch),
        check_clean_worktree(git),
        check_tag_points_to_head(git, baseline_tag),
        check_tracked_artifacts(git),
        check_forbidden_public_demo_files(git),
        check_history_artifacts(git),
        check_high_confidence_secrets(git),
        check_docs_public_status(git),
        check_public_demo_workflow(git, expected_branch),
        check_legacy_workflows_skip_display_branch(git, expected_branch),
    ]
    failures = [check for check in checks if not check.passed]
    return {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "purpose": "local pre-push audit for the public demo branch",
            "expected_branch": expected_branch,
            "baseline_tag": baseline_tag,
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
    parser.add_argument("--expected-branch", default="codex/public-demo-20260810")
    parser.add_argument("--baseline-tag", default="public-demo-local-20260811-v6")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    report = run_audit(expected_branch=args.expected_branch, baseline_tag=args.baseline_tag)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("AgentX public demo pre-push audit")
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
