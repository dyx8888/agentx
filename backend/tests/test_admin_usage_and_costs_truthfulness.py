from types import SimpleNamespace

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_admin_usage_does_not_generate_random_mock_usage(monkeypatch):
    import app.api.admin.admin as admin_api
    import app.database as database_mod

    class EmptyDB:
        def get_all_companies(self):
            return []

        def get_agents_by_company(self, _company_id):
            raise AssertionError("no agents should be requested without real companies")

    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setattr(database_mod, "db", EmptyDB())

    result = await admin_api.admin_get_usage(current_user=SimpleNamespace(is_admin=True))

    assert result.usages == []
    assert result.total_tokens_all == 0
    assert result.total_cost_all == 0.0


@pytest.mark.asyncio
async def test_admin_usage_reads_cost_tracker_summary(monkeypatch):
    import app.api.admin.admin as admin_api
    import app.database as database_mod
    import app.tracking.cost_tracker as cost_tracker_mod

    class FakeDB:
        def get_all_companies(self):
            return [
                SimpleNamespace(id=1, name="Alpha"),
                SimpleNamespace(id=2, name="Beta"),
            ]

        def get_agents_by_company(self, company_id):
            if company_id == 1:
                return [
                    SimpleNamespace(id=11, name="brand_bd", display_name="品牌商务"),
                    SimpleNamespace(id=12, name="ad_delivery", display_name="智能投流"),
                ]
            return [SimpleNamespace(id=21, name="customer_service", display_name="客服专员")]

    seen = {}

    def fake_summary(agent_ids, days):
        seen["agent_ids"] = agent_ids
        seen["days"] = days
        return {
            11: {"total_tokens": 1234, "total_cost": 1.234, "total_requests": 2},
            21: {"total_tokens": 500, "total_cost": 0.5, "total_requests": 1},
        }

    monkeypatch.setattr(database_mod, "db", FakeDB())
    monkeypatch.setattr(
        cost_tracker_mod.CostTracker,
        "get_cost_summary_by_agents",
        staticmethod(fake_summary),
    )

    result = await admin_api.admin_get_usage(days=7, current_user=SimpleNamespace(is_admin=True))

    assert seen == {"agent_ids": [11, 12, 21], "days": 7}
    assert [(item.company_id, item.agent_key, item.total_tokens) for item in result.usages] == [
        (1, "brand_bd", 1234),
        (2, "customer_service", 500),
    ]
    assert result.total_tokens_all == 1734
    assert result.total_cost_all == 1.73


@pytest.mark.asyncio
async def test_get_cost_summary_exception_returns_generic_500(monkeypatch):
    import app.api.admin.costs as costs_api

    def broken_total_cost(_days):
        raise RuntimeError("database path should not leak")

    monkeypatch.setattr(
        costs_api.CostTracker,
        "get_total_cost",
        staticmethod(broken_total_cost),
    )

    with pytest.raises(HTTPException) as exc_info:
        await costs_api.get_cost_summary(current_user=SimpleNamespace(is_admin=True))

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "内部服务器错误"
    assert "database path should not leak" not in str(exc_info.value.detail)
