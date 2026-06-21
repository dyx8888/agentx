"""
Unit tests for Master Orchestrator Agent (Task 2.4)
Tests for intent recognition, task decomposition, and result aggregation
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ============================================================
# Test Master System Prompt
# ============================================================

class TestMasterSystemPrompt:
    """Test Master system prompt definition"""

    def test_prompt_exists(self):
        """Master system prompt 已定义"""
        from app.agents.master import MASTER_SYSTEM_PROMPT

        assert MASTER_SYSTEM_PROMPT is not None
        assert len(MASTER_SYSTEM_PROMPT) > 0

    def test_prompt_contains_role(self):
        """Prompt 包含角色定位"""
        from app.agents.master import MASTER_SYSTEM_PROMPT

        assert "编排" in MASTER_SYSTEM_PROMPT or "Master" in MASTER_SYSTEM_PROMPT or "调度" in MASTER_SYSTEM_PROMPT

    def test_prompt_contains_routing_rules(self):
        """Prompt 包含路由规则"""
        from app.agents.master import MASTER_SYSTEM_PROMPT

        assert "达人" in MASTER_SYSTEM_PROMPT or "kol_search" in MASTER_SYSTEM_PROMPT.lower()

    def test_prompt_contains_task_decomposition(self):
        """Prompt 包含任务拆解说明"""
        from app.agents.master import MASTER_SYSTEM_PROMPT

        assert "拆解" in MASTER_SYSTEM_PROMPT or "分解" in MASTER_SYSTEM_PROMPT or "子任务" in MASTER_SYSTEM_PROMPT

    def test_prompt_contains_result_aggregation(self):
        """Prompt 包含结果汇总说明"""
        from app.agents.master import MASTER_SYSTEM_PROMPT

        assert "汇总" in MASTER_SYSTEM_PROMPT or "整合" in MASTER_SYSTEM_PROMPT or "合并" in MASTER_SYSTEM_PROMPT


# ============================================================
# Test Intent Recognition
# ============================================================

class TestIntentRecognition:
    """Test intent recognition logic"""

    def test_detect_kol_search_intent(self):
        """识别达人搜索意图"""
        from app.agents.master import recognize_intent

        result = recognize_intent("帮我找美妆达人")
        assert "kol_search" in result or "达人搜索" in result

    def test_detect_kol_search_keywords(self):
        """通过关键字识别达人搜索"""
        from app.agents.master import recognize_intent

        for keyword in ["达人", "找达人", "达人推荐", "搜索达人", "KOL"]:
            result = recognize_intent(f"请{keyword}")
            assert "kol_search" in result or "达人搜索" in result, f"Failed for keyword: {keyword}"

    def test_detect_data_analysis_intent(self):
        """识别数据分析意图"""
        from app.agents.master import recognize_intent

        for keyword in ["数据分析", "分析数据", "ROI", "竞品", "报表"]:
            result = recognize_intent(f"请{keyword}")
            assert "data_analysis" in result or "数据分析" in result, f"Failed for keyword: {keyword}"

    def test_detect_content_planning_intent(self):
        """识别内容策划意图"""
        from app.agents.master import recognize_intent

        for keyword in ["脚本", "文案", "策划", "种草", "内容"]:
            result = recognize_intent(f"请{keyword}")
            assert "content_operation" in result or "内容运营" in result, f"Failed for keyword: {keyword}"

    def test_detect_logistics_intent(self):
        """识别物流跟踪意图"""
        from app.agents.master import recognize_intent

        for keyword in ["物流", "快递", "发货", "样品", "仓储"]:
            result = recognize_intent(f"请{keyword}")
            assert "warehouse_logistics" in result or "仓储物流" in result, f"Failed for keyword: {keyword}"

    def test_multi_intent_detection(self):
        """多意图场景 — 复杂任务拆解"""
        from app.agents.master import recognize_intent

        result = recognize_intent("帮我分析数据并策划脚本")
        assert isinstance(result, list)
        assert len(result) >= 2

    def test_unknown_intent_default(self):
        """未知意图返回默认值"""
        from app.agents.master import recognize_intent

        result = recognize_intent("你好")
        assert result is not None


# ============================================================
# Test Task Decomposition
# ============================================================

class TestTaskDecomposition:
    """Test task decomposition logic"""

    def test_decompose_simple_task(self):
        """简单任务直接返回单个子任务"""
        from app.agents.master import decompose_task

        subtasks = decompose_task("帮我找美妆达人", ["kol_search"])
        assert len(subtasks) == 1
        assert subtasks[0]["agent"] == "kol_search"

    def test_decompose_complex_task(self):
        """复杂任务拆解为多个子任务"""
        from app.agents.master import decompose_task

        subtasks = decompose_task(
            "帮我分析数据并策划脚本",
            ["data_analysis", "content_operation"]
        )
        assert len(subtasks) >= 2

    def test_decompose_task_with_dependencies(self):
        """有依赖关系的任务保持顺序"""
        from app.agents.master import decompose_task

        subtasks = decompose_task(
            "先分析数据，再根据数据策划脚本",
            ["data_analysis", "content_operation"]
        )
        assert len(subtasks) >= 2
        # 数据分析应该在前
        assert subtasks[0]["agent"] == "data_analysis"

    def test_decompose_all_subtasks_have_description(self):
        """每个子任务都有描述"""
        from app.agents.master import decompose_task

        subtasks = decompose_task(
            "帮我分析数据并策划脚本",
            ["data_analysis", "content_operation"]
        )
        for st in subtasks:
            assert "description" in st
            assert len(st["description"]) > 0


# ============================================================
# Test Result Aggregation
# ============================================================

class TestResultAggregation:
    """Test result aggregation logic"""

    def test_aggregate_single_result(self):
        """单个结果直接返回"""
        from app.agents.master import aggregate_results

        results = [{"agent": "kol_search", "result": "找到了5位美妆达人"}]
        aggregated = aggregate_results("帮我找美妆达人", results)
        assert "美妆达人" in aggregated

    def test_aggregate_multiple_results(self):
        """多个结果合并输出"""
        from app.agents.master import aggregate_results

        results = [
            {"agent": "data_analysis", "result": "ROI为2.5"},
            {"agent": "content_operation", "result": "策划了3条脚本"},
        ]
        aggregated = aggregate_results("帮我分析数据并策划脚本", results)
        assert "ROI" in aggregated
        assert "脚本" in aggregated

    def test_aggregate_empty_results(self):
        """空结果返回提示"""
        from app.agents.master import aggregate_results

        aggregated = aggregate_results("帮我找美妆达人", [])
        assert len(aggregated) > 0

    def test_aggregate_includes_original_query_context(self):
        """汇总结果包含原始问题上下文"""
        from app.agents.master import aggregate_results

        results = [{"agent": "kol_search", "result": "找到了3位达人"}]
        aggregated = aggregate_results("帮我找美妆达人", results)
        assert "达人" in aggregated


# ============================================================
# Test Agent Registration
# ============================================================

class TestMasterAgentRegistration:
    """Test Master agent is registered in the agent registry"""

    def test_master_in_registry(self):
        """Master agent 已在注册表中"""
        from app.agents import AGENT_REGISTRY

        assert "master" in AGENT_REGISTRY

    def test_master_has_module_path(self):
        """Master agent 有正确的模块路径"""
        from app.agents import AGENT_REGISTRY

        assert AGENT_REGISTRY["master"]["module"] == "app.agents.master"

    def test_master_has_display_name(self):
        """Master agent 有显示名称"""
        from app.agents import AGENT_REGISTRY

        assert "name_display" in AGENT_REGISTRY["master"]
        assert len(AGENT_REGISTRY["master"]["name_display"]) > 0

    def test_master_has_role(self):
        """Master agent 有角色定义"""
        from app.agents import AGENT_REGISTRY

        assert "role" in AGENT_REGISTRY["master"]


# ============================================================
# Test Master Agent Function (get_agent_function)
# ============================================================

class TestMasterAgentFunction:
    """Test the callable agent function"""

    @pytest.mark.asyncio
    async def test_get_agent_function_returns_callable(self):
        """get_agent_function 返回可调用函数"""
        from app.agents.master import get_agent_function

        func = await get_agent_function()
        assert callable(func)

    @pytest.mark.asyncio
    async def test_agent_function_accepts_message(self):
        """agent function 接受消息参数"""
        from app.agents.master import get_agent_function

        func = await get_agent_function()
        import inspect

        sig = inspect.signature(func)
        params = list(sig.parameters.keys())
        assert "message" in params or "state" in params

    @pytest.mark.asyncio
    async def test_agent_function_handles_kol_search(self):
        """agent function 处理达人搜索请求"""
        with patch('app.agents.master.recognize_intent') as mock_intent:
            mock_intent.return_value = ["kol_search"]
            with patch('app.agents.master.decompose_task') as mock_decompose:
                mock_decompose.return_value = [
                    {"agent": "kol_search", "description": "搜索美妆达人"}
                ]
                with patch('app.agents.master.aggregate_results') as mock_aggregate:
                    mock_aggregate.return_value = "已为你找到美妆达人"

                    from app.agents.master import get_agent_function
                    func = await get_agent_function()

                    result = await func(message="帮我找美妆达人")
                    assert result is not None
