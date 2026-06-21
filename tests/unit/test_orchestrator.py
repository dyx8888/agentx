"""
Unit tests for AgentRuntime Orchestrator (Phase 6 coverage)
Tests for initialization, state building, replan, mode selection, token safety
"""

import pytest
from unittest.mock import MagicMock, patch


# ============================================================
# Test: AgentRuntime.__init__
# ============================================================

class TestAgentRuntimeInit:
    """Test AgentRuntime constructor"""

    def test_init_defaults(self):
        """构造函数默认值"""
        from app.runtime.orchestrator import AgentRuntime
        runtime = AgentRuntime()
        assert runtime.llm is None
        assert runtime._initialized is False
        assert runtime._total_tokens_consumed == 0
        assert runtime._loop_iterations == 0

    def test_initialized_property(self):
        """initialized 属性"""
        from app.runtime.orchestrator import AgentRuntime
        runtime = AgentRuntime()
        assert runtime.initialized is False
        runtime._initialized = True
        assert runtime.initialized is True


# ============================================================
# Test: _build_initial_state
# ============================================================

class TestBuildInitialState:
    """Test _build_initial_state"""

    def test_initial_state_structure(self):
        """初始状态结构"""
        from app.runtime.orchestrator import AgentRuntime
        runtime = AgentRuntime()
        state = runtime._build_initial_state(
            message="你好",
            agent_name="master",
            company_id="1",
            trace_id="trace-123"
        )
        assert "messages" in state
        assert len(state["messages"]) == 1
        assert state["messages"][0].content == "你好"
        assert state["company_context"]["agent_name"] == "master"
        assert state["company_context"]["company_id"] == "1"
        assert state["company_context"]["trace_id"] == "trace-123"

    def test_initial_state_defaults(self):
        """初始状态默认值"""
        from app.runtime.orchestrator import AgentRuntime
        runtime = AgentRuntime()
        state = runtime._build_initial_state("test", "agent", "1", "trace")
        assert state["plan"] == {}
        assert state["step_results"] == []
        assert state["reflection"] == {}
        assert state["current_step"] == 0
        assert state["plan_completed"] is False
        assert state["retry_count"] == 0
        assert state["replan_count"] == 0
        assert state["total_tokens_consumed"] == 0
        assert state["token_threshold_warning"] is False

    def test_initial_state_includes_available_tools(self):
        """初始状态包含可用工具"""
        from app.runtime.orchestrator import AgentRuntime
        runtime = AgentRuntime()
        runtime.mcp_tools = [{"name": "search"}]
        state = runtime._build_initial_state("test", "agent", "1", "trace")
        assert state["available_tools"] == [{"name": "search"}]


# ============================================================
# Test: _extract_working_memory
# ============================================================

class TestExtractWorkingMemory:
    """Test _extract_working_memory"""

    def test_extract_with_plan(self):
        """从 state 提取 working memory（含 plan）"""
        from app.runtime.orchestrator import AgentRuntime
        runtime = AgentRuntime()
        state = {
            "working_memory": {},
            "plan": {
                "goal": "分析达人数据",
                "steps": [
                    {"id": "1", "description": "搜索达人"},
                    {"id": "2", "description": "分析数据"},
                ]
            },
            "current_step": 1,
            "step_results": [{"step": "1", "success": True}],
            "retry_count": 0,
        }
        wm = runtime._extract_working_memory(state)
        assert wm.goal == "分析达人数据"
        assert "搜索达人" in wm.pending_actions
        assert "分析数据" in wm.pending_actions

    def test_extract_empty_state(self):
        """从空 state 提取 working memory"""
        from app.runtime.orchestrator import AgentRuntime
        runtime = AgentRuntime()
        state = {}
        wm = runtime._extract_working_memory(state)
        assert wm is not None

    def test_extract_uses_description_as_goal_fallback(self):
        """plan 无 goal 时使用 description"""
        from app.runtime.orchestrator import AgentRuntime
        runtime = AgentRuntime()
        state = {
            "working_memory": {},
            "plan": {
                "description": "备选描述",
                "steps": []
            },
        }
        wm = runtime._extract_working_memory(state)
        assert wm.goal == "备选描述"


