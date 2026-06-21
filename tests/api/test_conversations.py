"""
Unit tests for Conversation Management API (Task 1.2)
Tests for GET/POST/DELETE /api/conversations endpoints
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


# ============================================================
# Test Schemas (Pydantic models)
# ============================================================

class TestConversationSchemas:
    """Test Pydantic schemas for conversation API"""

    def test_create_conversation_request_minimal(self):
        """CreateConversationRequest 不传 title 时使用默认值"""
        from app.api.conversations import CreateConversationRequest

        req = CreateConversationRequest()
        assert req.title == "新对话"

    def test_create_conversation_request_with_title(self):
        """CreateConversationRequest 传入自定义 title"""
        from app.api.conversations import CreateConversationRequest

        req = CreateConversationRequest(title="美妆达人搜索")
        assert req.title == "美妆达人搜索"

    def test_create_conversation_request_title_too_long(self):
        """CreateConversationRequest title 超过 200 字符应报错"""
        from pydantic import ValidationError
        from app.api.conversations import CreateConversationRequest

        with pytest.raises(ValidationError):
            CreateConversationRequest(title="x" * 201)

    def test_conversation_response_schema(self):
        """ConversationResponse schema 字段正确"""
        from app.api.conversations import ConversationResponse

        now = datetime.now(timezone.utc)
        resp = ConversationResponse(
            id=1,
            title="test",
            created_at=now,
            updated_at=now,
            message_count=3,
            last_message="hello",
        )
        assert resp.id == 1
        assert resp.title == "test"
        assert resp.message_count == 3
        assert resp.last_message == "hello"

    def test_conversation_detail_response_schema(self):
        """ConversationDetailResponse schema 包含 messages 字段"""
        from app.api.conversations import ConversationDetailResponse, MessageResponse

        now = datetime.now(timezone.utc)
        msg = MessageResponse(
            id=1,
            role="user",
            content="hello",
            content_type="text",
            created_at=now,
        )
        detail = ConversationDetailResponse(
            id=1,
            title="test",
            created_at=now,
            updated_at=now,
            message_count=1,
            last_message="hello",
            messages=[msg],
        )
        assert len(detail.messages) == 1
        assert detail.messages[0].role == "user"
        assert detail.messages[0].content == "hello"

    def test_conversation_list_response_schema(self):
        """ConversationListResponse schema 包含 total 和 items"""
        from app.api.conversations import ConversationListResponse, ConversationResponse

        now = datetime.now(timezone.utc)
        item = ConversationResponse(
            id=1,
            title="test",
            created_at=now,
            updated_at=now,
            message_count=0,
            last_message=None,
        )
        resp = ConversationListResponse(total=1, items=[item])
        assert resp.total == 1
        assert len(resp.items) == 1


# ============================================================
# Test Router endpoints (with mocked DB)
# ============================================================

@pytest.fixture
def mock_db_adapter():
    """Mock PostgresAdapter for database operations"""
    adapter = MagicMock()
    mock_session = MagicMock()
    adapter.get_session.return_value.__enter__.return_value = mock_session
    return adapter, mock_session


@pytest.fixture
def mock_current_user():
    """Mock authenticated user"""
    user = MagicMock()
    user.id = 1
    user.company_id = 1
    user.username = "testuser"
    user.disabled = False
    return user


@pytest.fixture
def client(mock_db_adapter, mock_current_user):
    """Create test client with mocked dependencies"""
    from fastapi import FastAPI
    from app.api.conversations import router as conv_router
    from app.auth import get_current_active_user
    from app.database import db as db_proxy

    app = FastAPI()
    app.include_router(conv_router, prefix="/api/conversations", tags=["conversations"])

    async def mock_get_user():
        return mock_current_user

    app.dependency_overrides[get_current_active_user] = mock_get_user

    # Set the DatabaseProxy instance to our mock
    db_proxy._instance = mock_db_adapter[0]

    yield TestClient(app)

    # Cleanup
    db_proxy._instance = None


class TestListConversations:
    """Test GET /api/conversations"""

    def test_list_conversations_empty(self, client, mock_db_adapter):
        """获取空对话列表"""
        _, mock_session = mock_db_adapter
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_query.count.return_value = 0

        response = client.get("/api/conversations")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_list_conversations_with_pagination(self, client, mock_db_adapter):
        """获取对话列表 — 分页参数"""
        _, mock_session = mock_db_adapter
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_query.count.return_value = 0

        response = client.get("/api/conversations?limit=10&offset=5")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0


class TestCreateConversation:
    """Test POST /api/conversations"""

    def test_create_conversation_default_title(self, client, mock_db_adapter):
        """创建对话 — 使用默认标题"""
        _, mock_session = mock_db_adapter
        mock_session.add = MagicMock()
        mock_session.commit = MagicMock()

        def mock_refresh(conv):
            conv.id = 1
            conv.created_at = datetime.now(timezone.utc)
            conv.updated_at = datetime.now(timezone.utc)

        mock_session.refresh = mock_refresh

        response = client.post("/api/conversations", json={})
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "新对话"

    def test_create_conversation_custom_title(self, client, mock_db_adapter):
        """创建对话 — 自定义标题"""
        _, mock_session = mock_db_adapter
        mock_session.add = MagicMock()
        mock_session.commit = MagicMock()

        def mock_refresh(conv):
            conv.id = 1
            conv.created_at = datetime.now(timezone.utc)
            conv.updated_at = datetime.now(timezone.utc)

        mock_session.refresh = mock_refresh

        response = client.post("/api/conversations", json={"title": "美妆达人搜索"})
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "美妆达人搜索"


class TestGetConversationDetail:
    """Test GET /api/conversations/{conversation_id}"""

    def test_get_conversation_not_found(self, client, mock_db_adapter):
        """获取不存在的对话 — 返回 404"""
        _, mock_session = mock_db_adapter
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        response = client.get("/api/conversations/999")
        assert response.status_code == 404

    def test_get_conversation_detail(self, client, mock_db_adapter):
        """获取对话详情"""
        from app.database.models import Conversation

        _, mock_session = mock_db_adapter
        now = datetime.now(timezone.utc)

        mock_conv = MagicMock(spec=Conversation)
        mock_conv.id = 1
        mock_conv.company_id = 1
        mock_conv.user_id = 1
        mock_conv.title = "test"
        mock_conv.status = "active"
        mock_conv.message_count = 1
        mock_conv.last_message = "hello"
        mock_conv.created_at = now
        mock_conv.updated_at = now
        mock_conv.messages = []

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mock_conv

        response = client.get("/api/conversations/1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["title"] == "test"


class TestDeleteConversation:
    """Test DELETE /api/conversations/{conversation_id}"""

    def test_delete_conversation_not_found(self, client, mock_db_adapter):
        """删除不存在的对话 — 返回 404"""
        _, mock_session = mock_db_adapter
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        response = client.delete("/api/conversations/999")
        assert response.status_code == 404

    def test_delete_conversation_success(self, client, mock_db_adapter):
        """删除对话成功 — 返回 204"""
        from app.database.models import Conversation

        _, mock_session = mock_db_adapter
        mock_conv = MagicMock(spec=Conversation)
        mock_conv.id = 1
        mock_conv.company_id = 1

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mock_conv
        mock_session.delete = MagicMock()
        mock_session.commit = MagicMock()

        response = client.delete("/api/conversations/1")
        assert response.status_code == 204

    def test_delete_conversation_wrong_company(self, client, mock_db_adapter):
        """删除其他公司的对话 — 返回 404"""
        _, mock_session = mock_db_adapter
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        response = client.delete("/api/conversations/1")
        assert response.status_code == 404
