"""
16.1.7 WorkflowLoader 单元测试
正常YAML/缺少字段/格式错误
"""
import os
import tempfile

import pytest


class TestWorkflowLoader:
    """工作流加载器单元测试"""

    @pytest.fixture
    def loader(self, tmp_path):
        from app.engine.workflow import WorkflowLoader
        workflows_dir = tmp_path / "workflows"
        workflows_dir.mkdir()
        return WorkflowLoader(workflows_dir=str(workflows_dir))

    def _write_workflow(self, tmp_path, name, content):
        import yaml
        path = tmp_path / "workflows" / f"{name}.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(content, f, allow_unicode=True)
        return path

    def test_load_valid_yaml(self, loader, tmp_path):
        """加载正常YAML"""
        self._write_workflow(tmp_path, "test_flow", {
            "name": "test_flow",
            "version": "1.0.0",
            "description": "Test workflow",
            "steps": [
                {"id": "1", "name": "Step 1", "type": "tool", "action": "test_tool"},
                {"id": "2", "name": "Step 2", "type": "agent", "action": "test_agent"},
            ],
        })
        loader._loaded = False
        workflows = loader.load_all()
        assert "test_flow" in workflows
        wf = workflows["test_flow"]
        assert len(wf.steps) == 2
        assert wf.steps[0].id == "1"

    def test_load_missing_fields(self, loader, tmp_path):
        """加载缺少字段的YAML（使用默认值）"""
        self._write_workflow(tmp_path, "minimal_flow", {
            "name": "minimal_flow",
            "version": "1.0.0",
            "steps": [
                {"id": "1", "name": "Only Step", "type": "tool"},
            ],
        })
        loader._loaded = False
        workflows = loader.load_all()
        wf = workflows["minimal_flow"]
        assert wf.description == ""
        assert wf.trigger_keywords == []

    def test_load_empty_yaml(self, loader, tmp_path):
        """加载空YAML"""
        self._write_workflow(tmp_path, "empty_flow", {})
        loader._loaded = False
        workflows = loader.load_all()
        assert "empty_flow" in workflows
        wf = workflows["empty_flow"]
        assert wf.steps == []

    def test_match_by_keyword(self, loader, tmp_path):
        """关键词匹配"""
        self._write_workflow(tmp_path, "complaint_flow", {
            "name": "complaint_flow",
            "version": "1.0.0",
            "trigger_keywords": ["投诉", "退款"],
            "steps": [],
        })
        loader._loaded = False
        wf = loader.match_workflow("我要投诉产品质量问题")
        assert wf is not None
        assert wf.name == "complaint_flow"

    def test_match_by_intent(self, loader, tmp_path):
        """意图类型匹配"""
        self._write_workflow(tmp_path, "report_flow", {
            "name": "report_flow",
            "version": "1.0.0",
            "trigger_intent_types": ["generate"],
            "steps": [],
        })
        loader._loaded = False
        wf = loader.match_workflow("生成报告", intent_type="generate")
        assert wf is not None
        assert wf.name == "report_flow"

    def test_no_match(self, loader, tmp_path):
        """无匹配"""
        self._write_workflow(tmp_path, "specific_flow", {
            "name": "specific_flow",
            "version": "1.0.0",
            "trigger_keywords": ["专业词汇ABC"],
            "steps": [],
        })
        loader._loaded = False
        wf = loader.match_workflow("普通的日常对话")
        assert wf is None

    def test_complexity_filter(self, loader, tmp_path):
        """复杂度过滤"""
        self._write_workflow(tmp_path, "simple_flow", {
            "name": "simple_flow",
            "version": "1.0.0",
            "min_complexity": 0,
            "max_complexity": 4,
            "trigger_keywords": ["查询"],
            "steps": [],
        })
        self._write_workflow(tmp_path, "complex_flow", {
            "name": "complex_flow",
            "version": "1.0.0",
            "min_complexity": 6,
            "max_complexity": 10,
            "trigger_keywords": ["分析"],
            "steps": [],
        })
        loader._loaded = False
        assert loader.match_workflow("查询", complexity=2) is not None
        assert loader.match_workflow("分析", complexity=2) is None
        assert loader.match_workflow("分析", complexity=7) is not None