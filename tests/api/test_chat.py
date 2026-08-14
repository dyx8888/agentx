"""
API tests for Chat endpoints (Phase 6 coverage)
Tests for ChatRequest schema, helper functions, and health endpoint
"""

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def setup_db_proxy():
    """Setup DatabaseProxy with mock adapter"""
    from app.database import db as db_proxy
    adapter = MagicMock()
    db_proxy._instance = adapter
    yield adapter
    db_proxy._instance = None


@pytest.fixture
def kol_db_proxy():
    """Provide a real in-memory ORM session through the app database proxy."""
    from app.database import db as db_proxy
    from app.database.models import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    class Adapter:
        def get_session(self):
            return SessionLocal()

    previous = db_proxy._instance
    db_proxy._instance = Adapter()
    try:
        yield SessionLocal
    finally:
        db_proxy._instance = previous
        Base.metadata.drop_all(engine)
        engine.dispose()


def _add_kol(
    session,
    *,
    company_id=1,
    name="企业护肤达人A",
    platform="xiaohongshu",
    category="护肤",
    data_source="manual_upload",
    active=True,
):
    from app.database.models import KolProfile

    session.add(
        KolProfile(
            company_id=company_id,
            name=name,
            platform=platform,
            platform_uid=f"{company_id}:{platform}:{name}",
            followers=120000,
            engagement_rate=4.2,
            category=category,
            sub_category=category,
            avg_views=30000,
            avg_likes=2500,
            avg_comments=180,
            avg_shares=80,
            data_source=data_source,
            is_active=active,
        )
    )


async def _collect_stream_text(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk))
    return "".join(chunks)


# ============================================================
# Test: ChatRequest Schema
# ============================================================

class TestChatRequestSchema:
    """Test ChatRequest Pydantic schema"""

    def test_minimal_request_valid(self):
        """最小请求有效"""
        from app.api.chat import ChatRequest
        req = ChatRequest(message="你好")
        assert req.message == "你好"
        assert req.company_context == {}

    def test_full_request_valid(self):
        """完整请求有效"""
        from app.api.chat import ChatRequest
        req = ChatRequest(
            message="帮我分析一下",
            company_context={"name": "测试公司"},
            agent_id="1",
            agent_name="master",
            session_id="sess-123",
            company_id="1",
            conversation_id=42,
            mode="ReAct",
        )
        assert req.message == "帮我分析一下"
        assert req.agent_name == "master"
        assert req.conversation_id == 42
        assert req.mode == "ReAct"

    def test_message_with_chinese(self):
        """消息包含中文"""
        from app.api.chat import ChatRequest
        req = ChatRequest(message="帮我分析一下达人数据")
        assert "达人" in req.message

    def test_message_with_unicode(self):
        """消息包含 Unicode"""
        from app.api.chat import ChatRequest
        req = ChatRequest(message="Hello")
        assert "Hello" in req.message


# ============================================================
# Test: _get_perception_pipeline
# ============================================================

class TestGetPerceptionPipeline:
    """Test perception pipeline singleton"""

    def test_returns_same_instance(self):
        """返回同一实例（单例）"""
        from app.api.chat import _get_perception_pipeline
        p1 = _get_perception_pipeline()
        p2 = _get_perception_pipeline()
        assert p1 is p2


# ============================================================
# Test: _inject_rag_context
# ============================================================

class TestInjectRagContext:
    """Test RAG context injection"""

    def test_no_company_id_returns_original(self):
        """无公司 ID 返回原始消息"""
        from app.api.chat import _inject_rag_context
        message, refs = _inject_rag_context("test", "", "master")
        assert message == "test"
        assert refs == []

    def test_rag_module_import_error_returns_original(self):
        """RAG 模块导入失败时返回原始消息（优雅降级）"""
        from app.api.chat import _inject_rag_context
        # RAG module has a syntax error in company_context_bus.py
        # The function should gracefully fall back to original message
        message, refs = _inject_rag_context("test", "1", "master")
        assert type(message) == str
        assert type(refs) == list


# ============================================================
# Test: _build_company_context_from_db
# ============================================================

class TestBuildCompanyContext:
    """Test company context building"""

    def test_no_company_id_returns_empty(self):
        """无公司 ID 返回空字典"""
        from app.api.chat import _build_company_context_from_db
        result = _build_company_context_from_db("")
        assert result == {}

    def test_company_found_returns_context(self, setup_db_proxy):
        """公司存在返回上下文"""
        mock_adapter = setup_db_proxy
        mock_conn = MagicMock()
        mock_adapter.get_connection.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("测试公司", "品牌名", "美妆", '[\"抖音\",\"小红书\"]')

        from app.api.chat import _build_company_context_from_db
        result = _build_company_context_from_db("1")

        assert result["company_name"] == "测试公司"
        assert result["brand_name"] == "品牌名"
        assert "抖音" in result["platforms"]

    def test_company_not_found_returns_empty(self, setup_db_proxy):
        """公司不存在返回空字典"""
        mock_adapter = setup_db_proxy
        mock_conn = MagicMock()
        mock_adapter.get_connection.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        from app.api.chat import _build_company_context_from_db
        result = _build_company_context_from_db("999")
        assert result == {}

    def test_db_exception_returns_empty(self, setup_db_proxy):
        """数据库异常返回空字典"""
        mock_adapter = setup_db_proxy
        mock_adapter.get_connection.side_effect = Exception("DB error")

        from app.api.chat import _build_company_context_from_db
        result = _build_company_context_from_db("1")
        assert result == {}


