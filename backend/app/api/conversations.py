"""
Conversation Management API
CRUD endpoints for conversations and messages
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth import get_current_active_user
from app.database import db
from app.database.models import Conversation, Message, User

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
            items=[ConversationResponse.model_validate(item) for item in items],
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


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation_detail(
    conversation_id: int,
    current_user: User = Depends(get_current_active_user),
):
    """Get conversation detail with messages"""
    conv = _get_conversation_or_404(conversation_id, current_user.company_id)
    return ConversationDetailResponse(
        id=conv.id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=conv.message_count,
        last_message=conv.last_message,
        messages=[MessageResponse.model_validate(m) for m in conv.messages],
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_active_user),
):
    """Delete a conversation"""
    conv = _get_conversation_or_404(conversation_id, current_user.company_id)
    with db.get_session() as session:
        session.delete(conv)
        session.commit()
    return None
