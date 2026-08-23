"""Normalize sanitized browser connector events into business-neutral records."""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from app.database.models import BrowserConnectorEvent
from app.services.browser_connector_rules import (
    AVG_COMMENT_KEYS,
    AVG_LIKE_KEYS,
    AVG_SHARE_KEYS,
    AVG_VIEW_KEYS,
    CAMPAIGN_ID_KEYS,
    CAMPAIGN_NAME_KEYS,
    CATEGORY_KEYS,
    CLICK_KEYS,
    CONVERSION_KEYS,
    CPA_KEYS,
    CREATOR_NAME_KEYS,
    CREATOR_UID_KEYS,
    CTR_KEYS,
    ENGAGEMENT_KEYS,
    FOLLOWER_KEYS,
    IMPRESSION_KEYS,
    KNOWLEDGE_CONTAINER_KEYS,
    KNOWLEDGE_TEXT_KEYS,
    LOCATION_KEYS,
    REVENUE_KEYS,
    ROI_KEYS,
    SPEND_KEYS,
    VERIFIED_KEYS,
)
from app.services.browser_connector_schemas import (
    BrowserConnectorRecordKind,
    NormalizedBrowserConnectorRecord,
)


def normalize_browser_connector_event(
    event: BrowserConnectorEvent,
) -> list[NormalizedBrowserConnectorRecord]:
    """Normalize one stored connector event without writing any business tables."""
    payload = _load_payload(event.sanitized_payload_json)
    body = _extract_payload_body(payload)
    source = _source_metadata(event)

    records: list[NormalizedBrowserConnectorRecord] = []
    records.extend(_normalize_creator_profiles(event, body, source))
    records.extend(_normalize_campaign_metrics(event, body, source))
    records.extend(_normalize_knowledge_observations(event, body, source))
    if not records:
        records.append(_unmapped_record(event, source))
    return records


def normalize_browser_connector_events(
    events: Iterable[BrowserConnectorEvent],
) -> list[NormalizedBrowserConnectorRecord]:
    """Normalize a batch of connector events."""
    normalized: list[NormalizedBrowserConnectorRecord] = []
    for event in events:
        normalized.extend(normalize_browser_connector_event(event))
    return normalized


def _normalize_creator_profiles(
    event: BrowserConnectorEvent,
    body: Any,
    source: dict[str, Any],
) -> list[NormalizedBrowserConnectorRecord]:
    records: list[NormalizedBrowserConnectorRecord] = []
    seen: set[tuple[str, str]] = set()

    for candidate in _iter_dict_candidates(body):
        name = _first_text(candidate, CREATOR_NAME_KEYS)
        platform_uid = _first_text(candidate, CREATOR_UID_KEYS)
        followers = _first_int(candidate, FOLLOWER_KEYS)
        if not name or (platform_uid is None and followers is None):
            continue

        platform_uid = platform_uid or f"connector-event-{event.id or 'unknown'}-{len(records) + 1}"
        dedupe_key = (event.platform, platform_uid)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        record = {
            "name": name,
            "platform": event.platform,
            "platform_uid": platform_uid,
            "followers": followers or 0,
            "engagement_rate": _first_percentage(candidate, ENGAGEMENT_KEYS) or 0,
            "category": _first_text(candidate, CATEGORY_KEYS) or "其他",
            "avg_views": _first_int(candidate, AVG_VIEW_KEYS) or 0,
            "avg_likes": _first_int(candidate, AVG_LIKE_KEYS) or 0,
            "avg_comments": _first_int(candidate, AVG_COMMENT_KEYS) or 0,
            "avg_shares": _first_int(candidate, AVG_SHARE_KEYS) or 0,
            "location": _first_text(candidate, LOCATION_KEYS),
            "verified": _first_bool(candidate, VERIFIED_KEYS) or False,
            "data_source": "browser_connector",
            "source_note": f"browser_connector_event:{event.id}",
            "source_url_hash": event.api_url_hash,
        }
        records.append(
            NormalizedBrowserConnectorRecord(
                kind=BrowserConnectorRecordKind.CREATOR_PROFILE,
                company_id=event.company_id,
                source_event_id=event.id,
                platform=event.platform,
                confidence=_creator_confidence(record),
                record=record,
                source=source,
            )
        )

    return records


