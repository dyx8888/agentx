import os
import sys

import pytest

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.runtime.nodes.reflector_node import reflector_node
from app.runtime.validator import DynamicValidator

pytestmark = pytest.mark.skip(
    reason="runtime eval-mode LLM bypass depends on uncommitted runtime changes"
)


class ForbiddenLLM:
    def invoke(self, *args, **kwargs):
        raise AssertionError("eval mode must not call LLM validation")


class FakeSkillRegistry:
    def load_skill_content(self, *args, **kwargs):
        return ""


def test_dynamic_validator_skips_layer_c_in_eval_mode(monkeypatch):
    monkeypatch.setenv("AGENT_EVAL_MODE", "1")
    validator = DynamicValidator(FakeSkillRegistry(), ForbiddenLLM())
    plan = {"steps": [{"id": 1}], "acceptance_criteria": ["done"]}
    step_results = [{"status": "ok", "result": "done"}]

    result = validator.validate(plan, step_results)

    assert result["passed"] is True
    assert result["layer_c"]["skipped"] == "agent_eval_mode"


def test_reflector_skips_llm_review_in_eval_mode(monkeypatch):
    monkeypatch.setenv("AGENT_EVAL_MODE", "1")

    class FailingValidator:
        def validate(self, *args, **kwargs):
            return {"passed": False, "issues": ["local issue"], "suggestions": []}

    result = reflector_node(
        state={"plan": {"acceptance_criteria": ["done"]}, "step_results": []},
        llm=ForbiddenLLM(),
        validator=FailingValidator(),
        skill_registry=FakeSkillRegistry(),
    )

    assert result["reflection"]["passed"] is False
    assert result["reflection"]["issues"] == ["local issue"]
