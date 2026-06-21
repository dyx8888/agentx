"""
Unit tests for Data Analysis Agent (Task 3.3)
Tests for System Prompt, data analysis functions, and Agent function
"""

import pytest
from unittest.mock import MagicMock, patch


# ============================================================
# Test: Data Analysis System Prompt
# ============================================================

class TestDataAnalysisSystemPrompt:
    """Test data analysis system prompt"""

    def test_system_prompt_exists(self):
        """System Prompt 存在"""
        from app.agents.data_analysis import DATA_ANALYSIS_SYSTEM_PROMPT
        assert DATA_ANALYSIS_SYSTEM_PROMPT
        assert isinstance(DATA_ANALYSIS_SYSTEM_PROMPT, str)

    def test_system_prompt_contains_role(self):
        """System Prompt 包含角色定位"""
        from app.agents.data_analysis import DATA_ANALYSIS_SYSTEM_PROMPT
        assert "数据分析" in DATA_ANALYSIS_SYSTEM_PROMPT

    def test_system_prompt_contains_roi(self):
        """System Prompt 包含 ROI 分析"""
        from app.agents.data_analysis import DATA_ANALYSIS_SYSTEM_PROMPT
        assert "ROI" in DATA_ANALYSIS_SYSTEM_PROMPT or "投资回报" in DATA_ANALYSIS_SYSTEM_PROMPT

    def test_system_prompt_contains_output_format(self):
        """System Prompt 包含输出格式要求"""
        from app.agents.data_analysis import DATA_ANALYSIS_SYSTEM_PROMPT
        assert "报告" in DATA_ANALYSIS_SYSTEM_PROMPT or "格式" in DATA_ANALYSIS_SYSTEM_PROMPT


# ============================================================
# Test: calculate_roi
# ============================================================

class TestCalculateROI:
    """Test ROI calculation"""

    def test_roi_calculation_basic(self):
        """基本 ROI 计算"""
        from app.agents.data_analysis import calculate_roi

        result = calculate_roi(gmv=100000, ad_spend=20000)
        assert result["roi"] == 5.0
        assert result["gmv"] == 100000
        assert result["ad_spend"] == 20000

    def test_roi_calculation_break_even(self):
        """盈亏平衡点"""
        from app.agents.data_analysis import calculate_roi

        result = calculate_roi(gmv=10000, ad_spend=10000)
        assert result["roi"] == 1.0

    def test_roi_calculation_loss(self):
        """亏损 ROI"""
        from app.agents.data_analysis import calculate_roi

        result = calculate_roi(gmv=5000, ad_spend=10000)
        assert result["roi"] == 0.5

    def test_roi_zero_spend(self):
        """零投放"""
        from app.agents.data_analysis import calculate_roi

        result = calculate_roi(gmv=10000, ad_spend=0)
        assert result["roi"] == 0.0

    def test_roi_includes_profit(self):
        """ROI 结果包含利润"""
        from app.agents.data_analysis import calculate_roi

        result = calculate_roi(gmv=100000, ad_spend=20000, cost=50000)
        assert "profit" in result
        assert result["profit"] == 30000  # 100000 - 20000 - 50000


# ============================================================
# Test: analyze_data_quality
# ============================================================

class TestAnalyzeDataQuality:
    """Test data quality analysis"""

    def test_data_quality_with_all_fields(self):
        """完整数据质量检查"""
        from app.agents.data_analysis import analyze_data_quality

        data = {"gmv": 100000, "orders": 500, "roi": 3.0}
        result = analyze_data_quality(data)

        assert "completeness" in result
        assert "issues" in result
        assert result["completeness"] == 1.0

    def test_data_quality_with_missing_fields(self):
        """包含缺失字段"""
        from app.agents.data_analysis import analyze_data_quality

        data = {"gmv": 100000, "orders": None, "roi": None}
        result = analyze_data_quality(data)

        assert result["completeness"] < 1.0
        assert len(result["issues"]) > 0

    def test_data_quality_empty_data(self):
        """空数据"""
        from app.agents.data_analysis import analyze_data_quality

        result = analyze_data_quality({})
        assert result["completeness"] == 0.0


