"""Ownership, capability, and lifecycle rules for browser connector capture jobs."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.database.models import BrowserConnectorEvent, CaptureJob, Conversation, Message, User


CAPTURE_JOB_PENDING = "pending"
CAPTURE_JOB_CAPTURED = "captured"
CAPTURE_JOB_CLASSIFIED = "classified"
CAPTURE_JOB_DRAFT_READY = "draft_ready"
CAPTURE_JOB_EXPIRED = "expired"
CAPTURE_JOB_PURPOSES = {
    "creator",
    "knowledge",
    "competitor_evidence",
    "content_reference",
    "generic_evidence",
}
CAPTURE_JOB_TTL = timedelta(minutes=20)
CAPABILITY_TICKET_TTL = timedelta(minutes=5)
_DENIED_TARGET_PATH_PARTS = (
    "login",
    "auth",
    "password",
    "token",
    "oauth",
    "callback",
    "captcha",
    "verify",
    "payment",
    "order",
    "message",
    "chat",
    "wallet",
    "address",
)


class CaptureJobError(ValueError):
    """Safe domain error returned as a client-visible capture job rejection."""


@dataclass(frozen=True)
class CreatedCaptureJob:
    job: CaptureJob
    capability_ticket: str


def create_capture_job(
    db: Session,
    *,
    current_user: User,
    conversation_id: int,
    target_url: str,
    purpose: str = "generic_evidence",
    source_message_id: int | None = None,
    capture_limit: int = 1,
) -> CreatedCaptureJob:
    company_id = _company_id(current_user)
    if purpose not in CAPTURE_JOB_PURPOSES:
        raise CaptureJobError("Unsupported capture purpose")
    if capture_limit < 1 or capture_limit > 3:
        raise CaptureJobError("Capture limit must be between 1 and 3")

    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.company_id == company_id,
            Conversation.user_id == current_user.id,
            Conversation.status == "active",
        )
        .first()
    )
    if conversation is None:
        raise CaptureJobError("Conversation not found")
    if source_message_id is not None:
        source_message = (
            db.query(Message)
            .filter(
                Message.id == source_message_id,
                Message.conversation_id == conversation_id,
            )
            .first()
        )
        if source_message is None:
            raise CaptureJobError("Source message not found")

    target_host, target_path_prefix = normalize_capture_target(target_url)
    now = _utcnow()
    ticket = _new_ticket()
    job = CaptureJob(
        company_id=company_id,
        user_id=current_user.id,
        conversation_id=conversation_id,
        source_message_id=source_message_id,
        purpose=purpose,
        target_host=target_host,
        target_path_prefix=target_path_prefix,
        status=CAPTURE_JOB_PENDING,
        expires_at=now + CAPTURE_JOB_TTL,
        capture_limit=capture_limit,
        capture_count=0,
        capability_ticket_hash=_ticket_hash(ticket),
        ticket_expires_at=min(now + CAPABILITY_TICKET_TTL, now + CAPTURE_JOB_TTL),
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return CreatedCaptureJob(job=job, capability_ticket=ticket)


def list_capture_jobs(
    db: Session,
    *,
    current_user: User,
    conversation_id: int | None = None,
    limit: int = 30,
) -> list[CaptureJob]:
    company_id = _company_id(current_user)
    query = db.query(CaptureJob).filter(
        CaptureJob.company_id == company_id,
        CaptureJob.user_id == current_user.id,
    )
    if conversation_id is not None:
        query = query.filter(CaptureJob.conversation_id == conversation_id)
    jobs = query.order_by(CaptureJob.updated_at.desc(), CaptureJob.id.desc()).limit(limit).all()
    _expire_pending_jobs(db, jobs)
    return jobs


def get_capture_job_for_user(db: Session, *, job_id: int, current_user: User) -> CaptureJob:
    company_id = _company_id(current_user)
    job = (
        db.query(CaptureJob)
        .filter(
            CaptureJob.id == job_id,
            CaptureJob.company_id == company_id,
            CaptureJob.user_id == current_user.id,
        )
        .first()
    )
    if job is None:
        raise CaptureJobError("Capture job not found")
    _expire_pending_jobs(db, [job])
    return job


def issue_capture_job_ticket(
    db: Session, *, job_id: int, current_user: User
) -> CreatedCaptureJob:
    job = get_capture_job_for_user(db, job_id=job_id, current_user=current_user)
    if job.status != CAPTURE_JOB_PENDING:
        raise CaptureJobError("Capture job is not pending")
    if job.capture_count >= job.capture_limit:
        raise CaptureJobError("Capture limit reached")
    now = _utcnow()
    if _is_expired(job, now):
        _mark_expired(db, job, now)
        raise CaptureJobError("Capture job has expired")

    ticket = _new_ticket()
    job.capability_ticket_hash = _ticket_hash(ticket)
    job.ticket_expires_at = min(now + CAPABILITY_TICKET_TTL, job.expires_at)
    job.ticket_used_at = None
    job.updated_at = now
    db.commit()
    db.refresh(job)
    return CreatedCaptureJob(job=job, capability_ticket=ticket)


def claim_capture_job(
    db: Session,
    *,
    job_id: int,
    capability_ticket: str,
    page_url: str,
    api_url: str,
    current_user: User | None,
) -> CaptureJob:
    """Validate and consume one ticket before a connector event is persisted."""
    job = db.query(CaptureJob).filter(CaptureJob.id == job_id).with_for_update().first()
    if job is None:
        raise CaptureJobError("Capture job is unavailable")
    if current_user is not None and (
        _company_id(current_user) != job.company_id or current_user.id != job.user_id
    ):
        raise CaptureJobError("Capture job does not belong to this user")

    now = _utcnow()
    if _is_expired(job, now):
        _mark_expired(db, job, now)
        raise CaptureJobError("Capture job has expired")
    if job.status != CAPTURE_JOB_PENDING:
        raise CaptureJobError("Capture job is no longer pending")
    if job.capture_count >= job.capture_limit:
        raise CaptureJobError("Capture limit reached")
    if job.ticket_used_at is not None or now > job.ticket_expires_at:
        raise CaptureJobError("Capture capability has expired or was already used")
    if not capability_ticket or not hmac.compare_digest(
        job.capability_ticket_hash, _ticket_hash(capability_ticket)
    ):
        raise CaptureJobError("Capture capability is invalid")
    if not capture_urls_match_job(job, page_url=page_url, api_url=api_url):
        raise CaptureJobError("Capture URL is outside the job target")

    job.ticket_used_at = now
    job.updated_at = now
    db.commit()
    db.refresh(job)
    return job


def complete_capture_job(
    db: Session,
    *,
    job_id: int,
    event: BrowserConnectorEvent,
) -> CaptureJob:
    job = db.query(CaptureJob).filter(CaptureJob.id == job_id).with_for_update().first()
    if job is None:
        raise CaptureJobError("Capture job is unavailable")
    if job.status != CAPTURE_JOB_PENDING:
        raise CaptureJobError("Capture job is no longer pending")

    now = _utcnow()
    job.status = CAPTURE_JOB_CAPTURED
    job.capture_count += 1
    job.result_event_id = event.id
    job.captured_at = now
    job.updated_at = now
    job.classification = classify_capture_job(job, event)
    job.result_summary_json = json.dumps(
        build_capture_evidence_summary(job, event), ensure_ascii=False, separators=(",", ":")
    )
    db.commit()
    db.refresh(job)
    return job


def create_capture_draft(
    db: Session,
    *,
    job_id: int,
    current_user: User,
    draft_kind: str,
) -> tuple[CaptureJob, Message]:
    if draft_kind not in {"analysis_summary", "invitation_draft"}:
        raise CaptureJobError("Unsupported draft type")
    job = get_capture_job_for_user(db, job_id=job_id, current_user=current_user)
    if job.status not in {CAPTURE_JOB_CLASSIFIED, CAPTURE_JOB_DRAFT_READY} or not job.result_event_id:
        raise CaptureJobError("Capture job has no captured evidence")

    evidence = _summary_from_job(job)
    content = build_stationary_draft(job, evidence, draft_kind)
    conversation = db.query(Conversation).filter(Conversation.id == job.conversation_id).first()
    if conversation is None:
        raise CaptureJobError("Conversation not found")
    next_sequence = int(conversation.message_count or 0) + 1
    message = Message(
        conversation_id=job.conversation_id,
        role="assistant",
        content=content,
        content_type="capture_draft",
        metadata_json=json.dumps(
            {
                "capture_job_id": job.id,
                "draft_kind": draft_kind,
                "classification": job.classification,
                "read_only_evidence": True,
                "external_send": False,
            },
            ensure_ascii=False,
        ),
        sequence_num=next_sequence,
    )
    db.add(message)
    job.draft_kind = draft_kind
    job.draft_content = content
    job.updated_at = _utcnow()
    conversation.message_count = next_sequence
    conversation.last_message = "已生成站内采集草稿"
    conversation.updated_at = job.updated_at
    job.status = CAPTURE_JOB_DRAFT_READY
    db.commit()
    db.refresh(job)
    db.refresh(message)
    return job, message


def classify_capture_job_for_user(
    db: Session, *, job_id: int, current_user: User
) -> CaptureJob:
    """Confirm the safe candidate classification before a draft can be generated."""
    job = get_capture_job_for_user(db, job_id=job_id, current_user=current_user)
    if job.status != CAPTURE_JOB_CAPTURED or not job.result_event_id or not job.classification:
        raise CaptureJobError("Capture job has no evidence ready for classification")
    job.status = CAPTURE_JOB_CLASSIFIED
    job.updated_at = _utcnow()
    db.commit()
    db.refresh(job)
    return job


def serialize_capture_job(job: CaptureJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "conversation_id": job.conversation_id,
        "source_message_id": job.source_message_id,
        "purpose": job.purpose,
        "target_host": job.target_host,
        "target_path_prefix": job.target_path_prefix,
        "status": job.status,
        "expires_at": job.expires_at,
        "capture_limit": job.capture_limit,
        "capture_count": job.capture_count,
        "result_event_id": job.result_event_id,
        "classification": job.classification,
        "evidence": _summary_from_job(job),
        "draft_kind": job.draft_kind,
        "draft_content": job.draft_content,
        "captured_at": job.captured_at,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def normalize_capture_target(target_url: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(str(target_url).strip())
    except ValueError as exc:
        raise CaptureJobError("Target URL must be valid") from exc
    host = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise CaptureJobError("Target URL must use HTTPS without credentials")
    if any(part in path.lower() for part in _DENIED_TARGET_PATH_PARTS):
        raise CaptureJobError("Target URL is not eligible for read-only capture")
    return host, path


def capture_urls_match_job(job: CaptureJob, *, page_url: str, api_url: str) -> bool:
    try:
        page = urlsplit(page_url)
        api = urlsplit(api_url)
    except ValueError:
        return False
    page_host = (page.hostname or "").lower()
    api_host = (api.hostname or "").lower()
    if page.scheme != "https" or api.scheme != "https":
        return False
    if page_host != job.target_host:
        return False
    if not (page.path or "/").startswith(job.target_path_prefix):
        return False
    if not _same_platform_site(job.target_host, api_host):
        return False
    return not any(part in (api.path or "/").lower() for part in _DENIED_TARGET_PATH_PARTS)


def classify_capture_job(job: CaptureJob, event: BrowserConnectorEvent) -> str:
    if job.purpose in {"competitor_evidence", "content_reference", "generic_evidence"}:
        return job.purpose
    if job.purpose == "creator":
        return "generic_evidence"
    if job.purpose == "knowledge":
        return "content_reference"
    return "generic_evidence"


def build_capture_evidence_summary(job: CaptureJob, event: BrowserConnectorEvent) -> dict[str, Any]:
    payload = _safe_payload(event.sanitized_payload_json)
    title = _first_text(payload, ("title", "name", "subject"))
    visible_text = _first_text(payload, ("visible_text", "summary", "description", "content"))
    excerpt = (visible_text or "").strip().replace("\n", " ")[:600]
    return {
        "event_id": event.id,
        "classification": job.classification or classify_capture_job(job, event),
        "platform": event.platform,
        "title": title[:200] if title else None,
        "excerpt": excerpt or None,
        "source_url_hash": event.api_url_hash,
        "read_only": True,
    }


def build_stationary_draft(job: CaptureJob, evidence: dict[str, Any], draft_kind: str) -> str:
    label = {
        "generic_evidence": "公开网页证据",
        "competitor_evidence": "竞品证据",
        "content_reference": "内容参考",
    }.get(job.classification or "", "公开网页证据")
    excerpt = str(evidence.get("excerpt") or "未提取到可展示的正文摘要。")
    title = str(evidence.get("title") or job.target_host)
    if draft_kind == "analysis_summary":
        return (
            f"采集分析摘要（仅站内）\n\n"
            f"证据类型：{label}\n来源页面：{title}\n\n"
            f"已采集的公开页面摘要：{excerpt}\n\n"
            "建议：先由运营人员核对原页面与业务相关性，再决定是否进入达人库、知识库或竞品分析流程。"
        )
    return (
        f"邀约草稿（仅站内，未发送）\n\n"
        f"参考证据：{label}，来源页面：{title}\n\n"
        f"你好，我们关注到你近期公开内容中提到的方向：{excerpt[:220]}\n"
        "我们希望进一步了解是否有合作可能。具体合作内容、报价与发送对象仍需由运营人员确认后单独发送。"
    )


def _summary_from_job(job: CaptureJob) -> dict[str, Any]:
    return _safe_payload(job.result_summary_json)


def _safe_payload(raw: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _first_text(value: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for child in value.values():
            found = _first_text(child, keys)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_text(child, keys)
            if found:
                return found
    return None


def _expire_pending_jobs(db: Session, jobs: list[CaptureJob]) -> None:
    now = _utcnow()
    changed = False
    for job in jobs:
        if job.status == CAPTURE_JOB_PENDING and _is_expired(job, now):
            job.status = CAPTURE_JOB_EXPIRED
            job.updated_at = now
            changed = True
    if changed:
        db.commit()
        for job in jobs:
            db.refresh(job)


def _mark_expired(db: Session, job: CaptureJob, now: datetime) -> None:
    job.status = CAPTURE_JOB_EXPIRED
    job.updated_at = now
    db.commit()
    db.refresh(job)


def _is_expired(job: CaptureJob, now: datetime) -> bool:
    return job.expires_at <= now


def _same_platform_site(left: str, right: str) -> bool:
    if left == right:
        return True
    return left.endswith(f".{right}") or right.endswith(f".{left}")


def _company_id(user: User) -> int:
    company_id = getattr(user, "company_id", None)
    if company_id is None:
        raise CaptureJobError("Capture jobs require a tenant-bound user")
    return int(company_id)


def _new_ticket() -> str:
    return secrets.token_urlsafe(32)


def _ticket_hash(ticket: str) -> str:
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.utcnow()