# ============================================================
# Test: _dynamic_replan
# ============================================================

class TestDynamicReplan:
    """Test _dynamic_replan"""

    def test_replan_max_reached(self):
        """达到最大重规划次数"""
        from app.runtime.orchestrator import AgentRuntime
        runtime = AgentRuntime()
        state = {"replan_count": 2}
        result = runtime._dynamic_replan(state, "test")
        assert result["plan_completed"] is True

    def test_replan_no_remaining_steps(self):
        """所有步骤已完成"""
        from app.runtime.orchestrator import AgentRuntime
        runtime = AgentRuntime()
        state = {
            "replan_count": 0,
            "plan": {
                "steps": [
                    {"id": "1", "description": "step1"},
                    {"id": "2", "description": "step2"},
                ]
            },
            "step_results": [
                {"step": "1", "success": True},
                {"step": "2", "success": True},
            ],
            "reflection_feedback": [],
        }
        result = runtime._dynamic_replan(state, "test")
        assert result["plan_completed"] is True

    def test_replan_remaining_steps(self):
        """有未完成步骤"""
        from app.runtime.orchestrator import AgentRuntime
        runtime = AgentRuntime()
        state = {
            "replan_count": 0,
            "plan": {
                "steps": [
                    {"id": "1", "description": "step1"},
                    {"id": "2", "description": "step2"},
                    {"id": "3", "description": "step3"},
                ]
            },
            "step_results": [
                {"step": "1", "success": True},
            ],
            "reflection_feedback": [],
            "plan_history": [],
        }
        result = runtime._dynamic_replan(state, "test")
        assert result["plan_completed"] is False
        assert result["replan_count"] == 1
        assert len(result["plan"]["steps"]) == 2  # 剩余 2 个未完成步骤

    def test_replan_with_feedback(self):
        """带反馈的重规划"""
        from app.runtime.orchestrator import AgentRuntime
        runtime = AgentRuntime()
        state = {
            "replan_count": 0,
            "plan": {
                "steps": [
                    {"id": "1", "description": "step1"},
                ]
            },
            "step_results": [
                {"step": "1", "success": False},
            ],
            "reflection_feedback": [{"issue": "数据不完整"}],
            "plan_history": [],
        }
        result = runtime._dynamic_replan(state, "test")
        assert result["plan_completed"] is False


# ============================================================
# Test: _select_agent_mode_fallback
# ============================================================

class TestSelectAgentModeFallback:
    """Test _select_agent_mode_fallback keyword matching"""

    def test_engine_first_keywords(self):
        """搜索/查询关键词 → engine_first"""
        from app.runtime.orchestrator import AgentRuntime
        assert AgentRuntime._select_agent_mode_fallback("搜索达人") == "engine_first"
        assert AgentRuntime._select_agent_mode_fallback("查找数据") == "engine_first"
        assert AgentRuntime._select_agent_mode_fallback("查询订单") == "engine_first"

    def test_workflow_keywords(self):
        """流程/审批关键词 → workflow"""
        from app.runtime.orchestrator import AgentRuntime
        assert AgentRuntime._select_agent_mode_fallback("生成报告") == "workflow"
        assert AgentRuntime._select_agent_mode_fallback("批量导出") == "workflow"

    def test_agent_keywords(self):
        """分析/策略关键词 → agent"""
        from app.runtime.orchestrator import AgentRuntime
        assert AgentRuntime._select_agent_mode_fallback("分析数据") == "agent"
        assert AgentRuntime._select_agent_mode_fallback("优化策略") == "agent"

    def test_no_match_defaults_hybrid(self):
        """无匹配 → hybrid"""
        from app.runtime.orchestrator import AgentRuntime
        assert AgentRuntime._select_agent_mode_fallback("你好") == "hybrid"
        assert AgentRuntime._select_agent_mode_fallback("") == "hybrid"

    def test_engine_first_takes_priority(self):
        """engine_first 优先级最高"""
        from app.runtime.orchestrator import AgentRuntime
        # 同时包含 engine 和 agent 关键词时，engine_first 优先
        result = AgentRuntime._select_agent_mode_fallback("搜索并分析数据")
        assert result == "engine_first"


