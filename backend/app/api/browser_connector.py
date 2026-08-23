"""
Browser connector ingest API.

This MVP endpoint accepts read-only, structured browser capture data from the
AgentX Chrome extension. It binds identity from the authenticated AgentX user
and rejects payloads that try to carry credentials or other sensitive fields.
"""

from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import parse_qsl, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator

from sqlalchemy.orm import Session

from app.auth import get_current_active_user
from app.core.feature_flags import get_feature_flags
from app.database.core import get_db
from app.database.models import User
from app.services.browser_connector_business import (
    import_connector_creators_to_kols,
    import_connector_knowledge_observations,
    list_connector_business_records,
    list_connector_campaign_snapshots,
)
from app.services.browser_connector_capture import store_browser_connector_capture
from app.services.browser_connector_schemas import BrowserConnectorRecordKind


router = APIRouter(tags=["browser-connector"])

BROWSER_CONNECTOR_FEATURE = "browser_connector"

SENSITIVE_KEY_MARKERS = (
    "authorization",
    "bearer",
    "cookie",
    "setcookie",
    "token",
    "password",
    "passwd",
    "pwd",
    "captcha",
    "verificationcode",
    "verifycode",
    "smscode",
    "payment",
    "creditcard",
    "bankcard",
    "cardnumber",
    "secret",
    "credential",
    "session",
    "apikey",
    "api_key",
)
SENSITIVE_EXACT_KEYS = {
    "card",
}

ALLOWED_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def _normalize_key(key: str) -> str:
    return key.lower().replace("_", "").replace("-", "").replace(".", "")


def _is_sensitive_key(key: str) -> bool:
    normalized_key = _normalize_key(key)
    return normalized_key in SENSITIVE_EXACT_KEYS or any(
        marker in normalized_key for marker in SENSITIVE_KEY_MARKERS
    )


def _find_sensitive_keys(value: Any, path: str = "data") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            child_path = f"{path}.{key}"
            if _is_sensitive_key(key):
                paths.append(child_path)
            paths.extend(_find_sensitive_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_find_sensitive_keys(child, f"{path}[{index}]"))
    return paths


def _reject_sensitive_url_parts(url: str, field_name: str) -> None:
    parsed = urlsplit(url)
    if parsed.username or parsed.password:
        raise ValueError(f"{field_name} must not contain URL credentials")
    for query_key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        normalized_key = _normalize_key(query_key)
        if any(marker in normalized_key for marker in SENSITIVE_KEY_MARKERS):
            raise ValueError(f"{field_name} must not contain sensitive query keys")


class ConnectorMetadata(BaseModel):
    """Metadata about the browser connector instance."""

    source: str = Field(default="browser-extension", min_length=1, max_length=80)
    extension_id: str | None = Field(default=None, max_length=128)
    version: str | None = Field(default=None, max_length=32)
    mode: str = Field(default="readonly", max_length=32)

    model_config = {"extra": "forbid"}


class PageMetadata(BaseModel):
    """Browser page context, without cookies or headers."""

    url: str = Field(..., min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=300)
    referrer: str | None = Field(default=None, max_length=2048)

    model_config = {"extra": "forbid"}

    @field_validator("url", "referrer")
    @classmethod
    def reject_sensitive_urls(cls, value: str | None, info):
        if value:
            _reject_sensitive_url_parts(value, info.field_name)
        return value


class ApiCaptureMetadata(BaseModel):
    """Captured API response metadata from a whitelisted browser request."""

    url: str = Field(..., min_length=1, max_length=2048)
    method: str = Field(..., min_length=3, max_length=10)
    status_code: int | None = Field(default=None, ge=100, le=599)
    matched_rule: str = Field(..., min_length=1, max_length=120)
    response_mime: str | None = Field(default=None, max_length=120)
    captured_from: Literal["fetch", "xmlhttprequest"] | None = None

    model_config = {"extra": "forbid"}

    @field_validator("url")
    @classmethod
    def reject_sensitive_api_url(cls, value: str):
        _reject_sensitive_url_parts(value, "api.url")
        return value

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str):
        method = value.upper()
        if method not in ALLOWED_HTTP_METHODS:
            raise ValueError("Unsupported HTTP method")
        return method


