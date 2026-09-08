"""
Browser connector ingest API.

This MVP endpoint accepts read-only, structured browser capture data from the
AgentX Chrome extension. It binds identity from the authenticated AgentX user
and rejects payloads that try to carry credentials or other sensitive fields.
"""

import asyncio
from datetime import datetime, timezone
import os
from typing import Any, Literal
from urllib.parse import parse_qsl, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator

from sqlalchemy.orm import Session

from app.auth import get_current_active_user
from app.database.core import get_db
from app.database.models import User
from app.services.browser_connector_business import (
    import_connector_creators_to_kols,
    import_connector_knowledge_observations,
    list_connector_business_records,
    list_connector_campaign_snapshots,
)
from app.services.browser_connector_capture import store_browser_connector_capture
from app.services.browser_connector_jobs import (
    CAPTURE_JOB_PURPOSES,
    CaptureJobError,
    claim_capture_job,
    classify_capture_job_for_user,
    complete_capture_job,
    create_capture_draft,
    create_capture_job,
    get_capture_job_for_user,
    issue_capture_job_ticket,
    list_capture_jobs,
    serialize_capture_job,
)
from app.services.browser_connector_schemas import BrowserConnectorRecordKind


router = APIRouter(tags=["browser-connector"])

BROWSER_CONNECTOR_FEATURE = "browser_connector"
BROWSER_CONNECTOR_DISABLE_VALUES = {"0", "false", "no", "off"}

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

ALLOWED_HTTP_METHODS = {"GET", "HEAD"}


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

    # A job ID alone carries no authority. The matching short-lived capability is
    # verified server-side and is never persisted in connector event storage.
    capture_job_id: int | None = Field(default=None, ge=1, exclude=True)
    capability_ticket: str | None = Field(default=None, min_length=16, max_length=512, exclude=True)

    # Accepted only so client-provided identity cannot break ingestion; ignored.
    tenant_id: int | str | None = Field(default=None, exclude=True)
    company_id: int | str | None = Field(default=None, exclude=True)
    user_id: int | str | None = Field(default=None, exclude=True)
    conversation_id: int | str | None = Field(default=None, exclude=True)

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
    capture_job_id: int | None = None
    capture_status: str | None = None
    classification: str | None = None


class CaptureJobCreateRequest(BaseModel):
    conversation_id: int = Field(..., ge=1)
    target_url: str = Field(..., min_length=8, max_length=2048)
    purpose: Literal[
        "creator",
        "knowledge",
        "competitor_evidence",
        "content_reference",
        "generic_evidence",
    ] = "generic_evidence"
    source_message_id: int | None = Field(default=None, ge=1)
    capture_limit: int = Field(default=1, ge=1, le=3)


class CaptureJobTicketResponse(BaseModel):
    job: dict[str, Any]
    capability_ticket: str


class CaptureJobListResponse(BaseModel):
    items: list[dict[str, Any]]


class CaptureDraftRequest(BaseModel):
    draft_kind: Literal["analysis_summary", "invitation_draft"]


class CaptureDraftResponse(BaseModel):
    job: dict[str, Any]
    message_id: int
    content: str


class BrowserConnectorStatusResponse(BaseModel):
    """Current backend availability for the authenticated browser connector user."""

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


def _schedule_capture_completed_notification(capture_job) -> None:
    """Best-effort realtime notification. ChatPage polling remains the reliable fallback."""
    async def notify() -> None:
        from app.ws import ws_manager

        await ws_manager.send_capture_completed(
            user_id=int(capture_job.user_id),
            company_id=int(capture_job.company_id),
            capture_job_id=int(capture_job.id),
            conversation_id=int(capture_job.conversation_id),
            status=str(capture_job.status),
            classification=str(capture_job.classification or "generic_evidence"),
        )

    try:
        asyncio.get_running_loop().create_task(notify())
    except RuntimeError:
        # A synchronous test or script may call this module without an event loop.
        return


