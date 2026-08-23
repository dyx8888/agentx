import json

import pytest

from tests.performance import browser_connector_live_evidence_template as template
from tests.performance.browser_connector_pilot_readiness_audit import (
    LIVE_EVIDENCE_BOOLEAN_REQUIREMENTS,
    LIVE_EVIDENCE_REQUIRED_FIELDS,
    check_manual_live_evidence,
)


def test_live_evidence_template_contains_all_readiness_fields():
    data = template.build_template()

    for field in LIVE_EVIDENCE_REQUIRED_FIELDS:
        assert field in data
    for field, expected in LIVE_EVIDENCE_BOOLEAN_REQUIREMENTS.items():
        assert field in data
        assert data["_expected_boolean_values"][field] is expected
    assert "Authorization headers" in data["_do_not_include"]
    assert "raw platform response payloads" in data["_do_not_include"]


def test_live_evidence_template_does_not_pass_until_filled():
    data = template.build_template()

    result = check_manual_live_evidence(
        template.DEFAULT_MANUAL_EVIDENCE,
        lambda _path: data,
    )

    assert result.status == "fail"
    assert "missing" in result.detail


def test_write_template_refuses_to_overwrite(tmp_path):
    out = tmp_path / "browser_connector_live_evidence.json"
    template.write_template(out)

    with pytest.raises(FileExistsError):
        template.write_template(out)


def test_template_cli_writes_secret_safe_json(tmp_path):
    out = tmp_path / "live_evidence.json"

    assert template.main(["--out", str(out)]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))

    serialized = json.dumps(written, ensure_ascii=False).lower()
    assert "actual-cookie-secret" not in serialized
    assert "actual-token-secret" not in serialized
    assert written["normalized_record_kinds"] == []
    assert written["real_chrome_extension_loaded"] is None



def test_live_evidence_template_prefills_safe_staging_metadata():
    data = template.build_template(
        frontend_origin="https://app.example.com/path",
        backend_origin="https://api.example.com",
        extension_commit="abc123",
        test_company_id=42,
        test_user="pilot@example.com",
        staging_probe_report="reports/staging.json",
        db_audit_report="reports/db.json",
        pilot_readiness_report="reports/readiness.json",
    )

    assert data["frontend_origin"] == "https://app.example.com"
    assert data["backend_origin"] == "https://api.example.com"
    assert data["extension_commit"] == "abc123"
    assert data["test_company_id"] == 42
    assert data["test_user"] == "pilot@example.com"
    assert data["_evidence_files"]["staging_probe_report"] == "reports/staging.json"
    assert data["db_audit_report"] == "reports/db.json"
    assert data["real_chrome_extension_loaded"] is None

    result = check_manual_live_evidence(template.DEFAULT_MANUAL_EVIDENCE, lambda _path: data)
    assert result.status == "fail"
    assert "missing" in result.detail


def test_live_evidence_template_rejects_origin_with_query_secret():
    with pytest.raises(ValueError, match="query strings"):
        template.build_template(frontend_origin="https://app.example.com?token=secret")