# ============================================================
# Test: _check_token_safety
# ============================================================

class TestCheckTokenSafety:
    """Test _check_token_safety"""

    def test_safe_when_under_threshold(self):
        """Token 消耗低于阈值"""
        from app.runtime.orchestrator import AgentRuntime
        runtime = AgentRuntime()
        runtime._total_tokens_consumed = 1000
        result = runtime._check_token_safety()
        assert result["safe"] is True
        assert result["warning"] is False
        assert result["total_tokens"] == 1000

    def test_warning_when_near_threshold(self):
        """Token 消耗接近阈值"""
        from app.runtime.orchestrator import AgentRuntime, MAX_AGENT_TOKEN_THRESHOLD, TOKEN_THRESHOLD_WARNING_RATIO
        runtime = AgentRuntime()
        runtime._total_tokens_consumed = int(MAX_AGENT_TOKEN_THRESHOLD * TOKEN_THRESHOLD_WARNING_RATIO)
        result = runtime._check_token_safety()
        assert result["warning"] is True

    def test_unsafe_when_over_threshold(self):
        """Token 消耗超过阈值"""
        from app.runtime.orchestrator import AgentRuntime, MAX_AGENT_TOKEN_THRESHOLD
        runtime = AgentRuntime()
        runtime._total_tokens_consumed = MAX_AGENT_TOKEN_THRESHOLD + 1
        result = runtime._check_token_safety()
        assert result["safe"] is False
        assert result["usage_ratio"] >= 1.0

    def test_includes_iterations(self):
        """包含迭代次数"""
        from app.runtime.orchestrator import AgentRuntime
        runtime = AgentRuntime()
        runtime._loop_iterations = 5
        result = runtime._check_token_safety()
        assert result["current_iterations"] == 5
        assert result["max_iterations"] == 10


# ============================================================
# Test: Constants
# ============================================================

class TestConstants:
    """Test module-level constants"""

    def test_max_loop_iterations(self):
        """最大循环次数"""
        from app.runtime.orchestrator import MAX_AGENT_LOOP_ITERATIONS
        assert MAX_AGENT_LOOP_ITERATIONS == 10

    def test_max_token_threshold(self):
        """Token 阈值"""
        from app.runtime.orchestrator import MAX_AGENT_TOKEN_THRESHOLD
        assert MAX_AGENT_TOKEN_THRESHOLD == 100000

    def test_token_warning_ratio(self):
        """Token 警告比例"""
        from app.runtime.orchestrator import TOKEN_THRESHOLD_WARNING_RATIO
        assert TOKEN_THRESHOLD_WARNING_RATIO == 0.7


# ============================================================
# Test: _select_agent_mode_by_llm (fallback path)
# ============================================================

class TestSelectAgentModeByLLM:
    """Test _select_agent_mode_by_llm"""

    def test_llm_none_falls_back(self):
        """LLM 未初始化时走降级"""
        from app.runtime.orchestrator import AgentRuntime
        runtime = AgentRuntime()
        runtime.llm = None
        result = runtime._select_agent_mode_by_llm("分析数据")
        assert result == "agent"

    def test_llm_exception_falls_back(self):
        """LLM 异常时走降级"""
        from app.runtime.orchestrator import AgentRuntime
        runtime = AgentRuntime()
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("LLM timeout")
        runtime.llm = mock_llm
        result = runtime._select_agent_mode_by_llm("搜索数据")
        assert result == "engine_first"
