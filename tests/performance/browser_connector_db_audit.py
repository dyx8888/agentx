"""Read-only database audit for AgentX browser connector capture evidence.

This script inspects stored ``browser_connector_events`` rows after a real
staging browser-extension capture. It does not mutate database state and it
does not print database URLs, cookies, tokens, or stored payload values.

Usage:
    python tests/performance/browser_connector_db_audit.py --company-id 42

    python tests/performance/browser_connector_db_audit.py \
      --database-url postgresql://... \
      --company-id 42 \
      --out tests/reports/browser_connector_db_audit.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session, sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
DEFAULT_OUT = PROJECT_ROOT / "tests" / "reports" / "browser_connector_db_audit.json"
DEFAULT_SQLITE_DB = BACKEND_ROOT / "data" / "agentx.db"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database.models import BrowserConnectorEvent  # noqa: E402
from app.services.browser_connector_capture import SENSITIVE_STORAGE_MARKERS  # noqa: E402
from app.services.browser_connector_normalizer import normalize_browser_connector_event  # noqa: E402


HASH_RE = re.compile(r"^[a-f0-9]{64}$")
RAW_URL_RE = re.compile(r"https?://|\?.+=|&.+=|square_pc_api", re.IGNORECASE)


@dataclass(frozen=True)
class AuditCheck:
    name: str
    passed: bool
    detail: str


def _default_database_url() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return database_url
    db_path = Path(os.getenv("BROWSER_CONNECTOR_DB_AUDIT_SQLITE", str(DEFAULT_SQLITE_DB)))
    return f"sqlite:///{db_path}"


def _safe_database_meta(database_url: str) -> dict[str, Any]:
    parsed = urlparse(database_url)
    return {
        "scheme": parsed.scheme or "unknown",
        "host_present": bool(parsed.hostname),
        "database_name_present": bool(parsed.path and parsed.path != "/"),
    }


def _load_json(raw_json: str) -> Any:
    try:
        return json.loads(raw_json)
    except (TypeError, json.JSONDecodeError):
        return None


def _scan_sensitive_markers(value: Any, *, path: str = "payload") -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    markers = tuple(str(marker).lower() for marker in SENSITIVE_STORAGE_MARKERS)

    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized_key = key.lower().replace("_", "").replace("-", "").replace(".", "")
            for marker in markers:
                if marker in normalized_key:
                    findings.append({"path": f"{path}.{key}", "marker": marker})
            findings.extend(_scan_sensitive_markers(child, path=f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_scan_sensitive_markers(child, path=f"{path}[{index}]"))
    elif isinstance(value, str):
        lowered = value.lower()
        for marker in markers:
            if marker in lowered:
                findings.append({"path": path, "marker": marker})

    return findings


def _event_metadata_contains_raw_url(event: BrowserConnectorEvent) -> bool:
    metadata = {
        "source": event.source,
        "platform": event.platform,
        "matched_rule": event.matched_rule,
        "api_url_hash": event.api_url_hash,
        "payload_hash": event.payload_hash,
        "api_method": event.api_method,
        "response_mime": event.response_mime,
    }
    return bool(RAW_URL_RE.search(json.dumps(metadata, ensure_ascii=False)))


def _kind_value(kind: Any) -> str:
    return getattr(kind, "value", str(kind))


def run_audit(
    db: Session,
    *,
    company_id: int,
    limit: int = 200,
    sample_size: int = 20,
) -> dict[str, Any]:
    """Inspect connector captures for one tenant without writing to the database."""
    total_events = (
        db.query(func.count(BrowserConnectorEvent.id))
        .filter(BrowserConnectorEvent.company_id == company_id)
        .scalar()
        or 0
    )
    events = (
        db.query(BrowserConnectorEvent)
        .filter(BrowserConnectorEvent.company_id == company_id)
        .order_by(BrowserConnectorEvent.created_at.desc(), BrowserConnectorEvent.id.desc())
        .limit(limit)
        .all()
    )

    sensitive_findings: list[dict[str, Any]] = []
    invalid_hash_events: list[int] = []
    raw_url_metadata_events: list[int] = []
    invalid_json_events: list[int] = []
    normalized_counts: dict[str, int] = {}
    sample_records: list[dict[str, Any]] = []

    for event in events:
        event_id = int(event.id or 0)
        if not HASH_RE.match(str(event.api_url_hash or "")) or not HASH_RE.match(str(event.payload_hash or "")):
            invalid_hash_events.append(event_id)
        if _event_metadata_contains_raw_url(event):
            raw_url_metadata_events.append(event_id)

        payload = _load_json(event.sanitized_payload_json)
        if payload is None:
            invalid_json_events.append(event_id)
        else:
            for finding in _scan_sensitive_markers(payload):
                sensitive_findings.append({"event_id": event_id, **finding})

        try:
            records = normalize_browser_connector_event(event)
        except Exception as exc:  # pragma: no cover - defensive for staging evidence
            records = []
            error_kind = f"normalization_error:{type(exc).__name__}"
            normalized_counts[error_kind] = normalized_counts.get(error_kind, 0) + 1

        for record in records:
            kind = _kind_value(record.kind)
            normalized_counts[kind] = normalized_counts.get(kind, 0) + 1
            if len(sample_records) < sample_size:
                sample_records.append(
                    {
                        "source_event_id": record.source_event_id,
                        "kind": kind,
                        "platform": record.platform,
                        "confidence": record.confidence,
                    }
                )

    checks = [
        AuditCheck(
            "tenant has connector events",
            bool(total_events),
            f"{total_events} event(s) found for company_id {company_id}",
        ),
        AuditCheck(
            "sampled rows have valid hashes",
            not invalid_hash_events,
            "api_url_hash and payload_hash are 64-char sha256 hex values"
            if not invalid_hash_events
            else f"invalid hash format on event ids: {invalid_hash_events[:20]}",
        ),
        AuditCheck(
            "sampled metadata has no raw api url",
            not raw_url_metadata_events,
            "metadata stores hashes/rules only, not raw API URLs or query strings"
            if not raw_url_metadata_events
            else f"raw URL-like metadata on event ids: {raw_url_metadata_events[:20]}",
        ),
        AuditCheck(
            "stored payload json parses",
            not invalid_json_events,
            "all sampled sanitized payloads parsed as JSON"
            if not invalid_json_events
            else f"invalid JSON on event ids: {invalid_json_events[:20]}",
        ),
        AuditCheck(
            "stored payloads have no sensitive markers",
            not sensitive_findings,
            "no cookie/token/password/captcha/payment markers found"
            if not sensitive_findings
            else f"{len(sensitive_findings)} sensitive marker finding(s)",
        ),
        AuditCheck(
            "normalization produces auditable record kinds",
            bool(normalized_counts),
            f"record kinds: {normalized_counts}" if normalized_counts else "no normalized records produced",
        ),
    ]

    failures = [check for check in checks if not check.passed]
    return {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "company_id": company_id,
            "limit": limit,
            "sample_size": sample_size,
            "read_only": True,
            "secret_values_redacted": True,
            "scope": (
                "browser connector database audit for stored sanitized events; "
                "does not validate live browser login or real platform capture by itself"
            ),
        },
        "summary": {
            "passed": not failures,
            "check_count": len(checks),
            "failure_count": len(failures),
            "total_events": int(total_events),
            "sampled_events": len(events),
            "normalized_record_counts": normalized_counts,
        },
        "checks": [asdict(check) for check in checks],
        "findings": {
            "sensitive_markers": sensitive_findings[:50],
            "invalid_hash_event_ids": invalid_hash_events[:50],
            "raw_url_metadata_event_ids": raw_url_metadata_events[:50],
            "invalid_json_event_ids": invalid_json_events[:50],
        },
        "samples": {
            "normalized_records": sample_records,
        },
    }


def run_audit_from_database_url(
    database_url: str,
    *,
    company_id: int,
    limit: int = 200,
    sample_size: int = 20,
) -> dict[str, Any]:
    engine = create_engine(database_url, pool_pre_ping=True, echo=False)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with SessionLocal() as db:
        report = run_audit(db, company_id=company_id, limit=limit, sample_size=sample_size)
    report["meta"]["database"] = _safe_database_meta(database_url)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-id", required=True, type=int, help="Tenant/company id to inspect")
    parser.add_argument("--database-url", default="", help="Optional DATABASE_URL override; never printed")
    parser.add_argument("--limit", type=int, default=200, help="Maximum tenant rows to inspect")
    parser.add_argument("--sample-size", type=int, default=20, help="Maximum normalized sample records in report")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Secret-safe JSON report path")
    args = parser.parse_args(argv)

    database_url = args.database_url.strip() or _default_database_url()
    report = run_audit_from_database_url(
        database_url,
        company_id=args.company_id,
        limit=args.limit,
        sample_size=args.sample_size,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("AgentX browser connector database audit")
    print("=" * 80)
    print(f"passed: {report['summary']['passed']}")
    print(f"company_id: {args.company_id}")
    print(f"events: {report['summary']['sampled_events']} sampled / {report['summary']['total_events']} total")
    print(f"checks: {report['summary']['check_count']}  failures: {report['summary']['failure_count']}")
    print(f"record kinds: {report['summary']['normalized_record_counts']}")
    for check in report["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        print(f"{status} {check['name']}: {check['detail']}")
    print(f"JSON report: {out_path}")
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
