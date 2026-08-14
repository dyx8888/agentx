import asyncio


def test_ad_delivery_stop_loss_actions_require_human_review():
    from app.engines.ad_delivery_engine import AdDeliveryEngine, CampaignMetrics

    engine = AdDeliveryEngine()
    metrics = CampaignMetrics(
        campaign_id="cmp-1",
        impressions=10000,
        clicks=50,
        conversions=1,
        spend=950,
        revenue=200,
        cpa=200,
        roi=0.2,
        ctr=0.005,
        lasting_hours=5,
    )

    actions = engine._analyze_stop_loss(
        campaign_id="cmp-1",
        m=metrics,
        target_cpa=100,
        target_roi=1.5,
        daily_budget=1000,
        company_id=239,
    )
    risky_actions = [a for a in actions if a["action"] in {"reduce_budget", "pause_campaign"}]

    assert risky_actions
    assert all(action["auto_execute"] is False for action in risky_actions)
    assert all(action["require_review"] is True for action in risky_actions)


def test_ad_delivery_execute_stop_loss_only_creates_review_alert(monkeypatch):
    from app.communication import collaboration as collaboration_mod
    from app.engines.ad_delivery_engine import AdDeliveryEngine, CampaignMetrics, CampaignStatus

    alerts = []

    class FakeCollaborationEngine:
        async def create_alert(self, **kwargs):
            alerts.append(kwargs)
            return "alert-1"

    monkeypatch.setattr(collaboration_mod, "collaboration_engine", FakeCollaborationEngine())

    engine = AdDeliveryEngine()
    engine.register_campaign(
        "cmp-1",
        CampaignMetrics(
            campaign_id="cmp-1",
            impressions=10000,
            clicks=100,
            conversions=2,
            spend=900,
            revenue=100,
            cpa=150,
            roi=0.1,
            ctr=0.01,
            lasting_hours=5,
        ),
    )

    result = asyncio.run(engine.execute_stop_loss_action("cmp-1", "pause_campaign", 239))

    assert result["status"] == CampaignStatus.PENDING_REVIEW.value
    assert result["requires_human_review"] is True
    assert "cmp-1" in engine._active_campaigns
    assert alerts[0]["title"] == "广告暂停待审核"
    assert "自动" not in alerts[0]["message"]


def test_stop_loss_engine_rules_do_not_auto_execute_budget_side_effects():
    from app.engines.stop_loss import CampaignMetrics, StopLossAction, StopLossEngine

    engine = StopLossEngine()
    metrics = CampaignMetrics(
        campaign_id="cmp-1",
        campaign_name="测试计划",
        platform="douyin",
        daily_budget=1000,
        current_spend=950,
        cpa=350,
        target_cpa=100,
        roi=0.2,
        breakeven_roi=1.0,
        ctr=0.005,
        industry_avg_ctr=0.02,
        impressions=10000,
        clicks=50,
        conversions=0,
        running_hours=5,
    )

    triggers = engine.evaluate(metrics)
    budget_side_effects = [
        trigger
        for trigger in triggers
        if trigger.action in {StopLossAction.REDUCE_BUDGET_50, StopLossAction.PAUSE_CAMPAIGN}
    ]

    assert budget_side_effects
    assert all(trigger.auto_executed is False for trigger in budget_side_effects)
    assert all("自动执行" not in trigger.recommended_action for trigger in budget_side_effects)

