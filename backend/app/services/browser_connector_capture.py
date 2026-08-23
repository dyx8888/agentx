"""Persistence service for sanitized browser connector captures."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import BrowserConnectorEvent, User


SENSITIVE_STORAGE_MARKERS = (
    "authorization",
    "bearer",
    "cookie",
    "setcookie",
    "token",
    "password",
    "passwd",
    "pwd",
    "captcha",
    "verification",
    "verifycode",
    "smscode",
    "otp",
    "payment",
    "paypassword",
    "creditcard",
    "bankcard",
    "cardnumber",
    "cvv",
    "secret",
    "credential",
    "session",
    "apikey",
    "api_key",
)


@dataclass(frozen=True)
class StoredBrowserConnectorEvent:
    event: BrowserConnectorEvent
    duplicate: bool


def store_browser_connector_capture(db: Session, request: Any, current_user: User) -> StoredBrowserConnectorEvent:
    """Persist a sanitized connector capture and deduplicate repeated events per tenant."""
    if current_user.company_id is None:
        raise ValueError("Browser connector capture requires a tenant-bound user")

    data = _model_to_plain(request.data)
    _assert_storage_safe(data)

    sanitized_payload_json = _canonical_json(data)
    platform = _platform_from_url(request.api.url, request.api.matched_rule)
    api_url_hash = _sha256(_canonical_api_url(request.api.url))
    payload_hash = _sha256(
        _canonical_json(
            {
                "company_id": current_user.company_id,
                "source": request.connector.source,
                "platform": platform,
                "matched_rule": request.api.matched_rule,
                "api_url_hash": api_url_hash,
                "api_method": request.api.method,
                "status_code": request.api.status_code,
                "response_mime": request.api.response_mime,
                "data": data,
            }
        )
    )

    existing = (
        db.query(BrowserConnectorEvent)
        .filter(
            BrowserConnectorEvent.company_id == current_user.company_id,
            BrowserConnectorEvent.payload_hash == payload_hash,
        )
        .first()
    )
    if existing is not None:
        return StoredBrowserConnectorEvent(event=existing, duplicate=True)

    event = BrowserConnectorEvent(
        company_id=current_user.company_id,
        user_id=current_user.id,
        source=request.connector.source,
        platform=platform,
        matched_rule=request.api.matched_rule,
        api_url_hash=api_url_hash,
        api_method=request.api.method,
        status_code=request.api.status_code,
        response_mime=request.api.response_mime,
        sanitized_payload_json=sanitized_payload_json,
        payload_hash=payload_hash,
        captured_at=request.captured_at,
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(BrowserConnectorEvent)
            .filter(
                BrowserConnectorEvent.company_id == current_user.company_id,
                BrowserConnectorEvent.payload_hash == payload_hash,
            )
            .one()
        )
        return StoredBrowserConnectorEvent(event=existing, duplicate=True)

    db.refresh(event)
    return StoredBrowserConnectorEvent(event=event, duplicate=False)


def list_browser_connector_events(
    db: Session, company_id: int, limit: int = 50
) -> list[BrowserConnectorEvent]:
    """Return connector events scoped to one tenant only."""
    return (
        db.query(BrowserConnectorEvent)
        .filter(BrowserConnectorEvent.company_id == company_id)
        .order_by(BrowserConnectorEvent.created_at.desc(), BrowserConnectorEvent.id.desc())
        .limit(limit)
        .all()
    )


def _assert_storage_safe(value: Any, path: str = "data") -> None:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized = _normalize_key(key)
            if any(marker in normalized for marker in SENSITIVE_STORAGE_MARKERS):
                raise ValueError(f"Refusing to store sensitive connector field: {path}.{key}")
            _assert_storage_safe(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_storage_safe(child, f"{path}[{index}]")


def _model_to_plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _model_to_plain(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_model_to_plain(child) for child in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_api_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url)
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            "",
            "",
        )
    )


def _platform_from_url(raw_url: str, matched_rule: str) -> str:
    host = urlsplit(raw_url).hostname or ""
    normalized_rule = str(matched_rule or "").lower()
    if "xqttool" in host:
        return "xqttool"
    if "douyin" in host or "jinritemai" in host or "oceanengine" in host:
        return "douyin"
    if normalized_rule.endswith("-api"):
        return normalized_rule[:-4]
    return host or "unknown"


def _normalize_key(value: str) -> str:
    return value.lower().replace("_", "").replace("-", "").replace(".", "")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
