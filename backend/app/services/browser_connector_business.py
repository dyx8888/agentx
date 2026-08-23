"""Business adapters for normalized browser connector records.

These adapters are intentionally explicit and human-triggered. They never mutate
third-party ecommerce platforms and do not run from the ingest path.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.database.models import BrowserConnectorEvent, KolProfile
from app.services.browser_connector_normalizer import normalize_browser_connector_event
from app.services.browser_connector_schemas import (
    BrowserConnectorRecordKind,
    NormalizedBrowserConnectorRecord,
)


KnowledgeAddFunc = Callable[..., str]


@dataclass
class BrowserConnectorImportResult:
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    dry_run: bool = True
    records: list[dict[str, Any]] = field(default_factory=list)
    doc_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def list_connector_business_records(
    db: Session,
    *,
    company_id: int,
    kind: BrowserConnectorRecordKind | None = None,
    event_ids: list[int] | None = None,
    limit: int = 50,
) -> list[NormalizedBrowserConnectorRecord]:
    """Return normalized connector records scoped to one tenant."""
    records: list[NormalizedBrowserConnectorRecord] = []
    for event in _query_events(db, company_id=company_id, event_ids=event_ids, limit=limit):
        for record in normalize_browser_connector_event(event):
            if kind is None or record.kind == kind:
                records.append(record)
    return records


def import_connector_creators_to_kols(
    db: Session,
    *,
    company_id: int,
    event_ids: list[int] | None = None,
    dry_run: bool = True,
    limit: int = 50,
) -> BrowserConnectorImportResult:
    """Import normalized creator records into the tenant KOL library after user confirmation."""
    result = BrowserConnectorImportResult(dry_run=dry_run)
    records = list_connector_business_records(
        db,
        company_id=company_id,
        kind=BrowserConnectorRecordKind.CREATOR_PROFILE,
        event_ids=event_ids,
        limit=limit,
    )

    for normalized in records:
        payload = normalized.record
        name = str(payload.get("name") or "").strip()
        platform = str(payload.get("platform") or normalized.platform or "").strip()
        platform_uid = str(payload.get("platform_uid") or "").strip()
        if not name or not platform or not platform_uid:
            result.skipped += 1
            result.errors.append(f"event {normalized.source_event_id}: missing creator identity")
            continue

        existing = (
            db.query(KolProfile)
            .filter(
                KolProfile.company_id == company_id,
                KolProfile.platform == platform,
                KolProfile.platform_uid == platform_uid,
            )
            .first()
        )
        if existing:
            result.updated += 1
        else:
            result.imported += 1

        result.records.append(normalized.to_dict())
        if dry_run:
            continue

        values = _kol_profile_values(company_id, payload, normalized)
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
        else:
            db.add(KolProfile(**values))

    if not dry_run:
        db.commit()

    return result


def import_connector_knowledge_observations(
    db: Session,
    *,
    company_id: int,
    add_knowledge_func: KnowledgeAddFunc,
    event_ids: list[int] | None = None,
    dry_run: bool = True,
    limit: int = 50,
) -> BrowserConnectorImportResult:
    """Import normalized knowledge observations after user confirmation."""
    result = BrowserConnectorImportResult(dry_run=dry_run)
    records = list_connector_business_records(
        db,
        company_id=company_id,
        kind=BrowserConnectorRecordKind.KNOWLEDGE_OBSERVATION,
        event_ids=event_ids,
        limit=limit,
    )

    for normalized in records:
        payload = normalized.record
        content = str(payload.get("content") or "").strip()
        if not content:
            result.skipped += 1
            result.errors.append(f"event {normalized.source_event_id}: missing knowledge content")
            continue

        result.imported += 1
        result.records.append(normalized.to_dict())
        if dry_run:
            continue

        metadata = {
            "category": "browser_connector",
            "scenario": "connector_capture",
            "source": "browser_connector",
            "data_source": "browser_connector",
            "source_note": payload.get("source_note") or "",
            "source_url_hash": payload.get("source_url_hash") or "",
            "title": payload.get("title") or "",
            "external_id": f"browser_connector_event:{normalized.source_event_id}",
            "tags": payload.get("tags") or ["browser_connector", normalized.platform],
        }
        try:
            doc_id = _extract_doc_id(
                add_knowledge_func(
                    text=content,
                    metadata=metadata,
                    company_id=str(company_id),
                )
            )
            result.doc_ids.append(doc_id)
        except Exception as exc:
            result.imported -= 1
            result.skipped += 1
            result.errors.append(f"event {normalized.source_event_id}: {exc}")

    return result


def list_connector_campaign_snapshots(
    db: Session,
    *,
    company_id: int,
    event_ids: list[int] | None = None,
    limit: int = 50,
) -> list[NormalizedBrowserConnectorRecord]:
    """Return read-only campaign metric snapshots for analysis."""
    return list_connector_business_records(
        db,
        company_id=company_id,
        kind=BrowserConnectorRecordKind.CAMPAIGN_METRICS,
        event_ids=event_ids,
        limit=limit,
    )


def _query_events(
    db: Session,
    *,
    company_id: int,
    event_ids: list[int] | None,
    limit: int,
) -> list[BrowserConnectorEvent]:
    query = db.query(BrowserConnectorEvent).filter(BrowserConnectorEvent.company_id == company_id)
    if event_ids:
        query = query.filter(BrowserConnectorEvent.id.in_(event_ids))
    return (
        query.order_by(BrowserConnectorEvent.created_at.desc(), BrowserConnectorEvent.id.desc())
        .limit(limit)
        .all()
    )


def _kol_profile_values(
    company_id: int,
    payload: dict[str, Any],
    normalized: NormalizedBrowserConnectorRecord,
) -> dict[str, Any]:
    now = datetime.utcnow()
    source_note = payload.get("source_note") or f"browser_connector_event:{normalized.source_event_id}"
    return {
        "company_id": company_id,
        "name": str(payload["name"]).strip(),
        "platform": str(payload.get("platform") or normalized.platform).strip(),
        "platform_uid": str(payload["platform_uid"]).strip(),
        "followers": int(payload.get("followers") or 0),
        "engagement_rate": float(payload.get("engagement_rate") or 0),
        "category": str(payload.get("category") or "其他").strip()[:50],
        "avg_views": int(payload.get("avg_views") or 0),
        "avg_likes": int(payload.get("avg_likes") or 0),
        "avg_comments": int(payload.get("avg_comments") or 0),
        "avg_shares": int(payload.get("avg_shares") or 0),
        "location": payload.get("location"),
        "verified": bool(payload.get("verified") or False),
        "bio": payload.get("bio"),
        "data_source": "browser_connector",
        "contact_info": json.dumps(
            {
                "source": "browser_connector",
                "source_note": source_note,
                "source_url_hash": payload.get("source_url_hash"),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        "last_synced_at": now,
        "is_active": True,
        "updated_at": now,
    }


def _extract_doc_id(result: str) -> str:
    try:
        parsed = json.loads(result)
    except (TypeError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, dict):
        return str(parsed.get("data", {}).get("doc_id") or parsed.get("doc_id") or "unknown")
    return "unknown"