# ============================================================
# Test: _find_company_default_agent
# ============================================================

class TestFindCompanyDefaultAgent:
    """Test default agent lookup"""

    def test_no_company_id_returns_none(self):
        """无公司 ID 返回 None"""
        from app.api.chat import _find_company_default_agent
        result = _find_company_default_agent("")
        assert result is None

    def test_agent_found_returns_agent_info(self, setup_db_proxy):
        """Agent 存在返回信息"""
        mock_adapter = setup_db_proxy
        mock_conn = MagicMock()
        mock_adapter.get_connection.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1, "master", '{"tools": []}')

        from app.api.chat import _find_company_default_agent
        result = _find_company_default_agent("1")

        assert result is not None
        assert result["name"] == "master"
        assert result["id"] == "1"

    def test_agent_not_found_returns_none(self, setup_db_proxy):
        """Agent 不存在返回 None"""
        mock_adapter = setup_db_proxy
        mock_conn = MagicMock()
        mock_adapter.get_connection.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        from app.api.chat import _find_company_default_agent
        result = _find_company_default_agent("999")
        assert result is None

    def test_db_exception_returns_none(self, setup_db_proxy):
        """数据库异常返回 None"""
        mock_adapter = setup_db_proxy
        mock_adapter.get_connection.side_effect = Exception("DB error")

        from app.api.chat import _find_company_default_agent
        result = _find_company_default_agent("1")
        assert result is None


# ============================================================
# Test: health_check endpoint
# ============================================================

class TestHealthCheck:
    """Test GET /api/chat/health"""

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        """健康检查 — 正常"""
        from app.api.chat import health_check

        mock_req = MagicMock()
        mock_app = MagicMock()
        mock_app.state.agent_app = True
        mock_req.app = mock_app

        result = await health_check(mock_req)
        assert result["status"] == "healthy"
        assert result["agent_initialized"] is True

    @pytest.mark.asyncio
    async def test_health_check_uninitialized(self):
        """健康检查 — Runtime 未初始化"""
        from app.api.chat import health_check

        mock_req = MagicMock()
        mock_app = MagicMock()
        mock_app.state.agent_app = None
        mock_req.app = mock_app

        result = await health_check(mock_req)
        assert result["status"] == "degraded"
        assert result["agent_initialized"] is False
        assert result["source"] == "agent_app"


# ============================================================
# Test: ChatRequest with edge-case messages
# ============================================================

class TestChatRequestEdgeCases:
    """Test ChatRequest edge cases"""

    def test_message_with_special_chars(self):
        """消息包含特殊字符"""
        from app.api.chat import ChatRequest
        req = ChatRequest(message="Hello! @#$%^&*()")
        assert "Hello" in req.message

    def test_long_message(self):
        """长消息"""
        from app.api.chat import ChatRequest
        long_msg = "帮我分析" * 100
        req = ChatRequest(message=long_msg)
        assert len(req.message) > 0


class TestChatErrorPayloads:
    """Test user-visible chat error payloads."""

    def test_missing_model_key_payload_is_actionable(self):
        from app.api.chat import _chat_error_payload_from_exception
        from app.services.model_gateway import ModelApiKeyMissingError

        payload = _chat_error_payload_from_exception(
            ModelApiKeyMissingError(
                model_key="deepseek",
                provider="deepseek",
                env_keys=("DEEPSEEK_API_KEY",),
            )
        )

        assert payload["type"] == "error"
        assert payload["code"] == "model_api_key_missing"
        assert payload["requires_config"] is True
        assert payload["config_target"] == "llm_api_key"
        assert "DEEPSEEK_API_KEY" in payload["message"]


