from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_admin_mock_fallback_disabled_in_production(monkeypatch):
    from app.api.admin import admin as admin_api

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setattr(admin_api, "_get_real_companies", lambda: [])
    monkeypatch.setattr(admin_api, "_get_real_users", lambda company_id=None: [])

    current_user = SimpleNamespace(is_admin=True)

    companies = await admin_api.admin_list_companies(current_user=current_user)
    assert companies.companies == []
    assert companies.total == 0

    users = await admin_api.admin_list_users(company_id=None, current_user=current_user)
    assert users.users == []
    assert users.total == 0

    subscriptions = await admin_api.admin_list_subscriptions(current_user=current_user)
    assert subscriptions.subscriptions == []
    assert subscriptions.total == 0

    usage = await admin_api.admin_get_usage(current_user=current_user)
    assert usage.usages == []
    assert usage.total_tokens_all == 0
    assert usage.total_cost_all == 0.0


@pytest.mark.asyncio
async def test_admin_mock_fallback_allowed_outside_production(monkeypatch):
    from app.api.admin import admin as admin_api

    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setattr(admin_api, "_get_real_companies", lambda: [])
    monkeypatch.setattr(admin_api, "_get_real_users", lambda company_id=None: [])

    current_user = SimpleNamespace(is_admin=True)

    companies = await admin_api.admin_list_companies(current_user=current_user)
    assert companies.total > 0

    users = await admin_api.admin_list_users(company_id=None, current_user=current_user)
    assert users.total > 0
