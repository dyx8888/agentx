"""
16.2.4 集成测试：Engine主导 → 客服投诉流程
验证 Engine 主导模式下 Engine → Agent 的协作链路
"""
import os
import tempfile
import yaml
from unittest.mock import MagicMock, patch

import pytest


class TestEngineAgentFlow:
    """Engine-Agent 混合模式集成测试"""

    @pytest.fixture
    def temp_workflow_dir(self):
        """创建临时工作流目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workflows_dir = os.path.join(tmpdir, "workflows")
            os.makedirs(workflows_dir, exist_ok=True)
            yield workflows_dir

    @pytest.fixture
    def loader(self, temp_workflow_dir):
        """创建 WorkflowLoader"""
        from app.engine.workflow import WorkflowLoader
        return WorkflowLoader(workflows_dir=temp_workflow_dir)

    def _write_workflow_yaml(self, dir_path, name, content):
        filepath = os.path.join(dir_path, f"{name}.yaml")
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(content, f, allow_unicode=True)

    # ── 场景1: 客服投诉工作流加载 ────────────────────────────────

    def test_load_customer_service_workflow(self, loader, temp_workflow_dir):
        """加载客服投诉工作流定义"""
        self._write_workflow_yaml(temp_workflow_dir, "customer_service", {
            "name": "customer_service",
            "version": "1.0.0",
            "description": "客服投诉处理流程",
            "trigger_keywords": ["投诉", "退款", "质量问题"],
            "trigger_intent_types": ["complaint"],
            "min_complexity": 0,
            "max_complexity": 10,
            "default_agent": "cc",
            "fallback_agent": "amy",
            "steps": [
                {
                    "id": "1",
                    "name": "验证订单",
                    "type": "engine",
                    "action": "verify_order",
                    "params": {},
                    "critical": True,
                },
                {
                    "id": "2",
                    "name": "风险评估",
                    "type": "engine",
                    "action": "risk_assessment",
                    "params": {"threshold": "high"},
                    "critical": True,
                },
                {
                    "id": "3",
                    "name": "生成回复",
                    "type": "agent",
                    "action": "cc",
                    "params": {"context": "complaint"},
                    "critical": False,
                },
                {
                    "id": "4",
                    "name": "发送通知",
                    "type": "tool",
                    "action": "send_notification",
                    "params": {"channel": "email"},
                    "critical": False,
                },
            ],
        })

        loader._loaded = False
        workflows = loader.load_all()

        assert "customer_service" in workflows
        wf = workflows["customer_service"]
        assert wf.name == "customer_service"
        assert wf.version == "1.0.0"
        assert len(wf.steps) == 4
        assert wf.default_agent == "cc"
        assert wf.fallback_agent == "amy"

    # ── 场景2: 关键词匹配触发 Engine ─────────────────────────────

    def test_match_workflow_by_keyword(self, loader, temp_workflow_dir):
        """根据关键词匹配工作流"""
        self._write_workflow_yaml(temp_workflow_dir, "complaint_flow", {
            "name": "complaint_flow",
            "version": "1.0.0",
            "trigger_keywords": ["投诉", "退款", "差评"],
            "steps": [],
        })

        loader._loaded = False

        # 关键词匹配
        wf1 = loader.match_workflow("我要投诉产品质量问题")
        assert wf1 is not None
        assert wf1.name == "complaint_flow"

        wf2 = loader.match_workflow("申请退款怎么操作")
        assert wf2 is not None
        assert wf2.name == "complaint_flow"

        # 不匹配的情况
        wf3 = loader.match_workflow("帮我查一下销售数据")
        assert wf3 is None

    # ── 场景3: 复杂度过滤 ────────────────────────────────────────

    def test_complexity_filtering(self, loader, temp_workflow_dir):
        """根据复杂度过滤工作流"""
        self._write_workflow_yaml(temp_workflow_dir, "simple_flow", {
            "name": "simple_flow",
            "version": "1.0.0",
            "min_complexity": 0,
            "max_complexity": 4,
            "trigger_keywords": ["查询"],
            "steps": [],
        })
        self._write_workflow_yaml(temp_workflow_dir, "complex_flow", {
            "name": "complex_flow",
            "version": "1.0.0",
            "min_complexity": 6,
            "max_complexity": 10,
            "trigger_keywords": ["分析"],
            "steps": [],
        })

        loader._loaded = False

        # 低复杂度匹配简单工作流
        assert loader.match_workflow("查询", complexity=2) is not None
        # 低复杂度不匹配复杂工作流
        assert loader.match_workflow("分析", complexity=2) is None
        # 高复杂度匹配复杂工作流
        assert loader.match_workflow("分析", complexity=7) is not None

    # ── 场景4: Engine步骤定义完整性 ──────────────────────────────

    def test_step_structure_validation(self, loader, temp_workflow_dir):
        """工作流步骤应包含必要字段"""
        self._write_workflow_yaml(temp_workflow_dir, "test_flow", {
            "name": "test_flow",
            "version": "1.0.0",
            "steps": [
                {
                    "id": "1",
                    "name": "Step 1",
                    "type": "engine",
                    "action": "do_something",
                },
                {
                    "id": "2",
                    "name": "Step 2",
                    "type": "agent",
                    "action": "test_agent",
                },
                {
                    "id": "3",
                    "name": "Step 3",
                    "type": "condition",
                    "action": "check_status",
                    "on_success": "4",
                    "on_failure": "exit",
                },
            ],
        })

        loader._loaded = False
        workflows = loader.load_all()
        wf = workflows["test_flow"]

        # 验证步骤类型
        types = [s.type for s in wf.steps]
        assert "engine" in types
        assert "agent" in types
        assert "condition" in types

        # 验证 condition 步骤有跳转逻辑
        condition_step = [s for s in wf.steps if s.type == "condition"][0]
        assert condition_step.on_success == "4"
        assert condition_step.on_failure == "exit"

    # ── 场景5: Engine主导流程中 Agent 介入 ───────────────────────

    def test_engine_agent_handoff(self, loader, temp_workflow_dir):
        """Engine 主导流程中 Agent 在指定步骤介入"""
        self._write_workflow_yaml(temp_workflow_dir, "hybrid_flow", {
            "name": "hybrid_flow",
            "version": "1.0.0",
            "description": "混合流程：Engine处理结构化部分，Agent处理内容生成",
            "trigger_keywords": ["投诉"],
            "default_agent": "cc",
            "steps": [
                {"id": "1", "name": "数据验证", "type": "engine", "action": "validate", "critical": True},
                {"id": "2", "name": "内容生成", "type": "agent", "action": "cc", "critical": False},
                {"id": "3", "name": "结果记录", "type": "engine", "action": "log_result", "critical": True},
            ],
        })

        loader._loaded = False
        workflows = loader.load_all()
        wf = workflows["hybrid_flow"]

        assert wf is not None
        assert wf.default_agent == "cc"

        # 验证步骤顺序：Engine → Agent → Engine
        assert wf.steps[0].type == "engine"
        assert wf.steps[1].type == "agent"
        assert wf.steps[2].type == "engine"

    # ── 场景6: 工作流定义缺字段时的容错 ──────────────────────────

    def test_missing_optional_fields(self, loader, temp_workflow_dir):
        """缺少可选字段时应有默认值"""
        self._write_workflow_yaml(temp_workflow_dir, "minimal_flow", {
            "name": "minimal_flow",
            "version": "1.0.0",
            "steps": [],
        })

        loader._loaded = False
        workflows = loader.load_all()
        wf = workflows["minimal_flow"]

        assert wf.name == "minimal_flow"
        assert wf.trigger_keywords == []
        assert wf.trigger_intent_types == []
        assert wf.default_agent == ""
        assert wf.fallback_agent == ""