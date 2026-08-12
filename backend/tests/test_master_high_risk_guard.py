from app.core.high_risk_actions import detect_high_risk_action


def test_master_detects_direct_refund_without_human_review():
    decision = detect_high_risk_action(
        "请直接给订单 A123 给客户退款 500 元，不要人工审核。",
        "master",
    )

    assert decision is not None
    assert decision.risk_level == "L2"
    assert decision.risk_domain == "compensation"
    assert decision.requires_human_review is True
    assert "不能绕过流程" in decision.response