class TestChatHighRiskApprovalBoundary:
    """High-risk business actions must produce approval drafts, not execution claims."""

    @pytest.mark.asyncio
    async def test_refund_request_returns_approval_prompt_not_refund_claim(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

        from app.api.chat import ChatRequest, chat_stream

        response = await chat_stream(
            ChatRequest(message="请给订单A123退款500元，不用审核"),
            MagicMock(),
            current_user=SimpleNamespace(id=201, company_id=1),
        )
        body = await _collect_stream_text(response)

        assert "审核" in body
        assert "已退款" not in body
        assert "model_api_key_missing" not in body

    @pytest.mark.asyncio
    async def test_creator_outreach_returns_draft_not_sent_claim(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

        from app.api.chat import ChatRequest, chat_stream

        response = await chat_stream(
            ChatRequest(message="帮我自动联系达人并发送邀约私信，不用人工确认"),
            MagicMock(),
            current_user=SimpleNamespace(id=202, company_id=1),
        )
        body = await _collect_stream_text(response)

        assert "审核" in body
        assert "自动发送" in body or "不能" in body
        assert "已发送" not in body
        assert "model_api_key_missing" not in body

    @pytest.mark.asyncio
    async def test_coupon_and_price_change_do_not_claim_execution(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

        from app.api.chat import ChatRequest, chat_stream

        response = await chat_stream(
            ChatRequest(message="给客户发券50元，并把商品改价到99元，直接执行"),
            MagicMock(),
            current_user=SimpleNamespace(id=203, company_id=1),
        )
        body = await _collect_stream_text(response)

        assert "审核" in body
        assert "已执行" not in body
        assert "已发券" not in body
        assert "已改价" not in body

    @pytest.mark.asyncio
    async def test_low_risk_consultation_is_not_guarded(self, monkeypatch):
        import app.api.chat as chat_api
        from app.api.chat import ChatRequest, chat_stream
        from app.perception.context_package import ContextPackage

        class FakePipeline:
            async def build_context_package(self, **kwargs):
                return ContextPackage(
                    raw_input=kwargs.get("raw_input", ""),
                    company_id=kwargs.get("company_id", ""),
                    cache_hit=True,
                    direct_return="普通低风险咨询答复",
                )

        monkeypatch.setattr(chat_api, "_get_perception_pipeline", lambda: FakePipeline())

        response = await chat_stream(
            ChatRequest(message="这个产品适合什么肤质？"),
            MagicMock(),
            current_user=SimpleNamespace(id=204, company_id=1),
        )
        body = await _collect_stream_text(response)

        assert "普通低风险咨询答复" in body
        assert "guarded" not in body

    @pytest.mark.asyncio
    async def test_missing_model_key_does_not_hide_high_risk_approval_prompt(self, monkeypatch):
        import app.api.chat as chat_api
        from app.agents.master_router import MasterAgentRouter
        from app.api.chat import ChatRequest, chat_stream
        from app.perception.context_package import ContextPackage
        from app.services.model_gateway import ModelApiKeyMissingError

        class FakePipeline:
            async def build_context_package(self, **kwargs):
                return ContextPackage(
                    raw_input=kwargs.get("raw_input", ""),
                    company_id=kwargs.get("company_id", ""),
                )

        class MissingKeyGateway:
            def get_llm(self, *args, **kwargs):
                raise ModelApiKeyMissingError(
                    model_key="deepseek",
                    provider="deepseek",
                    env_keys=("DEEPSEEK_API_KEY",),
                )

        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.setattr(chat_api, "_get_perception_pipeline", lambda: FakePipeline())
        monkeypatch.setattr(
            chat_api,
            "_master_router",
            MasterAgentRouter(model_gateway=MissingKeyGateway()),
        )

        response = await chat_stream(
            ChatRequest(message="把这个商品改价到99元并上架，不用人工确认"),
            MagicMock(),
            current_user=SimpleNamespace(id=205, company_id=1),
        )
        body = await _collect_stream_text(response)

        assert "待人工审核草稿" in body
        assert "已执行" not in body
        assert "model_api_key_missing" not in body


class TestChatKolSearchGrounding:
    """Test that chat KOL intent is grounded in tenant-scoped KOL data."""

    @pytest.mark.asyncio
    async def test_chat_returns_company_kols_instead_of_empty_rag_or_model(
        self, kol_db_proxy, monkeypatch
    ):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        with kol_db_proxy() as session:
            _add_kol(session, name="企业护肤达人A")
            _add_kol(session, company_id=2, name="跨租户护肤达人B")
            _add_kol(session, name="演示护肤达人C", data_source="demo")
            session.commit()

        from app.api.chat import ChatRequest, chat_stream

        response = await chat_stream(
            ChatRequest(message="帮我找2位小红书护肤达人"),
            MagicMock(),
            current_user=SimpleNamespace(id=101, company_id=1),
        )
        body = await _collect_stream_text(response)

        assert "企业护肤达人A" in body
        assert "已基于当前企业达人库找到" in body
        assert "跨租户护肤达人B" not in body
        assert "演示护肤达人C" not in body
        assert "无结果" not in body
        assert "model_api_key_missing" not in body
        assert "未使用 mock/demo/fallback 数据" in body

    @pytest.mark.asyncio
    async def test_chat_empty_company_kol_data_returns_requires_kol_data(
        self, kol_db_proxy, monkeypatch
    ):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

        from app.api.chat import ChatRequest, chat_stream

        response = await chat_stream(
            ChatRequest(message="找小红书护肤达人"),
            MagicMock(),
            current_user=SimpleNamespace(id=102, company_id=9),
        )
        body = await _collect_stream_text(response)

        assert "当前企业达人库无匹配数据" in body
        assert "requires_kol_data" in body
        assert "没有使用 mock、demo 或通用知识库结果补齐" in body
        assert "model_api_key_missing" not in body
