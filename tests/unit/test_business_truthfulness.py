"""Truthfulness gates for business agents without connected production data."""

import json

import pytest


def test_erp_tracking_is_fail_closed_without_a_logistics_backend():
    from app.agents.tools import track_shipment

    result = track_shipment.invoke({"tracking_no": "SF1234567890", "provider": "auto"})

    assert result["status"] == "unavailable"
    assert result["requires_logistics_backend"] is True
    assert result["tracking_details"] == []
    assert result["current_location"] == ""


@pytest.mark.asyncio
async def test_production_mcp_fallbacks_are_not_presented_as_real_data(monkeypatch):
    from app.mcp_servers.monitor_server import check_delivery_status
    from app.mcp_servers.report_server import (
        generate_performance_report,
        generate_strategy_suggestion,
    )

    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("ALLOW_PLATFORM_MOCK_FALLBACK", raising=False)
    import app.platforms

    monkeypatch.setattr(app.platforms, "get_platform_adapter", lambda *_args, **_kwargs: None)

    monitor = json.loads(check_delivery_status("ORD001"))
    report = json.loads(await generate_performance_report("unknown", "campaign-1"))
    strategy = json.loads(generate_strategy_suggestion("xiaohongshu", "beauty"))

    assert monitor["status"] == "error"
    assert report["status"] == "error"
    assert strategy["status"] == "error"
    assert all("mock fallback is disabled" in result["message"] for result in (monitor, report, strategy))
