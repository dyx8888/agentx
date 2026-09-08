import json
from datetime import datetime, timezone
from pathlib import Path

from tests.performance.browser_connector_pilot_readiness_audit import (
    GitResult,
    REQUIRED_TRACKED_FILES,
    run_audit,
)


AUDIT_NOW = datetime(2026, 8, 13, 1, 0, tzinfo=timezone.utc)


BASE_TEXT = {
    "browser-extension/agentx-connector/manifest.json": json.dumps(
        {
            "manifest_version": 3,
            "host_permissions": ["http://localhost/*", "http://127.0.0.1/*", "https://app.example.com/*", "https://*/*"],
            "permissions": ["activeTab", "scripting", "storage", "tabs"],
            "content_scripts": [
                {
                    "matches": [
                        "https://*/*",
                    ],
                    "js": ["src/content-script.js"],
                }
            ],
        }
    ),
    "backend/app/api/browser_connector.py": "platform_write_operation: false",
    "backend/app/services/browser_connector_business.py": "read_only=true",
    "browser-extension/agentx-connector/src/background.js": "platform_write_operation: false",
    "browser-extension/agentx-connector/src/injected.js": "platform_write_operation: false",
    "frontend/src/pages/SettingsPage.jsx": "浏览器连接器采集 / 只读来源",
    "docs/browser-connector-deployment-runbook-2026-08-13.md": "\n".join(
        [
            "COOKIE_SAMESITE=none",
            "browser_connector_staging_probe.py",
            "browser_connector_db_audit.py",
            "The connector is not ready for real-user pilot use",
        ]
    ),
    "docs/browser-connector-security-boundaries-2026-08-12.md": "\n".join(
        [
            "read-only",
            "must not collect, store, or forward",
            "FEATURE_BROWSER_CONNECTOR_TENANT_IDS",
            "database audit",
        ]
    ),
    "docs/browser-connector-live-validation-and-business-rollout-plan-2026-08-13.md": "\n".join(
        [
            "可交付给用户试用的最低门槛",
            "真实 Chrome 插件链路验收",
            "DB audit",
            "不做平台自动点击",
        ]
    ),
    "docs/browser-connector-normalization-map-2026-08-13.md": "\n".join(
        [
            "creator_profile",
            "knowledge_observation",
            "campaign_metrics",
            "真实 staging/生产候选样本仍需",
        ]
    ),
}


def _fake_git(files=None, dirty="", branch="codex/browser-connector-mvp"):
    tracked = sorted(files or REQUIRED_TRACKED_FILES)

    def run(args):
        key = tuple(args)
        if key == ("ls-files",):
            return GitResult(0, "\n".join(tracked), "")
        if key == ("branch", "--show-current"):
            return GitResult(0, branch, "")
        if key == ("status", "--porcelain=v1"):
            return GitResult(0, dirty, "")
        if key == ("rev-parse", "--short", "HEAD"):
            return GitResult(0, "abc123", "")
        return GitResult(0, "", "")

    return run


def _reader(texts=None):
    values = texts or BASE_TEXT

    def read(path):
        return values[path]

    return read


def _json_reader(values):
    def read(path):
        return values.get(str(path))

    return read


def _passing_external_evidence(tmp_path):
    staging = tmp_path / "browser_connector_staging_probe.json"
    db = tmp_path / "browser_connector_db_audit.json"
    manual = tmp_path / "browser_connector_live_evidence.json"
    values = {
        str(staging): {
            "meta": {
                "generated_at": "2026-08-13T00:00:00+0800",
                "frontend_url": "https://app.example.com",
                "backend_url": "https://api.example.com",
                "manifest_path": "C:\\temp\\agentx-connector\\manifest.json",
                "secret_values_redacted": True,
            },
            "summary": {"passed": True, "check_count": 7},
        },
        str(db): {
            "meta": {
                "generated_at": "2026-08-13T00:01:00+0800",
                "company_id": 42,
                "read_only": True,
                "secret_values_redacted": True,
            },
            "summary": {
                "passed": True,
                "total_events": 2,
                "normalized_record_counts": {"creator_profile": 1, "campaign_metrics": 1},
            }
        },
        str(manual): {
            "generated_at": "2026-08-13T00:02:00+0800",
            "frontend_origin": "https://app.example.com",
            "backend_origin": "https://api.example.com",
            "extension_commit": "abc123",
            "browser": "Chrome 127",
            "test_company_id": 42,
            "test_user": "pilot@example.com",
            "platform_page": "https://buyin.jinritemai.com/dashboard",
            "matched_allowlist_rule": "buyin-api",
            "ingest_authenticated_result": "202",
            "stored_event_id": 101,
            "normalized_record_kinds": ["creator_profile"],
            "settings_source_counts": {"creator_profile": 1},
            "real_chrome_extension_loaded": True,
            "real_platform_sample_collected": True,
            "sensitive_value_scan_passed": True,
            "platform_write_operation_observed": False,
            "settings_review_completed": True,
            "business_import_requires_manual_confirmation": True,
        },
    }
    return staging, db, manual, values


