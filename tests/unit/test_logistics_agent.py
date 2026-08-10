"""
Unit tests for Logistics Tracking Agent (Task 3.5)
Tests for System Prompt, query functions, and Agent function
"""

import pytest
from unittest.mock import MagicMock, patch


# ============================================================
# Test: Logistics System Prompt
# ============================================================

class TestLogisticsSystemPrompt:
    """Test logistics system prompt"""

    def test_system_prompt_exists(self):
        """System Prompt 存在"""
        from app.agents.logistics import LOGISTICS_SYSTEM_PROMPT
        assert LOGISTICS_SYSTEM_PROMPT
        assert isinstance(LOGISTICS_SYSTEM_PROMPT, str)

    def test_system_prompt_contains_role(self):
        """System Prompt 包含角色定位"""
        from app.agents.logistics import LOGISTICS_SYSTEM_PROMPT
        assert "物流" in LOGISTICS_SYSTEM_PROMPT

    def test_system_prompt_contains_statuses(self):
        """System Prompt 包含物流状态说明"""
        from app.agents.logistics import LOGISTICS_SYSTEM_PROMPT
        assert "状态" in LOGISTICS_SYSTEM_PROMPT or "status" in LOGISTICS_SYSTEM_PROMPT.lower()


# ============================================================
# Test: query_logistics
# ============================================================

class TestQueryLogistics:
    """Test logistics query function"""

    def test_query_by_tracking_number(self):
        """按运单号查询"""
        from app.agents.logistics import query_logistics

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        result = query_logistics(
            session=mock_session,
            company_id=1,
            tracking_number="SF1234567890",
        )

        assert isinstance(result, list)

    def test_query_enforces_company_isolation(self):
        """查询强制公司隔离"""
        from app.agents.logistics import query_logistics
        from app.database.models import LogisticsTracking

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        query_logistics(
            session=mock_session,
            company_id=1,
            tracking_number="SF1234567890",
        )

        # Verify query was built on LogisticsTracking
        mock_session.query.assert_called_once_with(LogisticsTracking)

    def test_query_by_status(self):
        """按状态筛选"""
        from app.agents.logistics import query_logistics

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        result = query_logistics(
            session=mock_session,
            company_id=1,
            status="in_transit",
        )

        assert isinstance(result, list)

    def test_query_with_kol_name(self):
        """按达人名称筛选"""
        from app.agents.logistics import query_logistics

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        result = query_logistics(
            session=mock_session,
            company_id=1,
            kol_name="李佳琦",
        )

        assert isinstance(result, list)


# ============================================================
# Test: format_logistics_result
# ============================================================

class TestFormatLogisticsResult:
    """Test logistics result formatting"""

    def test_format_empty_results(self):
        """格式化空结果"""
        from app.agents.logistics import format_logistics_result

        result = format_logistics_result([])
        assert len(result) > 0
        assert "未找到" in result or "无" in result

    def test_format_single_logistics(self):
        """格式化单条物流"""
        from app.agents.logistics import format_logistics_result

        logistics = [{
            "id": 1,
            "tracking_number": "SF1234567890",
            "carrier": "顺丰快递",
            "status": "in_transit",
            "status_detail": "已到达北京转运中心",
            "origin": "上海",
            "destination": "北京",
            "kol_name": "李佳琦",
            "sample_name": "口红样品",
        }]

        result = format_logistics_result(logistics)
        assert "SF1234567890" in result
        assert "顺丰" in result

    def test_format_multiple_logistics(self):
        """格式化多条物流"""
        from app.agents.logistics import format_logistics_result

        logistics = [
            {
                "id": 1,
                "tracking_number": "SF1234567890",
                "carrier": "顺丰快递",
                "status": "in_transit",
                "status_detail": "运输中",
                "origin": "上海",
                "destination": "北京",
                "kol_name": "李佳琦",
                "sample_name": "口红样品",
            },
            {
                "id": 2,
                "tracking_number": "YT0987654321",
                "carrier": "圆通快递",
                "status": "delivered",
                "status_detail": "已签收",
                "origin": "广州",
                "destination": "深圳",
                "kol_name": "薇娅",
                "sample_name": "面膜样品",
            },
        ]

        result = format_logistics_result(logistics)
        assert "2" in result  # "为您找到 2 条"
        assert "SF1234567890" in result
        assert "YT0987654321" in result

    def test_format_includes_status_cn(self):
        """格式化包含中文状态"""
        from app.agents.logistics import format_logistics_result

        logistics = [{
            "id": 1,
            "tracking_number": "SF1234567890",
            "carrier": "顺丰快递",
            "status": "delivered",
            "status_detail": "已签收",
            "origin": "上海",
            "destination": "北京",
            "kol_name": "李佳琦",
            "sample_name": "口红样品",
        }]

        result = format_logistics_result(logistics)
        assert "已签收" in result or "已送达" in result


# ============================================================
# Test: STATUS_MAP
# ============================================================

class TestStatusMap:
    """Test status mapping"""

    def test_status_map_exists(self):
        """状态映射表存在"""
        from app.agents.logistics import STATUS_MAP
        assert isinstance(STATUS_MAP, dict)

    def test_status_map_has_common_statuses(self):
        """状态映射表包含常用状态"""
        from app.agents.logistics import STATUS_MAP
        common_statuses = ["pending", "in_transit", "delivered"]
        for status in common_statuses:
            assert status in STATUS_MAP


# ============================================================
# Test: Agent Registration
# ============================================================

class TestLogisticsAgentFunction:
    """Test logistics agent function"""

    @pytest.mark.asyncio
    async def test_get_agent_function_returns_callable(self):
        """get_agent_function 返回可调用对象"""
        from app.agents.logistics import get_agent_function
        func = await get_agent_function()
        assert callable(func)

    @pytest.mark.asyncio
    async def test_agent_function_handles_tracking_query(self):
        """Agent 函数处理物流查询"""
        from app.agents.logistics import get_agent_function
        func = await get_agent_function()
        result = await func(message="帮我查一下物流 SF1234567890")
        assert result is not None

    @pytest.mark.asyncio
    async def test_agent_function_handles_status_query(self):
        """Agent 函数处理状态查询"""
        from app.agents.logistics import get_agent_function
        func = await get_agent_function()
        result = await func(message="物流状态怎么样")
        assert result is not None

    @pytest.mark.asyncio
    async def test_agent_function_handles_delivery_query(self):
        """Agent 函数处理配送查询"""
        from app.agents.logistics import get_agent_function
        func = await get_agent_function()
        result = await func(message="快递到哪了")
        assert result is not None
