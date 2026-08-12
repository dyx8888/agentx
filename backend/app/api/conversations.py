"""
Conversation Management API
CRUD endpoints for conversations and messages
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth import get_current_active_user
from app.database import db
from app.database.models import Conversation, Message, User
from app.services.message_persistence import sanitize_user_visible_text

router = APIRouter()


# ==========================================
# Pydantic Schemas
# ==========================================

class CreateConversationRequest(BaseModel):
    """Create conversation request body"""
    title: str = Field(default="新对话", max_length=200)


class MessageResponse(BaseModel):
    """Message in response"""
    id: int
    role: str
    content: str
    content_type: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationResponse(BaseModel):
    """Conversation in list response"""
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    last_message: str | None

    model_config = {"from_attributes": True}


class ConversationDetailResponse(ConversationResponse):
    """Conversation detail with messages"""
    messages: list[MessageResponse]


class ConversationListResponse(BaseModel):
    """Paginated conversation list"""
    total: int
    items: list[ConversationResponse]


class ConversationFileItem(BaseModel):
    """A file referenced or produced within a conversation"""
    id: str
    name: str
    size: str | None = None
    type: str
    source: str
    uploaded_at: str | None = None
    tag: str | None = None


class ConversationFilesResponse(BaseModel):
    """Files reconstructed from conversation messages"""
    items: list[ConversationFileItem]


# ==========================================
# Helper
# ==========================================

def _get_conversation_or_404(conversation_id: int, company_id: int) -> Conversation:
    """Get conversation by ID, raise 404 if not found or wrong company"""
    with db.get_session() as session:
        conv = session.query(Conversation).filter(
            Conversation.id == conversation_id,
            Conversation.company_id == company_id,
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return conv


_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"}


def _infer_file_type(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in {"xlsx", "xls"}:
        return "sheet"
    if ext == "csv":
        return "data"
    if ext in _IMAGE_EXTENSIONS:
        return "image"
    if ext == "pdf":
        return "pdf"
    if ext in {"md", "markdown"}:
        return "report"
    return "doc"


def _coerce_filename(entry) -> str | None:
    if isinstance(entry, str):
        return entry or None
    if isinstance(entry, dict):
        for key in ("filename", "name", "original_filename", "source_file", "source"):
            value = entry.get(key)
            if value:
                return str(value)
    return None


def _safe_json_loads(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _extract_conversation_files(messages) -> list[ConversationFileItem]:
    """Reconstruct conversation files from references_json and metadata_json."""
    items: list[ConversationFileItem] = []
    seen: set[tuple[str, str]] = set()

    for message in messages:
        uploaded_at = message.created_at.strftime("%m-%d %H:%M") if message.created_at else None
        default_source = "agent" if message.role == "assistant" else "uploaded"

        references = _safe_json_loads(message.references_json)
        if isinstance(references, dict):
            references = references.get("references")
        if not isinstance(references, list):
            references = []
        for reference in references:
            name = _coerce_filename(reference)
            if not name:
                continue
            key = (name, "uploaded")
            if key in seen:
                continue
            seen.add(key)
            items.append(
                ConversationFileItem(
                    id=f"ref-{len(items)}",
                    name=name,
                    type=_infer_file_type(name),
                    source="uploaded",
                    uploaded_at=uploaded_at,
                    tag="知识库引用",
                )
            )

        metadata = _safe_json_loads(message.metadata_json)
        entries = []
        if isinstance(metadata, dict):
            for key in ("files", "attachments"):
                value = metadata.get(key)
                if isinstance(value, list):
                    entries.extend(value)
        for entry in entries:
            name = _coerce_filename(entry)
            if not name:
                continue
            source = default_source
            size = None
            if isinstance(entry, dict):
                source = entry.get("source") or default_source
                size = entry.get("size")
            dedupe_key = (name, source)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            items.append(
                ConversationFileItem(
                    id=f"file-{len(items)}",
                    name=name,
                    size=str(size) if size is not None else None,
                    type=_infer_file_type(name),
                    source=source,
                    uploaded_at=uploaded_at,
                    tag="附件",
                )
            )

    return items


# ==========================================
# API Endpoints
# ==========================================

@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_active_user),
):
    """Get conversation list for current user, ordered by updated_at desc"""
    with db.get_session() as session:
        base_query = session.query(Conversation).filter(
            Conversation.company_id == current_user.company_id,
        )
        total = base_query.count()
        items = (
            base_query
            .order_by(Conversation.updated_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return ConversationListResponse(
            total=total,
            items=[
                ConversationResponse(
                    id=item.id,
                    title=item.title,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                    message_count=item.message_count,
                    last_message=(
                        sanitize_user_visible_text(item.last_message)
                        if item.last_message
                        else None
                    ),
                )
                for item in items
            ],
        )


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    request: CreateConversationRequest,
    current_user: User = Depends(get_current_active_user),
):
    """Create a new conversation"""
    with db.get_session() as session:
        conv = Conversation(
            user_id=current_user.id,
            company_id=current_user.company_id,
            title=request.title,
            status="active",
            message_count=0,
        )
        session.add(conv)
        session.commit()
        session.refresh(conv)
        return ConversationResponse.model_validate(conv)


@router.get("/{conversation_id:int}", response_model=ConversationDetailResponse)
async def get_conversation_detail(
    conversation_id: int,
    current_user: User = Depends(get_current_active_user),
):
    """Get conversation detail with messages"""
    with db.get_session() as session:
        conv = session.query(Conversation).filter(
            Conversation.id == conversation_id,
            Conversation.company_id == current_user.company_id,
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        messages = (
            session.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.sequence_num.asc(), Message.id.asc())
            .all()
        )
        return ConversationDetailResponse(
            id=conv.id,
            title=conv.title,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            message_count=conv.message_count,
            last_message=(
                sanitize_user_visible_text(conv.last_message) if conv.last_message else None
            ),
            messages=[
                MessageResponse(
                    id=message.id,
                    role=message.role,
                    content=(
                        sanitize_user_visible_text(message.content)
                        if message.role == "assistant"
                        else message.content
                    ),
                    content_type=message.content_type,
                    created_at=message.created_at,
                )
                for message in messages
            ],
        )


@router.get("/{conversation_id:int}/files", response_model=ConversationFilesResponse)
async def list_conversation_files(
    conversation_id: int,
    current_user: User = Depends(get_current_active_user),
):
    """List files referenced or produced within a conversation."""
    with db.get_session() as session:
        conv = session.query(Conversation).filter(
            Conversation.id == conversation_id,
            Conversation.company_id == current_user.company_id,
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        messages = (
            session.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.sequence_num.asc(), Message.id.asc())
            .all()
        )
        return ConversationFilesResponse(items=_extract_conversation_files(messages))


@router.delete("/{conversation_id:int}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_active_user),
):
    """Delete a conversation"""
    with db.get_session() as session:
        conv = session.query(Conversation).filter(
            Conversation.id == conversation_id,
            Conversation.company_id == current_user.company_id,
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        session.delete(conv)
        session.commit()
    return None
