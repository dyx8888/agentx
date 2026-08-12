"""
Unit tests for Message Persistence Service (Task 2.5)
Tests for saving/loading messages and updating conversation stats
"""

from unittest.mock import MagicMock

from app.database.models import Conversation


# ============================================================
# Test: Get or Create Conversation
# ============================================================


class TestGetOrCreateConversation:
    """Test get_or_create_conversation helper"""

    def test_create_new_conversation(self):
        """创建新对话"""
        from app.services.message_persistence import get_or_create_conversation

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        get_or_create_conversation(
            session=mock_session,
            user_id=1,
            company_id=1,
            title="新对话",
        )

        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_reuse_existing_conversation(self):
        """复用已有对话"""
        from app.services.message_persistence import get_or_create_conversation

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query

        existing_conv = MagicMock(spec=Conversation)
        existing_conv.id = 1
        existing_conv.status = "active"
        mock_query.first.return_value = existing_conv

        result = get_or_create_conversation(
            session=mock_session,
            user_id=1,
            company_id=1,
            conversation_id=1,
        )

        assert result.id == 1
        mock_session.add.assert_not_called()

    def test_create_with_custom_title(self):
        """使用自定义标题创建"""
        from app.services.message_persistence import get_or_create_conversation

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        get_or_create_conversation(
            session=mock_session,
            user_id=1,
            company_id=1,
            title="美妆达人搜索",
        )

        # 验证创建的 Conversation 使用了自定义标题
        call_args = mock_session.add.call_args[0][0]
        assert call_args.title == "美妆达人搜索"


# ============================================================
# Test: Save User Message
# ============================================================


class TestSaveUserMessage:
    """Test save_user_message helper"""

    def test_save_user_message(self):
        """保存用户消息"""
        from app.services.message_persistence import save_user_message

        mock_session = MagicMock()

        save_user_message(
            session=mock_session,
            conversation_id=1,
            user_id=1,
            content="帮我找美妆达人",
            sequence_num=1,
        )

        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_save_user_message_with_metadata(self):
        """保存用户消息 — 带 metadata"""
        from app.services.message_persistence import save_user_message

        mock_session = MagicMock()

        save_user_message(
            session=mock_session,
            conversation_id=1,
            user_id=1,
            content="帮我找美妆达人",
            metadata={"intent": "kol_search"},
            sequence_num=1,
        )

        call_args = mock_session.add.call_args[0][0]
        assert call_args.metadata_json is not None

    def test_user_message_role_is_user(self):
        """用户消息 role 为 'user'"""
        from app.services.message_persistence import save_user_message

        mock_session = MagicMock()

        save_user_message(
            session=mock_session,
            conversation_id=1,
            user_id=1,
            content="test",
            sequence_num=1,
        )

        call_args = mock_session.add.call_args[0][0]
        assert call_args.role == "user"


# ============================================================
# Test: Save Assistant Message
# ============================================================


class TestSaveAssistantMessage:
    """Test save_assistant_message helper"""

    def test_save_assistant_message(self):
        """保存助手回复"""
        from app.services.message_persistence import save_assistant_message

        mock_session = MagicMock()

        save_assistant_message(
            session=mock_session,
            conversation_id=1,
            content="已为你找到5位美妆达人",
            sequence_num=2,
        )

        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_assistant_message_role_is_assistant(self):
        """助手消息 role 为 'assistant'"""
        from app.services.message_persistence import save_assistant_message

        mock_session = MagicMock()

        save_assistant_message(
            session=mock_session,
            conversation_id=1,
            content="test",
            sequence_num=2,
        )

        call_args = mock_session.add.call_args[0][0]
        assert call_args.role == "assistant"

    def test_save_assistant_message_with_metadata(self):
        """保存助手回复 — 带结构化数据"""
        from app.services.message_persistence import save_assistant_message

        mock_session = MagicMock()

        save_assistant_message(
            session=mock_session,
            conversation_id=1,
            content="已为你找到美妆达人",
            metadata={"kol_list": [{"name": "达人A", "followers": 100000}]},
            references={"source": "平台数据"},
            sequence_num=2,
        )

        call_args = mock_session.add.call_args[0][0]
        assert call_args.metadata_json is not None
        assert call_args.references_json is not None