def test_pilot_readiness_audit_local_ready_with_external_pending():
    report = run_audit(git=_fake_git(), read_text=_reader(), json_reader=_json_reader({}))

    assert report["summary"]["local_ready"] is True
    assert report["summary"]["pilot_ready"] is False
    pending = {check["name"] for check in report["checks"] if check["status"] == "pending_external"}
    assert "staging CORS/Auth probe evidence" in pending
    assert "database capture audit evidence" in pending
    assert "manual live browser/platform evidence" in pending


def test_pilot_readiness_audit_passes_when_all_external_evidence_passes(tmp_path):
    staging, db, manual, values = _passing_external_evidence(tmp_path)

    report = run_audit(
        staging_probe_path=staging,
        db_audit_path=db,
        manual_evidence_path=manual,
        git=_fake_git(),
        read_text=_reader(),
        json_reader=_json_reader(values),
        now=AUDIT_NOW,
    )

    assert report["summary"]["local_ready"] is True
    assert report["summary"]["pilot_ready"] is True


def test_pilot_readiness_audit_fails_stale_staging_probe(tmp_path):
    staging, db, manual, values = _passing_external_evidence(tmp_path)
    values[str(staging)] = {
        **values[str(staging)],
        "meta": {**values[str(staging)]["meta"], "generated_at": "2026-08-08T00:00:00+0800"},
    }

    report = run_audit(
        staging_probe_path=staging,
        db_audit_path=db,
        manual_evidence_path=manual,
        git=_fake_git(),
        read_text=_reader(),
        json_reader=_json_reader(values),
        now=AUDIT_NOW,
    )

    staging_check = next(check for check in report["checks"] if check["name"] == "staging CORS/Auth probe evidence")
    assert report["summary"]["pilot_ready"] is False
    assert staging_check["status"] == "fail"
    assert "meta.generated_at_stale" in staging_check["detail"]


def test_pilot_readiness_audit_fails_stale_db_audit(tmp_path):
    staging, db, manual, values = _passing_external_evidence(tmp_path)
    values[str(db)] = {
        **values[str(db)],
        "meta": {**values[str(db)]["meta"], "generated_at": "2026-08-08T00:00:00+0800"},
    }

    report = run_audit(
        staging_probe_path=staging,
        db_audit_path=db,
        manual_evidence_path=manual,
        git=_fake_git(),
        read_text=_reader(),
        json_reader=_json_reader(values),
        now=AUDIT_NOW,
    )

    db_check = next(check for check in report["checks"] if check["name"] == "database capture audit evidence")
    assert report["summary"]["pilot_ready"] is False
    assert db_check["status"] == "fail"
    assert "meta.generated_at_stale" in db_check["detail"]


def test_pilot_readiness_audit_fails_stale_manual_evidence(tmp_path):
    staging, db, manual, values = _passing_external_evidence(tmp_path)
    values[str(manual)] = {**values[str(manual)], "generated_at": "2026-08-08T00:00:00+0800"}

    report = run_audit(
        staging_probe_path=staging,
        db_audit_path=db,
        manual_evidence_path=manual,
        git=_fake_git(),
        read_text=_reader(),
        json_reader=_json_reader(values),
        now=AUDIT_NOW,
    )

    manual_check = next(check for check in report["checks"] if check["name"] == "manual live browser/platform evidence")
    assert report["summary"]["pilot_ready"] is False
    assert manual_check["status"] == "fail"
    assert "generated_at_stale" in manual_check["detail"]