def _normalize_campaign_metrics(
    event: BrowserConnectorEvent,
    body: Any,
    source: dict[str, Any],
) -> list[NormalizedBrowserConnectorRecord]:
    records: list[NormalizedBrowserConnectorRecord] = []
    seen: set[str] = set()

    for candidate in _iter_dict_candidates(body):
        campaign_id = _first_text(candidate, CAMPAIGN_ID_KEYS)
        campaign_name = _first_text(candidate, CAMPAIGN_NAME_KEYS)
        impressions = _first_int(candidate, IMPRESSION_KEYS)
        clicks = _first_int(candidate, CLICK_KEYS)
        spend = _first_float(candidate, SPEND_KEYS)
        revenue = _first_float(candidate, REVENUE_KEYS)
        conversions = _first_int(candidate, CONVERSION_KEYS)

        if not (campaign_id or campaign_name):
            continue
        if not any(value is not None for value in (impressions, clicks, spend, revenue, conversions)):
            continue

        stable_id = campaign_id or f"connector-event-{event.id or 'unknown'}-{len(records) + 1}"
        if stable_id in seen:
            continue
        seen.add(stable_id)

        ctr = _first_ratio(candidate, CTR_KEYS)
        if ctr is None and impressions and clicks is not None and impressions > 0:
            ctr = clicks / impressions

        cpa = _first_float(candidate, CPA_KEYS)
        if cpa is None and spend is not None and conversions and conversions > 0:
            cpa = spend / conversions

        roi = _first_float(candidate, ROI_KEYS)
        if roi is None and spend and spend > 0 and revenue is not None:
            roi = revenue / spend

        record = {
            "campaign_id": stable_id,
            "campaign_name": campaign_name,
            "platform": event.platform,
            "impressions": impressions or 0,
            "clicks": clicks or 0,
            "conversions": conversions or 0,
            "spend": spend or 0,
            "revenue": revenue or 0,
            "ctr": ctr or 0,
            "cpa": cpa or 0,
            "roi": roi or 0,
            "data_source": "browser_connector",
            "source_note": f"browser_connector_event:{event.id}",
            "source_url_hash": event.api_url_hash,
        }
        records.append(
            NormalizedBrowserConnectorRecord(
                kind=BrowserConnectorRecordKind.CAMPAIGN_METRICS,
                company_id=event.company_id,
                source_event_id=event.id,
                platform=event.platform,
                confidence=_campaign_confidence(record),
                record=record,
                source=source,
            )
        )

    return records


def _normalize_knowledge_observations(
    event: BrowserConnectorEvent,
    body: Any,
    source: dict[str, Any],
) -> list[NormalizedBrowserConnectorRecord]:
    records: list[NormalizedBrowserConnectorRecord] = []
    for candidate in _iter_knowledge_candidates(body):
        title = _first_text(candidate, ("title", "name", "subject"))
        content = _first_text(candidate, KNOWLEDGE_TEXT_KEYS)
        if not content:
            continue

        tags = _coerce_tags(candidate.get("tags"))
        if event.platform not in tags:
            tags.append(event.platform)
        tags.append("browser_connector")

        record = {
            "title": title or f"Browser connector observation {event.id}",
            "content": content,
            "tags": sorted(set(tags)),
            "data_source": "browser_connector",
            "source_note": f"browser_connector_event:{event.id}",
            "source_url_hash": event.api_url_hash,
        }
        records.append(
            NormalizedBrowserConnectorRecord(
                kind=BrowserConnectorRecordKind.KNOWLEDGE_OBSERVATION,
                company_id=event.company_id,
                source_event_id=event.id,
                platform=event.platform,
                confidence=0.7 if title else 0.6,
                record=record,
                source=source,
            )
        )

    return records


