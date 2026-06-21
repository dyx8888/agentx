"""
Unit tests for KOL Search Agent (Task 3.1)
Tests for search_kols function, Agent System Prompt, and API endpoints
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.database.models import KolProfile, KolSearchHistory


# ============================================================
# Test: KolSearchAgent System Prompt
# ============================================================

class TestKolSearchSystemPrompt:
    """Test KOL search agent system prompt"""

    def test_system_prompt_exists(self):
        """System Prompt 存在"""
        from app.agents.kol_search import KOL_SEARCH_SYSTEM_PROMPT
        assert KOL_SEARCH_SYSTEM_PROMPT
        assert isinstance(KOL_SEARCH_SYSTEM_PROMPT, str)

    def test_system_prompt_contains_role(self):
        """System Prompt 包含角色定位"""
        from app.agents.kol_search import KOL_SEARCH_SYSTEM_PROMPT
        assert "达人" in KOL_SEARCH_SYSTEM_PROMPT

    def test_system_prompt_contains_platform_mapping(self):
        """System Prompt 包含平台映射"""
        from app.agents.kol_search import KOL_SEARCH_SYSTEM_PROMPT
        # 至少包含一个平台名称
        assert "抖音" in KOL_SEARCH_SYSTEM_PROMPT or "douyin" in KOL_SEARCH_SYSTEM_PROMPT.lower()

    def test_system_prompt_contains_output_format(self):
        """System Prompt 包含输出格式要求"""
        from app.agents.kol_search import KOL_SEARCH_SYSTEM_PROMPT
        assert "格式" in KOL_SEARCH_SYSTEM_PROMPT or "卡片" in KOL_SEARCH_SYSTEM_PROMPT


# ============================================================
# Test: search_kols function
# ============================================================

class TestSearchKols:
    """Test search_kols query function"""

    def test_search_kols_by_query(self):
        """按关键词搜索达人"""
        from app.agents.kol_search import search_kols

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        result = search_kols(
            session=mock_session,
            company_id=1,
            query="美妆",
        )

        assert isinstance(result, list)

    def test_search_kols_by_platform(self):
        """按平台筛选"""
        from app.agents.kol_search import search_kols

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        result = search_kols(
            session=mock_session,
            company_id=1,
            query="美妆",
            platform="douyin",
        )

        assert isinstance(result, list)

    def test_search_kols_by_category(self):
        """按分类筛选"""
        from app.agents.kol_search import search_kols

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        result = search_kols(
            session=mock_session,
            company_id=1,
            query="美妆",
            category="美妆",
        )

        assert isinstance(result, list)

    def test_search_kols_by_followers_range(self):
        """按粉丝数范围筛选"""
        from app.agents.kol_search import search_kols

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        result = search_kols(
            session=mock_session,
            company_id=1,
            query="美妆",
            min_followers=10000,
            max_followers=100000,
        )

        assert isinstance(result, list)

    def test_search_kols_sort_by_followers(self):
        """按粉丝数排序"""
        from app.agents.kol_search import search_kols

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        result = search_kols(
            session=mock_session,
            company_id=1,
            query="美妆",
            sort_by="followers",
        )

        assert isinstance(result, list)

    def test_search_kols_enforces_company_isolation(self):
        """强制公司隔离"""
        from app.agents.kol_search import search_kols

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        search_kols(
            session=mock_session,
            company_id=42,
            query="美妆",
        )

        # 验证 filter 被调用（company_id 过滤）
        assert mock_query.filter.called


# ============================================================
# Test: format_kol_results
# ============================================================

class TestFormatKolResults:
    """Test KOL result formatting"""

    def test_format_empty_results(self):
        """空结果格式化"""
        from app.agents.kol_search import format_kol_results

        result = format_kol_results([])
        assert "未找到" in result

    def test_format_single_kol(self):
        """单个达人结果格式化"""
        from app.agents.kol_search import format_kol_results

        kol = {
            "id": 1,
            "name": "李佳琦",
            "platform": "douyin",
            "followers": 48500000,
            "engagement_rate": 3.5,
            "category": "美妆",
            "price_range_low": 8000,
            "price_range_high": 15000,
        }
        result = format_kol_results([kol])
        assert "李佳琦" in result
        assert "douyin" in result.lower() or "抖音" in result

    def test_format_multiple_kols(self):
        """多个达人结果格式化"""
        from app.agents.kol_search import format_kol_results

        kols = [
            {"id": 1, "name": "达人A", "platform": "douyin", "followers": 100000, "engagement_rate": 2.5, "category": "美妆"},
            {"id": 2, "name": "达人B", "platform": "xiaohongshu", "followers": 50000, "engagement_rate": 4.0, "category": "穿搭"},
        ]
        result = format_kol_results(kols)
        assert "达人A" in result
        assert "达人B" in result

    def test_format_includes_followers(self):
        """结果包含粉丝数"""
        from app.agents.kol_search import format_kol_results

        kol = {
            "id": 1,
            "name": "测试达人",
            "platform": "douyin",
            "followers": 100000,
            "engagement_rate": 2.5,
            "category": "美妆",
        }
        result = format_kol_results([kol])
        assert "10" in result  # 10万格式化为 "10.0万"


# ============================================================
# Test: Agent Registration
# ============================================================

class TestKolSearchAgentRegistration:
    """Test KOL search agent in registry"""

    def test_kol_search_in_registry(self):
        """达人搜索 Agent 在注册表中"""
        from app.agents import AGENT_REGISTRY
        assert "kol_search" in AGENT_REGISTRY

    def test_kol_search_has_module_path(self):
        """达人搜索 Agent 有模块路径"""
        from app.agents import AGENT_REGISTRY
        assert AGENT_REGISTRY["kol_search"]["module"]

    def test_kol_search_has_display_name(self):
        """达人搜索 Agent 有显示名称"""
        from app.agents import AGENT_REGISTRY
        assert AGENT_REGISTRY["kol_search"]["name_display"]

    def test_kol_search_has_role(self):
        """达人搜索 Agent 有角色"""
        from app.agents import AGENT_REGISTRY
        assert AGENT_REGISTRY["kol_search"]["role"]


# ============================================================
# Test: get_agent_function
# ============================================================

class TestKolSearchAgentFunction:
    """Test KOL search agent function"""

    @pytest.mark.asyncio
    async def test_get_agent_function_returns_callable(self):
        """get_agent_function 返回可调用对象"""
        from app.agents.kol_search import get_agent_function
        func = await get_agent_function()
        assert callable(func)

    @pytest.mark.asyncio
    async def test_agent_function_accepts_message(self):
        """Agent 函数接受 message 参数"""
        from app.agents.kol_search import get_agent_function
        func = await get_agent_function()
        result = await func(message="帮我找美妆达人")
        assert result is not None


# ============================================================
# Test: save_search_history
# ============================================================

class TestSaveSearchHistory:
    """Test search history saving"""

    def test_save_search_history(self):
        """保存搜索历史"""
        from app.agents.kol_search import save_search_history

        mock_session = MagicMock()

        save_search_history(
            session=mock_session,
            user_id=1,
            company_id=1,
            query="美妆达人",
            result_count=5,
        )

        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_save_search_history_with_filters(self):
        """保存搜索历史 — 带筛选条件"""
        from app.agents.kol_search import save_search_history

        mock_session = MagicMock()

        save_search_history(
            session=mock_session,
            user_id=1,
            company_id=1,
            query="美妆达人",
            platform_filter="douyin",
            category_filter="美妆",
            result_count=3,
            search_duration_ms=150,
        )

        call_args = mock_session.add.call_args[0][0]
        assert call_args.platform_filter == "douyin"
        assert call_args.category_filter == "美妆"
        assert call_args.search_duration_ms == 150