def test_pilot_readiness_audit_fails_manual_evidence_without_timestamp(tmp_path):
    staging, db, manual, values = _passing_external_evidence(tmp_path)
    values[str(manual)] = {key: value for key, value in values[str(manual)].items() if key != "generated_at"}

    report = run_audit(
        staging_probe_path=staging,
        db_audit_path=db,
        manual_evidence_path=manual,
        git=_fake_git(),
        read_text=_reader(),
        json_reader=_json_reader(values),
        now=AUDIT_NOW,
    )

    manual_check = next(check for check in report["checks"] if check["name"] == "manual live browser/platform evidence")
    assert report["summary"]["pilot_ready"] is False
    assert manual_check["status"] == "fail"
    assert "missing: generated_at" in manual_check["detail"]
    assert "generated_at_invalid_or_missing" in manual_check["detail"]


def test_pilot_readiness_audit_does_not_leak_invalid_timestamp_secret(tmp_path):
    staging, db, manual, values = _passing_external_evidence(tmp_path)
    values[str(manual)] = {**values[str(manual)], "generated_at": "Authorization: Bearer secret-token-value"}

    report = run_audit(
        staging_probe_path=staging,
        db_audit_path=db,
        manual_evidence_path=manual,
        git=_fake_git(),
        read_text=_reader(),
        json_reader=_json_reader(values),
        now=AUDIT_NOW,
    )

    manual_check = next(check for check in report["checks"] if check["name"] == "manual live browser/platform evidence")
    assert report["summary"]["pilot_ready"] is False
    assert "generated_at_invalid_or_missing" in manual_check["detail"]
    assert "secret_or_raw_url_fields" in manual_check["detail"]
    assert "secret-token-value" not in manual_check["detail"]


def test_pilot_readiness_audit_fails_staging_probe_without_secret_safe_meta(tmp_path):
    staging, db, manual, values = _passing_external_evidence(tmp_path)
    values[str(staging)] = {
        **values[str(staging)],
        "meta": {**values[str(staging)]["meta"], "secret_values_redacted": False},
    }

    report = run_audit(
        staging_probe_path=staging,
        db_audit_path=db,
        manual_evidence_path=manual,
        git=_fake_git(),
        read_text=_reader(),
        json_reader=_json_reader(values),
        now=AUDIT_NOW,
    )

    staging_check = next(check for check in report["checks"] if check["name"] == "staging CORS/Auth probe evidence")
    assert report["summary"]["pilot_ready"] is False
    assert staging_check["status"] == "fail"
    assert "meta.secret_values_redacted" in staging_check["detail"]


def test_pilot_readiness_audit_fails_db_audit_when_not_read_only(tmp_path):
    staging, db, manual, values = _passing_external_evidence(tmp_path)
    values[str(db)] = {
        **values[str(db)],
        "meta": {**values[str(db)]["meta"], "read_only": False},
    }

    report = run_audit(
        staging_probe_path=staging,
        db_audit_path=db,
        manual_evidence_path=manual,
        git=_fake_git(),
        read_text=_reader(),
        json_reader=_json_reader(values),
        now=AUDIT_NOW,
    )

    db_check = next(check for check in report["checks"] if check["name"] == "database capture audit evidence")
    assert report["summary"]["pilot_ready"] is False
    assert db_check["status"] == "fail"
    assert "meta.read_only" in db_check["detail"]


def test_pilot_readiness_audit_fails_manual_evidence_for_wrong_extension_commit(tmp_path):
    staging, db, manual, values = _passing_external_evidence(tmp_path)
    values[str(manual)] = {**values[str(manual)], "extension_commit": "stale999"}

    report = run_audit(
        staging_probe_path=staging,
        db_audit_path=db,
        manual_evidence_path=manual,
        git=_fake_git(),
        read_text=_reader(),
        json_reader=_json_reader(values),
        now=AUDIT_NOW,
    )

    manual_check = next(check for check in report["checks"] if check["name"] == "manual live browser/platform evidence")
    assert report["summary"]["pilot_ready"] is False
    assert manual_check["status"] == "fail"
    assert "extension_commit" in manual_check["detail"]


