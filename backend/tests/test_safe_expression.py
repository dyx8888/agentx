import pytest

from app.core.safe_expression import SafeExpressionError, safe_eval_bool


def test_safe_eval_supports_workflow_context_get():
    context = {"auto_approve": True, "complaint_type": "refund"}

    assert safe_eval_bool("context.get('auto_approve', False)", {"context": context}) is True
    assert (
        safe_eval_bool(
            "context.get('complaint_type') == 'refund'",
            {"context": context},
        )
        is True
    )


def test_safe_eval_supports_stop_loss_numeric_rules():
    variables = {
        "cpa": 180,
        "target_cpa": 100,
        "roi": 0.8,
        "breakeven_roi": 1.0,
        "running_hours": 4,
    }

    assert safe_eval_bool("cpa > target_cpa * 1.5 and running_hours >= 2", variables) is True
    assert safe_eval_bool("roi < breakeven_roi and running_hours >= 4", variables) is True


def test_safe_eval_rejects_code_execution():
    with pytest.raises(SafeExpressionError):
        safe_eval_bool("__import__('os').system('echo unsafe')", {})


def test_safe_eval_rejects_unknown_variables():
    with pytest.raises(SafeExpressionError):
        safe_eval_bool("missing_value == 1", {})