class CapturePolicy(BaseModel):
    """Client-side capture policy evidence supplied by the extension."""

    whitelist_rule: str = Field(..., min_length=1, max_length=120)
    redaction_version: str = Field(default="v1", max_length=32)
    contains_credentials: bool = False
    contains_sensitive_fields: bool = False
    platform_write_operation: bool = False

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def reject_unsafe_policy(self):
        if self.contains_credentials:
            raise ValueError("Payload must not contain credentials")
        if self.contains_sensitive_fields:
            raise ValueError("Payload must not contain sensitive fields")
        if self.platform_write_operation:
            raise ValueError("Browser connector ingest is read-only")
        return self


class BrowserConnectorIngestRequest(BaseModel):
    """Structured read-only browser capture payload."""

    connector: ConnectorMetadata
    page: PageMetadata
    api: ApiCaptureMetadata
    data: dict[str, Any] | list[Any]
    policy: CapturePolicy
    captured_at: datetime | None = None

    # Accepted only so client-provided identity cannot break ingestion; ignored.
    tenant_id: int | str | None = Field(default=None, exclude=True)
    company_id: int | str | None = Field(default=None, exclude=True)
    user_id: int | str | None = Field(default=None, exclude=True)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def reject_sensitive_payload_data(self):
        sensitive_paths = _find_sensitive_keys(self.data)
        if sensitive_paths:
            joined_paths = ", ".join(sensitive_paths[:5])
            raise ValueError(f"Payload contains sensitive fields: {joined_paths}")
        return self


class BrowserConnectorIngestResponse(BaseModel):
    """Minimal ingest acknowledgement bound to the authenticated user and stored event."""

    accepted: bool
    tenant_id: int | None
    company_id: int | None
    user_id: int
    event_id: int | None
    duplicate: bool = False
    received_at: datetime
    captured_at: datetime | None
    matched_rule: str
    data_shape: Literal["object", "array"]


class BrowserConnectorStatusResponse(BaseModel):
    """Current backend rollout status for the authenticated browser connector user."""

    enabled: bool
    reason: Literal["enabled", "tenant_required", "browser_connector_disabled"]
    feature: str = BROWSER_CONNECTOR_FEATURE
    tenant_id: int | None = None
    company_id: int | None = None
    user_id: int | None = None


class BrowserConnectorRecordsResponse(BaseModel):
    """Normalized connector record preview response."""

    total: int
    records: list[dict[str, Any]]


class BrowserConnectorImportRequest(BaseModel):
    """Human-confirmed connector business import request."""

    event_ids: list[int] | None = Field(default=None, max_length=200)
    dry_run: bool = Field(default=True, description="Preview by default; set false after user confirmation")
    limit: int = Field(default=50, ge=1, le=200)


class BrowserConnectorImportResponse(BaseModel):
    """Connector business import result."""

    imported: int
    updated: int = 0
    skipped: int
    dry_run: bool
    records: list[dict[str, Any]]
    doc_ids: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class BrowserConnectorCampaignSnapshotsResponse(BaseModel):
    """Read-only campaign snapshots derived from connector captures."""

    total: int
    records: list[dict[str, Any]]
    read_only: bool = True


@router.get("/status", response_model=BrowserConnectorStatusResponse)
async def get_browser_connector_status(
    current_user: User = Depends(get_current_active_user),
):
    """Return explicit rollout state before the Settings page requests connector records."""
    company_id, enabled, reason = _browser_connector_rollout_state(current_user)
    return BrowserConnectorStatusResponse(
        enabled=enabled,
        reason=reason,
        tenant_id=company_id,
        company_id=company_id,
        user_id=getattr(current_user, "id", None),
    )