def _iter_dict_candidates(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dict_candidates(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dict_candidates(child)


def _iter_knowledge_candidates(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in KNOWLEDGE_CONTAINER_KEYS:
                yield from _iter_dict_candidates(child)
            else:
                yield from _iter_knowledge_candidates(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_knowledge_candidates(child)


def _load_payload(raw_json: str) -> Any:
    try:
        return json.loads(raw_json)
    except (TypeError, json.JSONDecodeError):
        return {}


def _extract_payload_body(payload: Any) -> Any:
    if isinstance(payload, dict) and payload.get("kind") == "json" and "value" in payload:
        return payload["value"]
    return payload


def _source_metadata(event: BrowserConnectorEvent) -> dict[str, Any]:
    return {
        "source": event.source,
        "matched_rule": event.matched_rule,
        "api_method": event.api_method,
        "status_code": event.status_code,
        "response_mime": event.response_mime,
        "api_url_hash": event.api_url_hash,
        "payload_hash": event.payload_hash,
    }


def _unmapped_record(
    event: BrowserConnectorEvent,
    source: dict[str, Any],
) -> NormalizedBrowserConnectorRecord:
    return NormalizedBrowserConnectorRecord(
        kind=BrowserConnectorRecordKind.UNMAPPED_CAPTURE,
        company_id=event.company_id,
        source_event_id=event.id,
        platform=event.platform,
        confidence=0.0,
        record={
            "status": "pending",
            "reason": "no_normalization_rule_matched",
            "data_source": "browser_connector",
            "source_note": f"browser_connector_event:{event.id}",
            "source_url_hash": event.api_url_hash,
            "payload_hash": event.payload_hash,
        },
        source=source,
    )


def _first_text(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    value = _first_value(data, keys)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_int(data: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    return _to_int(_first_value(data, keys))


def _first_float(data: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    return _to_float(_first_value(data, keys))


def _first_percentage(data: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    value = _to_float(_first_value(data, keys))
    if value is None:
        return None
    return value * 100 if 0 < value <= 1 else value


def _first_ratio(data: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    raw_value = _first_value(data, keys)
    value = _to_float(raw_value)
    if value is None:
        return None
    if isinstance(raw_value, str) and "%" in raw_value:
        return value / 100
    return value / 100 if value > 1 else value


def _first_bool(data: dict[str, Any], keys: tuple[str, ...]) -> bool | None:
    value = _first_value(data, keys)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "y", "1", "已认证", "认证"}:
            return True
        if normalized in {"false", "no", "n", "0", "未认证"}:
            return False
    return None


def _first_value(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    lowered = {str(key).lower(): value for key, value in data.items()}
    for key in keys:
        if key in data:
            return data[key]
        normalized = key.lower()
        if normalized in lowered:
            return lowered[normalized]
    return None


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    if number is None:
        return None
    return int(number)


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip().replace(",", "")
    multiplier = 1.0
    if text.endswith("万"):
        multiplier = 10000.0
        text = text[:-1]
    elif text.lower().endswith("k"):
        multiplier = 1000.0
        text = text[:-1]
    text = text.replace("%", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group(0)) * multiplier


def _coerce_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,，|/]", value) if part.strip()]
    return []


def _creator_confidence(record: dict[str, Any]) -> float:
    score = 0.55
    if record.get("platform_uid"):
        score += 0.15
    if record.get("followers"):
        score += 0.15
    if record.get("engagement_rate"):
        score += 0.1
    if record.get("category") and record["category"] != "其他":
        score += 0.05
    return min(score, 0.95)


def _campaign_confidence(record: dict[str, Any]) -> float:
    metric_count = sum(
        1
        for key in ("impressions", "clicks", "conversions", "spend", "revenue")
        if record.get(key)
    )
    return min(0.5 + metric_count * 0.09, 0.95)