@router.get("/status", response_model=BrowserConnectorStatusResponse)
async def get_browser_connector_status(
    current_user: User = Depends(get_current_active_user),
):
    """Return explicit backend availability before the Settings page requests connector records."""
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
    """Accept a sanitized capture through current auth plus an optional task capability."""
    _require_browser_connector_enabled(current_user)

    capture_job = None
    if request.capture_job_id is not None:
        if not request.capability_ticket:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Capture job requires a capability ticket",
            )
        try:
            capture_job = claim_capture_job(
                db,
                job_id=request.capture_job_id,
                capability_ticket=request.capability_ticket,
                page_url=request.page.url,
                api_url=request.api.url,
                current_user=current_user,
            )
        except CaptureJobError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    data_shape: Literal["object", "array"] = "array" if isinstance(request.data, list) else "object"
    try:
        stored = store_browser_connector_capture(db, request, current_user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    if capture_job is not None:
        try:
            capture_job = complete_capture_job(db, job_id=capture_job.id, event=stored.event)
        except CaptureJobError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        _schedule_capture_completed_notification(capture_job)

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
        capture_job_id=capture_job.id if capture_job else None,
        capture_status=capture_job.status if capture_job else None,
        classification=capture_job.classification if capture_job else None,
    )


@router.post("/capture-jobs", response_model=CaptureJobTicketResponse, status_code=status.HTTP_201_CREATED)
async def create_browser_capture_job(
    request: CaptureJobCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Create an explicit, user-owned request for one safe page capture."""
    _require_browser_connector_enabled(current_user)
    try:
        created = create_capture_job(
            db,
            current_user=current_user,
            conversation_id=request.conversation_id,
            target_url=request.target_url,
            purpose=request.purpose,
            source_message_id=request.source_message_id,
            capture_limit=request.capture_limit,
        )
    except CaptureJobError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return CaptureJobTicketResponse(
        job=serialize_capture_job(created.job), capability_ticket=created.capability_ticket
    )


@router.get("/capture-jobs", response_model=CaptureJobListResponse)
async def list_browser_capture_jobs(
    conversation_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _require_browser_connector_enabled(current_user)
    jobs = list_capture_jobs(
        db,
        current_user=current_user,
        conversation_id=conversation_id,
        limit=limit,
    )
    return CaptureJobListResponse(items=[serialize_capture_job(job) for job in jobs])


@router.get("/capture-jobs/{job_id}", response_model=dict[str, Any])
async def get_browser_capture_job(
    job_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _require_browser_connector_enabled(current_user)
    try:
        return serialize_capture_job(get_capture_job_for_user(db, job_id=job_id, current_user=current_user))
    except CaptureJobError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/capture-jobs/{job_id}/ticket", response_model=CaptureJobTicketResponse)
async def refresh_browser_capture_job_ticket(
    job_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _require_browser_connector_enabled(current_user)
    try:
        created = issue_capture_job_ticket(db, job_id=job_id, current_user=current_user)
    except CaptureJobError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return CaptureJobTicketResponse(
        job=serialize_capture_job(created.job), capability_ticket=created.capability_ticket
    )


@router.post("/capture-jobs/{job_id}/classify", response_model=dict[str, Any])
async def classify_browser_capture_job(
    job_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Confirm the job's safe candidate category before creating a local draft."""
    _require_browser_connector_enabled(current_user)
    try:
        job = classify_capture_job_for_user(db, job_id=job_id, current_user=current_user)
    except CaptureJobError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return serialize_capture_job(job)


@router.post("/capture-jobs/{job_id}/draft", response_model=CaptureDraftResponse)
async def create_browser_capture_draft(
    job_id: int,
    request: CaptureDraftRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Generate an on-platform draft only; this route never sends external messages."""
    _require_browser_connector_enabled(current_user)
    try:
        job, message = create_capture_draft(
            db,
            job_id=job_id,
            current_user=current_user,
            draft_kind=request.draft_kind,
        )
    except CaptureJobError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return CaptureDraftResponse(job=serialize_capture_job(job), message_id=message.id, content=message.content)


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
    if _browser_connector_emergency_disabled():
        return normalized_company_id, False, "browser_connector_disabled"
    return normalized_company_id, True, "enabled"


def _require_browser_connector_enabled(current_user: User) -> int:
    company_id, enabled, _reason = _browser_connector_rollout_state(current_user)
    if company_id is None:
        _require_connector_company(current_user)
    if not enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="browser_connector_disabled: Browser connector is disabled by the emergency feature switch",
        )
    return company_id


def _browser_connector_emergency_disabled() -> bool:
    env_value = os.getenv(f"FEATURE_{BROWSER_CONNECTOR_FEATURE.upper()}")
    if env_value is None:
        return False
    return env_value.strip().lower() in BROWSER_CONNECTOR_DISABLE_VALUES


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
