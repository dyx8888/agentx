"""Pilot readiness boundary audit for the AgentX browser connector.

This audit separates local implementation readiness from real-user pilot
readiness. Local readiness can pass from committed code, docs, and regression
coverage. Pilot readiness remains pending until staging evidence proves the
real Chrome extension, authenticated Cookie/CORS path, database audit, and
business UAT flow.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Any
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = PROJECT_ROOT / "tests" / "reports" / "browser_connector_pilot_readiness_audit.json"
DEFAULT_STAGING_PROBE = PROJECT_ROOT / "tests" / "reports" / "browser_connector_staging_probe.json"
DEFAULT_DB_AUDIT = PROJECT_ROOT / "tests" / "reports" / "browser_connector_db_audit.json"
DEFAULT_MANUAL_EVIDENCE = PROJECT_ROOT / "tests" / "reports" / "browser_connector_live_evidence.json"
DEFAULT_MAX_EVIDENCE_AGE_HOURS = 72

REQUIRED_TRACKED_FILES = {
    "backend/alembic/versions/003_browser_connector_events.py",
    "backend/app/api/browser_connector.py",
    "backend/app/core/feature_flags.py",
    "backend/app/database/models.py",
    "backend/app/services/browser_connector_business.py",
    "backend/app/services/browser_connector_capture.py",
    "backend/app/services/browser_connector_normalizer.py",
    "backend/app/services/browser_connector_rules.py",
    "backend/app/services/browser_connector_schemas.py",
    "backend/config/feature_flags.yaml",
    "browser-extension/agentx-connector/README.md",
    "browser-extension/agentx-connector/manifest.deployment.example.json",
    "browser-extension/agentx-connector/manifest.json",
    "browser-extension/agentx-connector/src/background.js",
    "browser-extension/agentx-connector/src/content-script.js",
    "browser-extension/agentx-connector/src/injected.js",
    "browser-extension/agentx-connector/tools/build_deployment_manifest.py",
    "docs/browser-connector-deployment-runbook-2026-08-13.md",
    "docs/browser-connector-live-validation-and-business-rollout-plan-2026-08-13.md",
    "docs/browser-connector-normalization-map-2026-08-13.md",
    "docs/browser-connector-security-boundaries-2026-08-12.md",
    "frontend/e2e/browser-connector-extension.spec.js",
    "frontend/playwright.browser-connector.config.js",
    "frontend/src/__tests__/SettingsPage.test.jsx",
    "frontend/src/api/browserConnector.js",
    "frontend/src/pages/SettingsPage.jsx",
    "tests/api/test_browser_connector.py",
    "tests/api/test_browser_connector_business_integration.py",
    "tests/api/test_browser_connector_cors_auth.py",
    "tests/api/test_browser_connector_normalization.py",
    "tests/api/test_browser_connector_storage.py",
    "tests/performance/browser_connector_db_audit.py",
    "tests/performance/browser_connector_evidence_bundle.py",
    "tests/performance/browser_connector_live_evidence_template.py",
    "tests/performance/browser_connector_staging_probe.py",
    "tests/performance/test_browser_connector_db_audit.py",
    "tests/performance/test_browser_connector_evidence_bundle.py",
    "tests/performance/test_browser_connector_live_evidence_template.py",
    "tests/performance/test_browser_connector_manifest_builder.py",
    "tests/performance/test_browser_connector_staging_probe.py",
}

FORBIDDEN_WRITE_MARKERS = (
    "execute_stop_loss_action",
    "auto_execute",
    "send_invitation",
    "send_message",
    "update_budget",
    "pause_campaign",
    "platform_write_operation: true",
)

SAFETY_SCAN_FILES = (
    "backend/app/api/browser_connector.py",
    "backend/app/services/browser_connector_business.py",
    "browser-extension/agentx-connector/src/background.js",
    "browser-extension/agentx-connector/src/injected.js",
    "frontend/src/pages/SettingsPage.jsx",
)

LIVE_EVIDENCE_REQUIRED_FIELDS = (
    "generated_at",
    "frontend_origin",
    "backend_origin",
    "extension_commit",
    "browser",
    "test_company_id",
    "test_user",
    "platform_page",
    "matched_allowlist_rule",
    "ingest_authenticated_result",
    "stored_event_id",
    "normalized_record_kinds",
    "settings_source_counts",
)

LIVE_EVIDENCE_BOOLEAN_REQUIREMENTS = {
    "real_chrome_extension_loaded": True,
    "real_platform_sample_collected": True,
    "sensitive_value_scan_passed": True,
    "platform_write_operation_observed": False,
    "settings_review_completed": True,
    "business_import_requires_manual_confirmation": True,
}

LIVE_EVIDENCE_SECRET_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"authorization\s*[:=]\s*\S+",
        r"\bbearer\s+[A-Za-z0-9._\-]{8,}",
        r"\bcookie\s*[:=]\s*[^,;\s]+",
        r"\b(?:access_)?token\s*[:=]\s*[^,;\s]+",
        r"\b(?:password|passwd|pwd)\s*[:=]\s*[^,;\s]+",
        r"\b(?:captcha|verification|verifycode|smscode|otp)\s*[:=]\s*[^,;\s]+",
        r"\b(?:payment|creditcard|bankcard|cardnumber|cvv)\s*[:=]\s*[^,;\s]+",
        r"\b(?:secret|credential|session)\s*[:=]\s*[^,;\s]+",
        r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b",
    )
)
LIVE_EVIDENCE_URL_RE = re.compile(r"https?://[^\s,\"']+", re.IGNORECASE)
HTTPS_ORIGIN_RE = re.compile(r"^https://[^/?#]+/?$", re.IGNORECASE)


@dataclass(frozen=True)
class PilotCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str


GitRunner = Callable[[list[str]], GitResult]
TextReader = Callable[[str], str]
JsonReader = Callable[[Path], dict[str, Any] | None]


def run_git(args: list[str]) -> GitResult:
    proc = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return GitResult(proc.returncode, proc.stdout.strip(), proc.stderr.strip())


def read_tracked_text(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8", errors="replace")


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def pass_check(name: str, detail: str) -> PilotCheck:
    return PilotCheck(name, "pass", detail)


def fail_check(name: str, detail: str) -> PilotCheck:
    return PilotCheck(name, "fail", detail)


def pending_check(name: str, detail: str) -> PilotCheck:
    return PilotCheck(name, "pending_external", detail)


def list_tracked(git: GitRunner) -> set[str]:
    result = git(["ls-files"])
    if result.returncode != 0:
        return set()
    return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}


def check_branch(git: GitRunner, expected_branch: str) -> PilotCheck:
    result = git(["branch", "--show-current"])
    branch = result.stdout.strip()
    if result.returncode == 0 and branch == expected_branch:
        return pass_check("connector branch", f"branch={branch!r}")
    return fail_check("connector branch", f"branch={branch!r}, expected={expected_branch!r}")


def check_clean_worktree(git: GitRunner) -> PilotCheck:
    result = git(["status", "--porcelain=v1"])
    dirty = [line for line in result.stdout.splitlines() if line.strip()]
    if result.returncode == 0 and not dirty:
        return pass_check("clean connector worktree", "tracked worktree is clean")
    return fail_check("clean connector worktree", f"{len(dirty)} dirty item(s)")


def current_short_commit(git: GitRunner) -> str | None:
    result = git(["rev-parse", "--short", "HEAD"])
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def check_required_files(tracked: set[str]) -> PilotCheck:
    missing = sorted(REQUIRED_TRACKED_FILES - tracked)
    if not missing:
        return pass_check("connector artifacts tracked", "all connector code, docs, and audit scripts are tracked")
    return fail_check("connector artifacts tracked", ", ".join(missing[:20]))


def check_extension_manifest(read_text: TextReader) -> list[PilotCheck]:
    try:
        manifest = json.loads(read_text("browser-extension/agentx-connector/manifest.json"))
    except (OSError, json.JSONDecodeError):
        return [fail_check("local extension manifest", "manifest.json missing or invalid")]

    checks: list[PilotCheck] = []
    checks.append(
        pass_check("manifest version", "Chrome Manifest V3")
        if manifest.get("manifest_version") == 3
        else fail_check("manifest version", "manifest_version is not 3")
    )

    host_permissions = {str(item) for item in manifest.get("host_permissions", [])}
    broad = sorted(host_permissions & {"https://*/*", "http://*/*", "<all_urls>"})
    local_allowed = host_permissions <= {"http://localhost/*", "http://127.0.0.1/*"}
    if local_allowed and not broad:
        checks.append(pass_check("local manifest backend permissions", "local transport permissions only"))
    else:
        checks.append(fail_check("local manifest backend permissions", f"unexpected host permissions: {sorted(host_permissions)}"))

    content_matches: list[str] = []
    for item in manifest.get("content_scripts", []):
        if isinstance(item, dict):
            content_matches.extend(str(match) for match in item.get("matches", []))
    if any("jinritemai.com" in match for match in content_matches) and any("douyin.com" in match for match in content_matches):
        checks.append(pass_check("platform content-script matches", "allowlisted platform matches present"))
    else:
        checks.append(fail_check("platform content-script matches", "expected douyin/jinritemai matches"))
    return checks


def check_docs(read_text: TextReader) -> list[PilotCheck]:
    docs_to_markers = {
        "docs/browser-connector-deployment-runbook-2026-08-13.md": (
            "COOKIE_SAMESITE=none",
            "browser_connector_staging_probe.py",
            "browser_connector_db_audit.py",
            "The connector is not ready for real-user pilot use",
        ),
        "docs/browser-connector-security-boundaries-2026-08-12.md": (
            "read-only",
            "must not collect, store, or forward",
            "FEATURE_BROWSER_CONNECTOR_TENANT_IDS",
            "database audit",
        ),
        "docs/browser-connector-live-validation-and-business-rollout-plan-2026-08-13.md": (
            "可交付给用户试用的最低门槛",
            "真实 Chrome 插件链路验收",
            "DB audit",
            "不做平台自动点击",
        ),
        "docs/browser-connector-normalization-map-2026-08-13.md": (
            "creator_profile",
            "knowledge_observation",
            "campaign_metrics",
            "真实 staging/生产候选样本仍需",
        ),
    }

    checks: list[PilotCheck] = []
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


def check_no_platform_write_entrypoints(read_text: TextReader) -> PilotCheck:
    combined = []
    missing_files = []
    for path in SAFETY_SCAN_FILES:
        try:
            combined.append(read_text(path).lower())
        except OSError:
            missing_files.append(path)
    if missing_files:
        return fail_check("read-only safety scan", f"missing files: {', '.join(missing_files)}")

    text = "\n".join(combined)
    forbidden = [marker for marker in FORBIDDEN_WRITE_MARKERS if marker in text]
    has_readonly_evidence = "platform_write_operation: false" in text or "platform_write_operation" in text
    if forbidden:
        return fail_check("read-only safety scan", f"forbidden markers: {', '.join(forbidden)}")
    if not has_readonly_evidence:
        return fail_check("read-only safety scan", "platform_write_operation evidence missing")
    return pass_check("read-only safety scan", "no platform write automation markers found")


def _json_check(path: Path, json_reader: JsonReader, name: str) -> tuple[dict[str, Any] | None, PilotCheck | None]:
    data = json_reader(path)
    if data is None:
        return None, pending_check(name, f"missing or unreadable evidence file: {path}")
    return data, None


def _scan_live_evidence_value_leaks(value: Any, *, path: str = "manual") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            if key.startswith("_"):
                continue
            findings.extend(_scan_live_evidence_value_leaks(child, path=f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_scan_live_evidence_value_leaks(child, path=f"{path}[{index}]"))
    elif isinstance(value, str):
        for pattern in LIVE_EVIDENCE_SECRET_PATTERNS:
            if pattern.search(value):
                findings.append(path)
                break
        for match in LIVE_EVIDENCE_URL_RE.finditer(value):
            parsed = urlsplit(match.group(0))
            if parsed.query:
                findings.append(f"{path}:url_query")
                break
    return findings


def _require_secret_safe_report(data: dict[str, Any], *, path: str) -> list[str]:
    findings: list[str] = []
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    if meta.get("secret_values_redacted") is not True:
        findings.append("meta.secret_values_redacted")
    findings.extend(_scan_live_evidence_value_leaks(data, path=path))
    return sorted(set(findings))


def _parse_evidence_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    normalized = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", normalized)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _evidence_freshness_failures(
    *,
    field_path: str,
    generated_at: Any,
    now: datetime,
    max_age_hours: int,
) -> list[str]:
    generated = _parse_evidence_datetime(generated_at)
    if generated is None:
        return [f"{field_path}_invalid_or_missing"]
    now_utc = now if now.tzinfo and now.utcoffset() is not None else now.replace(tzinfo=timezone.utc)
    now_utc = now_utc.astimezone(timezone.utc)
    age_seconds = (now_utc - generated).total_seconds()
    if age_seconds < -300:
        return [f"{field_path}_from_future"]
    max_age_seconds = max_age_hours * 60 * 60
    if age_seconds > max_age_seconds:
        age_hours = int(age_seconds // 3600)
        return [f"{field_path}_stale age_hours={age_hours} max_age_hours={max_age_hours}"]
    return []


def check_staging_probe(
    path: Path,
    json_reader: JsonReader,
    *,
    expected_frontend_url: str | None = None,
    expected_backend_url: str | None = None,
    expected_manifest_path: str | None = None,
    now: datetime | None = None,
    max_evidence_age_hours: int = DEFAULT_MAX_EVIDENCE_AGE_HOURS,
) -> PilotCheck:
    data, pending = _json_check(path, json_reader, "staging CORS/Auth probe evidence")
    if pending:
        return pending
    assert data is not None

    summary = data.get("summary", {})
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    failures: list[str] = []
    if summary.get("passed") is not True:
        failures.append("summary.passed")
    for field in ("generated_at", "frontend_url", "backend_url", "manifest_path"):
        if not meta.get(field):
            failures.append(f"meta.{field}")
    failures.extend(
        _evidence_freshness_failures(
            field_path="meta.generated_at",
            generated_at=meta.get("generated_at"),
            now=now or datetime.now(timezone.utc),
            max_age_hours=max_evidence_age_hours,
        )
    )
    if meta.get("frontend_url") and not HTTPS_ORIGIN_RE.match(str(meta.get("frontend_url"))):
        failures.append("meta.frontend_url_https_origin")
    if meta.get("backend_url") and not HTTPS_ORIGIN_RE.match(str(meta.get("backend_url"))):
        failures.append("meta.backend_url_https_origin")
    if expected_frontend_url and str(meta.get("frontend_url", "")).rstrip("/") != expected_frontend_url.rstrip("/"):
        failures.append("meta.frontend_url_mismatch")
    if expected_backend_url and str(meta.get("backend_url", "")).rstrip("/") != expected_backend_url.rstrip("/"):
        failures.append("meta.backend_url_mismatch")
    if expected_manifest_path and str(meta.get("manifest_path", "")) != expected_manifest_path:
        failures.append("meta.manifest_path_mismatch")

    leaks = _require_secret_safe_report(data, path="staging")
    if leaks:
        failures.append(f"secret_or_raw_url_fields: {', '.join(leaks[:20])}")
    if failures:
        return fail_check("staging CORS/Auth probe evidence", "; ".join(failures))
    return pass_check("staging CORS/Auth probe evidence", f"passed with {summary.get('check_count')} checks")


def check_db_audit(
    path: Path,
    json_reader: JsonReader,
    *,
    now: datetime | None = None,
    max_evidence_age_hours: int = DEFAULT_MAX_EVIDENCE_AGE_HOURS,
) -> PilotCheck:
    data, pending = _json_check(path, json_reader, "database capture audit evidence")
    if pending:
        return pending
    assert data is not None

    summary = data.get("summary", {})
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    failures: list[str] = []
    if summary.get("passed") is not True:
        failures.append("summary.passed")
    if int(summary.get("total_events") or 0) <= 0:
        failures.append("summary.total_events")
    if not summary.get("normalized_record_counts"):
        failures.append("summary.normalized_record_counts")
    if meta.get("read_only") is not True:
        failures.append("meta.read_only")
    if not meta.get("generated_at"):
        failures.append("meta.generated_at")
    failures.extend(
        _evidence_freshness_failures(
            field_path="meta.generated_at",
            generated_at=meta.get("generated_at"),
            now=now or datetime.now(timezone.utc),
            max_age_hours=max_evidence_age_hours,
        )
    )

    leaks = _require_secret_safe_report(data, path="db_audit")
    if leaks:
        failures.append(f"secret_or_raw_url_fields: {', '.join(leaks[:20])}")
    if failures:
        return fail_check("database capture audit evidence", "; ".join(failures))
    counts = summary.get("normalized_record_counts", {})
    return pass_check("database capture audit evidence", f"events={summary.get('total_events')}, records={counts}")


def check_manual_live_evidence(
    path: Path,
    json_reader: JsonReader,
    *,
    expected_extension_commit: str | None = None,
    now: datetime | None = None,
    max_evidence_age_hours: int = DEFAULT_MAX_EVIDENCE_AGE_HOURS,
) -> PilotCheck:
    data, pending = _json_check(path, json_reader, "manual live browser/platform evidence")
    if pending:
        return pending
    assert data is not None

    missing = [field for field in LIVE_EVIDENCE_REQUIRED_FIELDS if not data.get(field)]
    mismatches = [
        f"{field}={data.get(field)!r}"
        for field, expected in LIVE_EVIDENCE_BOOLEAN_REQUIREMENTS.items()
        if data.get(field) is not expected
    ]
    record_kinds = data.get("normalized_record_kinds")
    if not isinstance(record_kinds, list) or not record_kinds:
        missing.append("normalized_record_kinds")
    if expected_extension_commit and data.get("extension_commit") != expected_extension_commit:
        mismatches.append(f"extension_commit={data.get('extension_commit')!r}, expected={expected_extension_commit!r}")
    freshness_failures = _evidence_freshness_failures(
        field_path="generated_at",
        generated_at=data.get("generated_at"),
        now=now or datetime.now(timezone.utc),
        max_age_hours=max_evidence_age_hours,
    )

    leaks = sorted(set(_scan_live_evidence_value_leaks(data)))
    if missing or mismatches or freshness_failures or leaks:
        detail = "; ".join(
            filter(
                None,
                [
                    f"missing: {', '.join(missing)}" if missing else "",
                    ", ".join(mismatches),
                    ", ".join(freshness_failures),
                    f"secret_or_raw_url_fields: {', '.join(leaks[:20])}" if leaks else "",
                ],
            )
        )
        return fail_check("manual live browser/platform evidence", detail)
    return pass_check("manual live browser/platform evidence", "real browser, platform sample, Settings, and manual-confirmation evidence present")


def run_audit(
    *,
    expected_branch: str = "codex/browser-connector-mvp",
    expected_frontend_url: str | None = None,
    expected_backend_url: str | None = None,
    expected_manifest_path: str | None = None,
    expected_extension_commit: str | None = None,
    staging_probe_path: Path = DEFAULT_STAGING_PROBE,
    db_audit_path: Path = DEFAULT_DB_AUDIT,
    manual_evidence_path: Path = DEFAULT_MANUAL_EVIDENCE,
    max_evidence_age_hours: int = DEFAULT_MAX_EVIDENCE_AGE_HOURS,
    now: datetime | None = None,
    git: GitRunner = run_git,
    read_text: TextReader = read_tracked_text,
    json_reader: JsonReader = read_json,
) -> dict[str, Any]:
    tracked = list_tracked(git)
    extension_commit = expected_extension_commit or current_short_commit(git)
    audit_now = now or datetime.now(timezone.utc)
    checks = [
        check_branch(git, expected_branch),
        check_clean_worktree(git),
        check_required_files(tracked),
        *check_extension_manifest(read_text),
        check_no_platform_write_entrypoints(read_text),
        *check_docs(read_text),
        check_staging_probe(
            staging_probe_path,
            json_reader,
            expected_frontend_url=expected_frontend_url,
            expected_backend_url=expected_backend_url,
            expected_manifest_path=expected_manifest_path,
            now=audit_now,
            max_evidence_age_hours=max_evidence_age_hours,
        ),
        check_db_audit(
            db_audit_path,
            json_reader,
            now=audit_now,
            max_evidence_age_hours=max_evidence_age_hours,
        ),
        check_manual_live_evidence(
            manual_evidence_path,
            json_reader,
            expected_extension_commit=extension_commit,
            now=audit_now,
            max_evidence_age_hours=max_evidence_age_hours,
        ),
    ]
    failures = [check for check in checks if check.status == "fail"]
    pending = [check for check in checks if check.status == "pending_external"]
    return {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "purpose": "browser connector pilot readiness boundary audit",
            "expected_branch": expected_branch,
            "expected_frontend_url": expected_frontend_url,
            "expected_backend_url": expected_backend_url,
            "expected_manifest_path": expected_manifest_path,
            "expected_extension_commit": extension_commit,
            "staging_probe_path": str(staging_probe_path),
            "db_audit_path": str(db_audit_path),
            "manual_evidence_path": str(manual_evidence_path),
            "max_evidence_age_hours": max_evidence_age_hours,
            "secret_values_redacted": True,
        },
        "summary": {
            "local_ready": not failures,
            "pilot_ready": not failures and not pending,
            "check_count": len(checks),
            "failure_count": len(failures),
            "pending_external_count": len(pending),
        },
        "checks": [asdict(check) for check in checks],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-branch", default="codex/browser-connector-mvp")
    parser.add_argument("--expected-frontend-url", default="")
    parser.add_argument("--expected-backend-url", default="")
    parser.add_argument("--expected-manifest-path", default="")
    parser.add_argument("--expected-extension-commit", default="")
    parser.add_argument("--staging-probe", type=Path, default=DEFAULT_STAGING_PROBE)
    parser.add_argument("--db-audit", type=Path, default=DEFAULT_DB_AUDIT)
    parser.add_argument("--manual-evidence", type=Path, default=DEFAULT_MANUAL_EVIDENCE)
    parser.add_argument("--max-evidence-age-hours", type=int, default=DEFAULT_MAX_EVIDENCE_AGE_HOURS)
    parser.add_argument("--require-pilot-ready", action="store_true")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    report = run_audit(
        expected_branch=args.expected_branch,
        expected_frontend_url=args.expected_frontend_url or None,
        expected_backend_url=args.expected_backend_url or None,
        expected_manifest_path=args.expected_manifest_path or None,
        expected_extension_commit=args.expected_extension_commit or None,
        staging_probe_path=args.staging_probe,
        db_audit_path=args.db_audit,
        manual_evidence_path=args.manual_evidence,
        max_evidence_age_hours=args.max_evidence_age_hours,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("AgentX browser connector pilot readiness audit")
    print("=" * 80)
    print(f"local_ready: {report['summary']['local_ready']}")
    print(f"pilot_ready: {report['summary']['pilot_ready']}")
    print(
        "checks: "
        f"{report['summary']['check_count']}  "
        f"failures: {report['summary']['failure_count']}  "
        f"pending_external: {report['summary']['pending_external_count']}"
    )
    for check in report["checks"]:
        print(f"{check['status'].upper()} {check['name']}: {check['detail']}")
    print(f"JSON report: {out_path}")

    if args.require_pilot_ready:
        return 0 if report["summary"]["pilot_ready"] else 1
    return 0 if report["summary"]["local_ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
