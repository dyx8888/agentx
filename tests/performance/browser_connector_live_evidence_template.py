"""Generate the manual live-evidence JSON template for browser connector pilots.

The generated file is intentionally not passing evidence. It contains empty
fields and null booleans so a pilot readiness audit fails until a tester fills
it from a real Chrome extension session and a real platform page.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.performance.browser_connector_pilot_readiness_audit import (
    DEFAULT_MANUAL_EVIDENCE,
    LIVE_EVIDENCE_BOOLEAN_REQUIREMENTS,
    LIVE_EVIDENCE_REQUIRED_FIELDS,
)


DO_NOT_INCLUDE = (
    "AgentX auth cookie values",
    "platform cookies",
    "Authorization headers",
    "platform tokens or API keys",
    "passwords",
    "captcha or verification codes",
    "payment or bank-card data",
    "raw platform response payloads",
    "raw API URLs containing query strings",
)


def _safe_origin(value: str, *, name: str) -> str:
    value = value.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"{name} must include scheme and host")
    if parsed.username or parsed.password:
        raise ValueError(f"{name} must not include credentials")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{name} must not include query strings or fragments")
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


def build_template(
    *,
    generated_at: str = "",
    frontend_origin: str = "",
    backend_origin: str = "",
    extension_commit: str = "",
    test_company_id: int | None = None,
    test_user: str = "",
    staging_probe_report: str = "tests/reports/browser_connector_staging_probe.json",
    db_audit_report: str = "tests/reports/browser_connector_db_audit.json",
    pilot_readiness_report: str = "tests/reports/browser_connector_pilot_readiness_audit.json",
) -> dict[str, Any]:
    safe_frontend_origin = _safe_origin(frontend_origin, name="frontend_origin") if frontend_origin else ""
    safe_backend_origin = _safe_origin(backend_origin, name="backend_origin") if backend_origin else ""
    template: dict[str, Any] = {
        "_instructions": (
            "Fill this from a real staging browser-extension validation only. "
            "Do not paste secrets, cookies, Authorization headers, tokens, passwords, "
            "captcha values, payment data, raw platform payloads, or raw query strings."
        ),
        "_do_not_include": list(DO_NOT_INCLUDE),
        "_expected_boolean_values": dict(LIVE_EVIDENCE_BOOLEAN_REQUIREMENTS),
        "_evidence_files": {
            "staging_probe_report": staging_probe_report,
            "db_audit_report": db_audit_report,
            "pilot_readiness_report": pilot_readiness_report,
        },
    }
    for field in LIVE_EVIDENCE_REQUIRED_FIELDS:
        if field == "normalized_record_kinds":
            template[field] = []
        elif field == "settings_source_counts":
            template[field] = {}
        else:
            template[field] = ""
    for field in LIVE_EVIDENCE_BOOLEAN_REQUIREMENTS:
        template[field] = None
    template.update(
        {
            "cors_preflight_allowed_origin_result": "",
            "cors_negative_origin_result": "",
            "cookie_flags_observed": "",
            "ingest_unauthenticated_result": "",
            "db_audit_report": db_audit_report,
            "sensitive_value_scan_result": "",
            "tester": "",
            "notes": "",
        }
    )
    template["generated_at"] = generated_at.strip()
    template["frontend_origin"] = safe_frontend_origin
    template["backend_origin"] = safe_backend_origin
    template["extension_commit"] = extension_commit.strip()
    if test_company_id is not None:
        template["test_company_id"] = test_company_id
    template["test_user"] = test_user.strip()
    return template


def write_template(path: Path, *, overwrite: bool = False, template_data: dict[str, Any] | None = None) -> Path:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing live evidence template: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(template_data or build_template(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_MANUAL_EVIDENCE)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--frontend-origin", default="")
    parser.add_argument("--backend-origin", default="")
    parser.add_argument("--extension-commit", default="")
    parser.add_argument("--test-company-id", type=int, default=None)
    parser.add_argument("--test-user", default="")
    parser.add_argument("--staging-probe-report", default="tests/reports/browser_connector_staging_probe.json")
    parser.add_argument("--db-audit-report", default="tests/reports/browser_connector_db_audit.json")
    parser.add_argument("--pilot-readiness-report", default="tests/reports/browser_connector_pilot_readiness_audit.json")
    args = parser.parse_args(argv)

    try:
        template_data = build_template(
            generated_at=args.generated_at,
            frontend_origin=args.frontend_origin,
            backend_origin=args.backend_origin,
            extension_commit=args.extension_commit,
            test_company_id=args.test_company_id,
            test_user=args.test_user,
            staging_probe_report=args.staging_probe_report,
            db_audit_report=args.db_audit_report,
            pilot_readiness_report=args.pilot_readiness_report,
        )
        out_path = write_template(args.out, overwrite=args.overwrite, template_data=template_data)
    except (FileExistsError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("AgentX browser connector live evidence template")
    print("=" * 80)
    print(f"template: {out_path}")
    print("Fill this file only after real staging Chrome/platform validation.")
    print("Then run browser_connector_pilot_readiness_audit.py --require-pilot-ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