# ============================================================
# Test: competitor_analysis
# ============================================================

class TestCompetitorAnalysis:
    """Test competitor analysis"""

    def test_competitor_analysis_basic(self):
        """基本竞品分析"""
        from app.agents.data_analysis import competitor_analysis

        own_data = {"gmv": 100000, "followers": 50000, "engagement_rate": 3.0}
        competitor_data = {"gmv": 150000, "followers": 80000, "engagement_rate": 2.5}

        result = competitor_analysis(own_data, competitor_data)

        assert "comparison" in result
        assert "advantage" in result

    def test_competitor_analysis_identifies_gaps(self):
        """竞品分析识别差距"""
        from app.agents.data_analysis import competitor_analysis

        own_data = {"gmv": 50000, "followers": 10000}
        competitor_data = {"gmv": 200000, "followers": 50000}

        result = competitor_analysis(own_data, competitor_data)

        assert "disadvantage" in result


# ============================================================
# Test: format_analysis_report
# ============================================================

class TestFormatAnalysisReport:
    """Test analysis report formatting"""

    def test_format_report_includes_roi(self):
        """报告包含 ROI 数据"""
        from app.agents.data_analysis import format_analysis_report

        roi_data = {"roi": 3.5, "gmv": 100000, "ad_spend": 28571}
        report = format_analysis_report(roi_data=roi_data)

        assert "3.5" in report or "ROI" in report

    def test_format_report_includes_quality(self):
        """报告包含数据质量"""
        from app.agents.data_analysis import format_analysis_report

        quality_data = {"completeness": 0.95, "issues": ["缺少转化率数据"]}
        report = format_analysis_report(quality_data=quality_data)

        assert "95" in report or "0.95" in report

    def test_format_report_includes_competitor(self):
        """报告包含竞品分析"""
        from app.agents.data_analysis import format_analysis_report

        competitor_data = {
            "comparison": {"gmv": "+50%"},
            "advantage": ["互动率领先"],
            "disadvantage": ["粉丝数落后"],
        }
        report = format_analysis_report(competitor_data=competitor_data)

        assert "竞品" in report or "对手" in report

    def test_format_report_empty(self):
        """空报告"""
        from app.agents.data_analysis import format_analysis_report

        report = format_analysis_report()
        assert len(report) > 0


# ============================================================
# Test: Agent Registration
# ============================================================

class TestDataAnalysisAgentRegistration:
    """Test data analysis agent in registry"""

    def test_data_analysis_in_registry(self):
        """数据分析 Agent 在注册表中"""
        from app.agents import AGENT_REGISTRY
        assert "data_analysis" in AGENT_REGISTRY


# ============================================================
# Test: get_agent_function
# ============================================================

class TestDataAnalysisAgentFunction:
    """Test data analysis agent function"""

    @pytest.mark.asyncio
    async def test_get_agent_function_returns_callable(self):
        """get_agent_function 返回可调用对象"""
        from app.agents.data_analysis import get_agent_function
        func = await get_agent_function()
        assert callable(func)

    @pytest.mark.asyncio
    async def test_agent_function_handles_roi_query(self):
        """Agent 函数处理 ROI 查询"""
        from app.agents.data_analysis import get_agent_function
        func = await get_agent_function()
        result = await func(message="帮我分析投入产出比")
        assert result is not None

    @pytest.mark.asyncio
    async def test_agent_function_handles_data_quality_query(self):
        """Agent 函数处理数据质量查询"""
        from app.agents.data_analysis import get_agent_function
        func = await get_agent_function()
        result = await func(message="检查数据质量")
        assert result is not None

    @pytest.mark.asyncio
    async def test_agent_function_handles_competitor_query(self):
        """Agent 函数处理竞品分析查询"""
        from app.agents.data_analysis import get_agent_function
        func = await get_agent_function()
        result = await func(message="帮我做竞品分析")
        assert result is not None
