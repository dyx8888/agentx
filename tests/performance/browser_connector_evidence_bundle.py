"""Run the browser connector pilot evidence commands in a fixed order.

This helper does not make the connector pilot-ready by itself. It standardizes
the commands that create the deployment manifest, staging probe report, DB audit
report, live evidence template, and final readiness report. Manual Chrome and
platform validation evidence must still be filled by a human tester.
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
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_DIR = PROJECT_ROOT / "tests" / "reports"
DEFAULT_BUNDLE_REPORT = DEFAULT_REPORT_DIR / "browser_connector_evidence_bundle.json"
MANIFEST_BUILDER = PROJECT_ROOT / "browser-extension" / "agentx-connector" / "tools" / "build_deployment_manifest.py"
STAGING_PROBE = PROJECT_ROOT / "tests" / "performance" / "browser_connector_staging_probe.py"
DB_AUDIT = PROJECT_ROOT / "tests" / "performance" / "browser_connector_db_audit.py"
LIVE_EVIDENCE_TEMPLATE = PROJECT_ROOT / "tests" / "performance" / "browser_connector_live_evidence_template.py"
PILOT_READINESS_AUDIT = PROJECT_ROOT / "tests" / "performance" / "browser_connector_pilot_readiness_audit.py"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class BundleStep:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class CommandPreview:
    name: str
    args: list[str]


CommandRunner = Callable[[list[str]], CommandResult]
SENSITIVE_COMMAND_OPTIONS = {"--database-url"}


def _run_command(args: list[str]) -> CommandResult:
    proc = subprocess.run(
        args,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return CommandResult(proc.returncode, proc.stdout.strip(), proc.stderr.strip())


def _validate_origin(url: str, *, name: str, allow_http_local: bool = False) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"{name} must include scheme and host")
    if parsed.username or parsed.password:
        raise ValueError(f"{name} must not include credentials")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{name} must not include query strings or fragments")
    if parsed.scheme != "https":
        local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
        if not (allow_http_local and local_http):
            raise ValueError(f"{name} must use https, except localhost with --allow-http-local")
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


def _command_preview(name: str, args: list[str]) -> CommandPreview:
    redacted: list[str] = []
    redact_next = False
    for arg in args:
        if redact_next:
            redacted.append("<redacted>")
            redact_next = False
            continue
        redacted.append(arg)
        if arg in SENSITIVE_COMMAND_OPTIONS:
            redact_next = True
    return CommandPreview(name, redacted)


def _step(name: str, args: list[str], runner: CommandRunner, *, dry_run: bool = False) -> BundleStep:
    if dry_run:
        return BundleStep(name, "planned", "command planned; not executed")
    result = runner(args)
    if result.returncode == 0:
        return BundleStep(name, "pass", "command completed")
    return BundleStep(name, "fail", f"command failed with returncode={result.returncode}")


def _skipped(name: str, detail: str) -> BundleStep:
    return BundleStep(name, "skipped", detail)


def _remaining(names: list[str]) -> list[BundleStep]:
    return [_skipped(name, "skipped because an earlier evidence step failed") for name in names]


def run_bundle(
    *,
    frontend_url: str,
    backend_url: str,
    company_id: int,
    report_dir: Path = DEFAULT_REPORT_DIR,
    manifest_out: Path | None = None,
    database_url: str = "",
    allow_http_local: bool = False,
    overwrite_live_evidence_template: bool = False,
    require_pilot_ready: bool = False,
    expected_extension_commit: str = "",
    dry_run: bool = False,
    command_runner: CommandRunner = _run_command,
) -> dict[str, object]:
    if company_id <= 0:
        raise ValueError("company_id must be a positive integer")

    frontend_origin = _validate_origin(frontend_url, name="frontend_url", allow_http_local=allow_http_local)
    backend_origin = _validate_origin(backend_url, name="backend_url", allow_http_local=allow_http_local)
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = Path(manifest_out) if manifest_out else report_dir / "agentx_connector_deployment_manifest.json"
    staging_report = report_dir / "browser_connector_staging_probe.json"
    db_report = report_dir / "browser_connector_db_audit.json"
    live_evidence = report_dir / "browser_connector_live_evidence.json"
    readiness_report = report_dir / "browser_connector_pilot_readiness_audit.json"

    steps: list[BundleStep] = []
    commands: list[CommandPreview] = []

    manifest_cmd = [
        sys.executable,
        str(MANIFEST_BUILDER),
        "--backend",
        backend_origin,
        "--out",
        str(manifest_path),
    ]
    if allow_http_local:
        manifest_cmd.append("--allow-http-local")
    commands.append(_command_preview("deployment manifest", manifest_cmd))
    steps.append(_step("deployment manifest", manifest_cmd, command_runner, dry_run=dry_run))
    if steps[-1].status == "fail":
        steps.extend(_remaining(["staging probe", "database audit", "manual live evidence template", "pilot readiness audit"]))
        return _report(steps, commands, frontend_origin, backend_origin, company_id, report_dir, manifest_path, database_url, expected_extension_commit, dry_run)

    staging_cmd = [
        sys.executable,
        str(STAGING_PROBE),
        "--frontend",
        frontend_origin,
        "--backend",
        backend_origin,
        "--manifest",
        str(manifest_path),
        "--out",
        str(staging_report),
    ]
    if allow_http_local:
        staging_cmd.append("--allow-http")
    commands.append(_command_preview("staging probe", staging_cmd))
    steps.append(_step("staging probe", staging_cmd, command_runner, dry_run=dry_run))
    if steps[-1].status == "fail":
        steps.extend(_remaining(["database audit", "manual live evidence template", "pilot readiness audit"]))
        return _report(steps, commands, frontend_origin, backend_origin, company_id, report_dir, manifest_path, database_url, expected_extension_commit, dry_run)

    db_cmd = [
        sys.executable,
        str(DB_AUDIT),
        "--company-id",
        str(company_id),
        "--out",
        str(db_report),
    ]
    if database_url.strip():
        db_cmd.extend(["--database-url", database_url.strip()])
    commands.append(_command_preview("database audit", db_cmd))
    steps.append(_step("database audit", db_cmd, command_runner, dry_run=dry_run))
    if steps[-1].status == "fail":
        steps.extend(_remaining(["manual live evidence template", "pilot readiness audit"]))
        return _report(steps, commands, frontend_origin, backend_origin, company_id, report_dir, manifest_path, database_url, expected_extension_commit, dry_run)

    if live_evidence.exists() and not overwrite_live_evidence_template and not dry_run:
        steps.append(_skipped("manual live evidence template", "existing live evidence file kept"))
    else:
        template_cmd = [
            sys.executable,
            str(LIVE_EVIDENCE_TEMPLATE),
            "--out",
            str(live_evidence),
            "--frontend-origin",
            frontend_origin,
            "--backend-origin",
            backend_origin,
            "--test-company-id",
            str(company_id),
            "--staging-probe-report",
            str(staging_report),
            "--db-audit-report",
            str(db_report),
            "--pilot-readiness-report",
            str(readiness_report),
        ]
        if expected_extension_commit.strip():
            template_cmd.extend(["--extension-commit", expected_extension_commit.strip()])
        if overwrite_live_evidence_template:
            template_cmd.append("--overwrite")
        commands.append(_command_preview("manual live evidence template", template_cmd))
        steps.append(_step("manual live evidence template", template_cmd, command_runner, dry_run=dry_run))
    if steps[-1].status == "fail":
        steps.extend(_remaining(["pilot readiness audit"]))
        return _report(steps, commands, frontend_origin, backend_origin, company_id, report_dir, manifest_path, database_url, expected_extension_commit, dry_run)

    readiness_cmd = [
        sys.executable,
        str(PILOT_READINESS_AUDIT),
        "--expected-frontend-url",
        frontend_origin,
        "--expected-backend-url",
        backend_origin,
        "--expected-manifest-path",
        str(manifest_path),
        "--staging-probe",
        str(staging_report),
        "--db-audit",
        str(db_report),
        "--manual-evidence",
        str(live_evidence),
        "--out",
        str(readiness_report),
    ]
    if expected_extension_commit.strip():
        readiness_cmd.extend(["--expected-extension-commit", expected_extension_commit.strip()])
    if require_pilot_ready:
        readiness_cmd.append("--require-pilot-ready")
    commands.append(_command_preview("pilot readiness audit", readiness_cmd))
    steps.append(_step("pilot readiness audit", readiness_cmd, command_runner, dry_run=dry_run))

    return _report(steps, commands, frontend_origin, backend_origin, company_id, report_dir, manifest_path, database_url, expected_extension_commit, dry_run)


def _report(
    steps: list[BundleStep],
    commands: list[CommandPreview],
    frontend_origin: str,
    backend_origin: str,
    company_id: int,
    report_dir: Path,
    manifest_path: Path,
    database_url: str,
    expected_extension_commit: str,
    dry_run: bool,
) -> dict[str, object]:
    failures = [step for step in steps if step.status == "fail"]
    planned = [step for step in steps if step.status == "planned"]
    return {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "purpose": "browser connector pilot evidence command bundle",
            "dry_run": dry_run,
            "frontend_url": frontend_origin,
            "backend_url": backend_origin,
            "company_id": company_id,
            "report_dir": str(report_dir),
            "manifest_path": str(manifest_path),
            "database_url_provided": bool(database_url.strip()),
            "expected_extension_commit": expected_extension_commit.strip() or None,
            "secret_values_redacted": True,
        },
        "summary": {
            "passed": not failures,
            "step_count": len(steps),
            "failure_count": len(failures),
            "planned_count": len(planned),
        },
        "steps": [asdict(step) for step in steps],
        "commands": [asdict(command) for command in commands],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend", required=True, help="Exact AgentX frontend origin")
    parser.add_argument("--backend", required=True, help="Exact AgentX backend origin")
    parser.add_argument("--company-id", required=True, type=int, help="Pilot tenant/company id")
    parser.add_argument("--database-url", default="", help="Optional DATABASE_URL override; never printed or written")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--manifest-out", type=Path, default=None)
    parser.add_argument("--allow-http-local", action="store_true")
    parser.add_argument("--overwrite-live-evidence-template", action="store_true")
    parser.add_argument("--require-pilot-ready", action="store_true")
    parser.add_argument("--expected-extension-commit", default="")
    parser.add_argument("--dry-run", action="store_true", help="Plan the evidence commands without executing them")
    parser.add_argument("--out", type=Path, default=DEFAULT_BUNDLE_REPORT)
    args = parser.parse_args(argv)

    try:
        report = run_bundle(
            frontend_url=args.frontend,
            backend_url=args.backend,
            company_id=args.company_id,
            report_dir=args.report_dir,
            manifest_out=args.manifest_out,
            database_url=args.database_url,
            allow_http_local=args.allow_http_local,
            overwrite_live_evidence_template=args.overwrite_live_evidence_template,
            require_pilot_ready=args.require_pilot_ready,
            expected_extension_commit=args.expected_extension_commit,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(f"evidence bundle failed: {exc}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("AgentX browser connector evidence bundle")
    print("=" * 80)
    print(f"passed: {report['summary']['passed']}")
    print(f"steps: {report['summary']['step_count']}  failures: {report['summary']['failure_count']}")
    for step in report["steps"]:
        print(f"{step['status'].upper()} {step['name']}: {step['detail']}")
    print(f"JSON report: {args.out}")
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
