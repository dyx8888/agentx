import json

import pytest

from tests.performance import browser_connector_evidence_bundle as bundle


def _runner(calls, *, fail_step=None):
    def run(args):
        calls.append(args)
        text = " ".join(args)
        if fail_step and fail_step in text:
            return bundle.CommandResult(1, "", "failed")
        return bundle.CommandResult(0, "ok", "")

    return run


def test_evidence_bundle_runs_expected_commands_and_redacts_database_url(tmp_path):
    calls = []
    secret_db_url = "postgresql://agentx:secret-password@db.example.com/agentx"

    report = bundle.run_bundle(
        frontend_url="https://app.example.com",
        backend_url="https://api.example.com",
        company_id=42,
        report_dir=tmp_path,
        database_url=secret_db_url,
        expected_extension_commit="abc123",
        command_runner=_runner(calls),
    )

    assert report["summary"]["passed"] is True
    assert [step["name"] for step in report["steps"]] == [
        "deployment manifest",
        "staging probe",
        "database audit",
        "manual live evidence template",
        "pilot readiness audit",
    ]
    assert report["meta"]["database_url_provided"] is True
    assert "secret-password" not in json.dumps(report, ensure_ascii=False)
    assert [command["name"] for command in report["commands"]] == [
        "deployment manifest",
        "staging probe",
        "database audit",
        "manual live evidence template",
        "pilot readiness audit",
    ]
    db_command = next(command for command in report["commands"] if command["name"] == "database audit")
    assert "--database-url" in db_command["args"]
    assert "<redacted>" in db_command["args"]
    assert secret_db_url not in db_command["args"]
    assert any("build_deployment_manifest.py" in " ".join(call) for call in calls)
    assert any("browser_connector_staging_probe.py" in " ".join(call) for call in calls)
    assert any("browser_connector_db_audit.py" in " ".join(call) for call in calls)
    template_call = next(call for call in calls if "browser_connector_live_evidence_template.py" in " ".join(call))
    assert "--frontend-origin" in template_call
    assert "https://app.example.com" in template_call
    assert "--extension-commit" in template_call
    assert "abc123" in template_call
    assert any("browser_connector_pilot_readiness_audit.py" in " ".join(call) for call in calls)


def test_evidence_bundle_rejects_origin_with_query_string(tmp_path):
    with pytest.raises(ValueError, match="query strings"):
        bundle.run_bundle(
            frontend_url="https://app.example.com?token=secret",
            backend_url="https://api.example.com",
            company_id=42,
            report_dir=tmp_path,
            command_runner=_runner([]),
        )


def test_evidence_bundle_dry_run_plans_without_executing_commands(tmp_path):
    calls = []
    secret_db_url = "postgresql://agentx:secret-password@db.example.com/agentx"

    report = bundle.run_bundle(
        frontend_url="https://app.example.com",
        backend_url="https://api.example.com",
        company_id=42,
        report_dir=tmp_path,
        database_url=secret_db_url,
        dry_run=True,
        command_runner=_runner(calls),
    )

    assert calls == []
    assert report["meta"]["dry_run"] is True
    assert report["summary"]["passed"] is True
    assert report["summary"]["planned_count"] == 5
    assert {step["status"] for step in report["steps"]} == {"planned"}
    assert len(report["commands"]) == 5
    assert any("<redacted>" in command["args"] for command in report["commands"])
    assert "secret-password" not in json.dumps(report, ensure_ascii=False)


def test_evidence_bundle_does_not_overwrite_existing_manual_evidence(tmp_path):
    calls = []
    (tmp_path / "browser_connector_live_evidence.json").write_text("{}", encoding="utf-8")

    report = bundle.run_bundle(
        frontend_url="https://app.example.com",
        backend_url="https://api.example.com",
        company_id=42,
        report_dir=tmp_path,
        command_runner=_runner(calls),
    )

    template_steps = [step for step in report["steps"] if step["name"] == "manual live evidence template"]
    assert template_steps == [
        {
            "name": "manual live evidence template",
            "status": "skipped",
            "detail": "existing live evidence file kept",
        }
    ]
    assert not any("browser_connector_live_evidence_template.py" in " ".join(call) for call in calls)


def test_evidence_bundle_fails_fast_when_staging_probe_fails(tmp_path):
    calls = []

    report = bundle.run_bundle(
        frontend_url="https://app.example.com",
        backend_url="https://api.example.com",
        company_id=42,
        report_dir=tmp_path,
        command_runner=_runner(calls, fail_step="browser_connector_staging_probe.py"),
    )

    assert report["summary"]["passed"] is False
    assert report["summary"]["failure_count"] == 1
    steps = {step["name"]: step["status"] for step in report["steps"]}
    assert steps["staging probe"] == "fail"
    assert steps["database audit"] == "skipped"
    assert steps["pilot readiness audit"] == "skipped"