# ============================================================
# Test: Update Conversation Stats
# ============================================================


class TestUpdateConversationStats:
    """Test update_conversation_stats helper"""

    def test_update_message_count(self):
        """更新 message_count 和 last_message"""
        from app.services.message_persistence import update_conversation_stats

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query

        mock_conv = MagicMock(spec=Conversation)
        mock_conv.id = 1
        mock_conv.message_count = 0
        mock_query.first.return_value = mock_conv

        update_conversation_stats(
            session=mock_session,
            conversation_id=1,
            last_message="已找到达人",
        )

        assert mock_conv.message_count == 1
        assert mock_conv.last_message == "已找到达人"
        mock_session.commit.assert_called_once()

    def test_update_message_count_increments(self):
        """message_count 递增"""
        from app.services.message_persistence import update_conversation_stats

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query

        mock_conv = MagicMock(spec=Conversation)
        mock_conv.id = 1
        mock_conv.message_count = 5
        mock_query.first.return_value = mock_conv

        update_conversation_stats(
            session=mock_session,
            conversation_id=1,
            last_message="新消息",
        )

        assert mock_conv.message_count == 6

    def test_update_conversation_not_found_no_error(self):
        """对话不存在时不抛异常"""
        from app.services.message_persistence import update_conversation_stats

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        # 不应抛出异常
        update_conversation_stats(
            session=mock_session,
            conversation_id=999,
            last_message="test",
        )


# ============================================================
# Test: Truncate Title
# ============================================================


class TestTruncateTitle:
    """Test title truncation helper"""

    def test_short_message_returns_full(self):
        """短消息直接返回"""
        from app.services.message_persistence import truncate_title

        result = truncate_title("帮我找美妆达人")
        assert result == "帮我找美妆达人"

    def test_long_message_truncated(self):
        """长消息截断"""
        from app.services.message_persistence import truncate_title

        result = truncate_title("这是一条非常长的消息用于测试标题截断功能" * 5)
        assert len(result) <= 50

    def test_empty_message_returns_default(self):
        """空消息返回默认标题"""
        from app.services.message_persistence import truncate_title

        result = truncate_title("")
        assert result == "新对话"


# ============================================================
# Test: Full Persistence Flow
# ============================================================


class TestFullPersistenceFlow:
    """Test the complete persistence flow"""

    def test_persist_chat_round(self):
        """完整的一轮对话持久化"""
        from app.services.message_persistence import (
            get_or_create_conversation,
            save_user_message,
            save_assistant_message,
            update_conversation_stats,
        )

        mock_session = MagicMock()

        # Setup mock queries
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        # 1. Get or create conversation
        conv = get_or_create_conversation(
            session=mock_session,
            user_id=1,
            company_id=1,
            title="美妆达人",
        )
        assert conv is not None

        # 2. Save user message
        save_user_message(
            session=mock_session,
            conversation_id=1,
            user_id=1,
            content="帮我找美妆达人",
            sequence_num=1,
        )

        # 3. Save assistant message
        save_assistant_message(
            session=mock_session,
            conversation_id=1,
            content="已为你找到5位美妆达人",
            sequence_num=2,
        )

        # 4. Update conversation stats
        mock_conv = MagicMock(spec=Conversation)
        mock_conv.id = 1
        mock_conv.message_count = 0
        mock_query.first.return_value = mock_conv

        update_conversation_stats(
            session=mock_session,
            conversation_id=1,
            last_message="已为你找到5位美妆达人",
        )

        assert mock_conv.message_count == 1


# ============================================================
# Test: ChatRequest with conversation_id
# ============================================================


class TestChatRequestWithConversationId:
    """Test ChatRequest model includes conversation_id"""

    def test_chat_request_has_conversation_id_field(self):
        """ChatRequest 包含 conversation_id 字段"""
        from app.api.chat import ChatRequest

        req = ChatRequest(
            message="test",
            conversation_id=1,
        )
        assert req.conversation_id == 1

    def test_chat_request_conversation_id_optional(self):
        """conversation_id 为可选字段"""
        from app.api.chat import ChatRequest

        req = ChatRequest(message="test")
        assert req.conversation_id is None