@router.post(
    "/ingest",
    response_model=BrowserConnectorIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_browser_connector_payload(
    request: BrowserConnectorIngestRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Accept structured browser connector data for the authenticated tenant."""
    _require_browser_connector_enabled(current_user)

    data_shape: Literal["object", "array"] = "array" if isinstance(request.data, list) else "object"
    try:
        stored = store_browser_connector_capture(db, request, current_user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return BrowserConnectorIngestResponse(
        accepted=True,
        tenant_id=current_user.company_id,
        company_id=current_user.company_id,
        user_id=current_user.id,
        event_id=stored.event.id,
        duplicate=stored.duplicate,
        received_at=datetime.now(timezone.utc),
        captured_at=request.captured_at,
        matched_rule=request.api.matched_rule,
        data_shape=data_shape,
    )


def _require_connector_company(current_user: User) -> int:
    company_id = getattr(current_user, "company_id", None)
    if company_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Browser connector business records require a tenant-bound user",
        )
    return int(company_id)


def _browser_connector_rollout_state(
    current_user: User,
) -> tuple[int | None, bool, Literal["enabled", "tenant_required", "browser_connector_disabled"]]:
    company_id = getattr(current_user, "company_id", None)
    if company_id is None:
        return None, False, "tenant_required"

    normalized_company_id = int(company_id)
    enabled = get_feature_flags().is_enabled_for_context(
        BROWSER_CONNECTOR_FEATURE,
        tenant_id=normalized_company_id,
        user_id=getattr(current_user, "id", None),
    )
    if enabled:
        return normalized_company_id, True, "enabled"
    return normalized_company_id, False, "browser_connector_disabled"


def _require_browser_connector_enabled(current_user: User) -> int:
    company_id, enabled, _reason = _browser_connector_rollout_state(current_user)
    if company_id is None:
        _require_connector_company(current_user)
    if not enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="browser_connector_disabled: Browser connector is not enabled for this tenant",
        )
    return company_id


@router.get("/records", response_model=BrowserConnectorRecordsResponse)
async def list_browser_connector_records(
    kind: BrowserConnectorRecordKind | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Preview normalized connector records for the authenticated tenant."""
    company_id = _require_browser_connector_enabled(current_user)
    records = list_connector_business_records(db, company_id=company_id, kind=kind, limit=limit)
    serialized = [record.to_dict() for record in records]
    return BrowserConnectorRecordsResponse(total=len(serialized), records=serialized)


@router.post("/import/kols", response_model=BrowserConnectorImportResponse)
async def import_browser_connector_kols(
    request: BrowserConnectorImportRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Import normalized connector creator records into the KOL library after user confirmation."""
    company_id = _require_browser_connector_enabled(current_user)
    result = import_connector_creators_to_kols(
        db,
        company_id=company_id,
        event_ids=request.event_ids,
        dry_run=request.dry_run,
        limit=request.limit,
    )
    return BrowserConnectorImportResponse(**result.to_dict())


@router.post("/import/knowledge", response_model=BrowserConnectorImportResponse)
async def import_browser_connector_knowledge(
    request: BrowserConnectorImportRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Import normalized connector observations into Knowledge after user confirmation."""
    company_id = _require_browser_connector_enabled(current_user)
    from app.api.knowledge import _invalidate_result_cache_for_company, add_knowledge

    result = import_connector_knowledge_observations(
        db,
        company_id=company_id,
        add_knowledge_func=add_knowledge,
        event_ids=request.event_ids,
        dry_run=request.dry_run,
        limit=request.limit,
    )
    if not request.dry_run and result.imported:
        _invalidate_result_cache_for_company(str(company_id))
    return BrowserConnectorImportResponse(**result.to_dict())


@router.get("/analytics/campaign-snapshots", response_model=BrowserConnectorCampaignSnapshotsResponse)
async def list_browser_connector_campaign_snapshots(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Return read-only connector campaign metric snapshots for analysis."""
    company_id = _require_browser_connector_enabled(current_user)
    records = list_connector_campaign_snapshots(db, company_id=company_id, limit=limit)
    serialized = [record.to_dict() for record in records]
    return BrowserConnectorCampaignSnapshotsResponse(total=len(serialized), records=serialized)