def test_pilot_readiness_audit_fails_missing_required_connector_file():
    files = set(REQUIRED_TRACKED_FILES)
    files.remove("browser-extension/agentx-connector/src/injected.js")

    report = run_audit(git=_fake_git(files=files), read_text=_reader(), json_reader=_json_reader({}))

    failed = {check["name"] for check in report["checks"] if check["status"] == "fail"}
    assert "connector artifacts tracked" in failed
    assert report["summary"]["local_ready"] is False


def test_pilot_readiness_audit_fails_unsafe_broad_extension_permission():
    texts = {
        **BASE_TEXT,
        "browser-extension/agentx-connector/manifest.json": json.dumps(
            {
                "manifest_version": 3,
                "host_permissions": ["https://*/*", "http://*/*"],
                "permissions": ["activeTab", "scripting", "storage", "tabs", "cookies"],
                "content_scripts": [{"matches": ["https://*/*"], "js": []}],
            }
        ),
    }

    report = run_audit(git=_fake_git(), read_text=_reader(texts), json_reader=_json_reader({}))

    failed = {check["name"] for check in report["checks"] if check["status"] == "fail"}
    assert "extension permission boundary" in failed
    assert report["summary"]["local_ready"] is False


def test_pilot_readiness_audit_fails_platform_write_marker():
    texts = {
        **BASE_TEXT,
        "backend/app/services/browser_connector_business.py": "send_message(); platform_write_operation: true",
    }

    report = run_audit(git=_fake_git(), read_text=_reader(texts), json_reader=_json_reader({}))

    failed = {check["name"] for check in report["checks"] if check["status"] == "fail"}
    assert "read-only safety scan" in failed
    assert report["summary"]["local_ready"] is False


def test_pilot_readiness_audit_fails_manual_evidence_with_platform_write(tmp_path):
    staging, db, manual, values = _passing_external_evidence(tmp_path)
    values[str(manual)] = {**values[str(manual)], "platform_write_operation_observed": True}

    report = run_audit(
        staging_probe_path=staging,
        db_audit_path=db,
        manual_evidence_path=manual,
        git=_fake_git(),
        read_text=_reader(),
        json_reader=_json_reader(values),
        now=AUDIT_NOW,
    )

    failed = {check["name"] for check in report["checks"] if check["status"] == "fail"}
    assert "manual live browser/platform evidence" in failed
    assert report["summary"]["pilot_ready"] is False


def test_pilot_readiness_audit_fails_manual_evidence_with_secret_value(tmp_path):
    staging, db, manual, values = _passing_external_evidence(tmp_path)
    values[str(manual)] = {**values[str(manual)], "notes": "Authorization: Bearer secret-token-value"}

    report = run_audit(
        staging_probe_path=staging,
        db_audit_path=db,
        manual_evidence_path=manual,
        git=_fake_git(),
        read_text=_reader(),
        json_reader=_json_reader(values),
        now=AUDIT_NOW,
    )

    failed = {check["name"] for check in report["checks"] if check["status"] == "fail"}
    manual_check = next(check for check in report["checks"] if check["name"] == "manual live browser/platform evidence")
    assert "manual live browser/platform evidence" in failed
    assert "secret_or_raw_url_fields" in manual_check["detail"]
    assert "secret-token-value" not in manual_check["detail"]


def test_pilot_readiness_audit_fails_manual_evidence_with_raw_query_url(tmp_path):
    staging, db, manual, values = _passing_external_evidence(tmp_path)
    values[str(manual)] = {
        **values[str(manual)],
        "platform_page": "https://buyin.jinritemai.com/square_pc_api/square/search_feed_author?token=secret",
    }

    report = run_audit(
        staging_probe_path=staging,
        db_audit_path=db,
        manual_evidence_path=manual,
        git=_fake_git(),
        read_text=_reader(),
        json_reader=_json_reader(values),
        now=AUDIT_NOW,
    )

    manual_check = next(check for check in report["checks"] if check["name"] == "manual live browser/platform evidence")
    assert report["summary"]["pilot_ready"] is False
    assert "secret_or_raw_url_fields" in manual_check["detail"]
    assert "token=secret" not in manual_check["detail"]
