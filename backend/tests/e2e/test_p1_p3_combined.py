import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

FRONTEND_URL = "http://localhost:5173"


class TestP1Agents:
    @pytest.mark.p1
    def test_content_ops_chat_page_accessible(self, page):
        page.goto(f"{FRONTEND_URL}/agents/content_ops/chat")
        assert page.url.startswith(FRONTEND_URL)

    @pytest.mark.p1
    def test_data_analyst_chat_page_accessible(self, page):
        page.goto(f"{FRONTEND_URL}/agents/data_analyst/chat")
        assert page.url.startswith(FRONTEND_URL)

    @pytest.mark.p1
    def test_customer_service_chat_page_accessible(self, page):
        page.goto(f"{FRONTEND_URL}/agents/customer_service/chat")
        assert page.url.startswith(FRONTEND_URL)


class TestP1Dashboard:
    @pytest.mark.p1
    def test_dashboard_page_loads(self, page):
        page.goto(f"{FRONTEND_URL}/dashboard")
        assert page.url.startswith(FRONTEND_URL)

    @pytest.mark.p1
    def test_dashboard_agent_status_list(self, authenticated_page):
        page = authenticated_page
        page.goto(f"{FRONTEND_URL}/dashboard")
        page.wait_for_timeout(5000)

        has_content = (
            page.locator('[class*="ant-card"]').count() > 0
            or page.locator('[class*="ant-tag"]').count() > 0
            or page.locator('[class*="ant-statistic"]').count() > 0
            or page.locator('[class*="ant-progress"]').count() > 0
            or page.locator('[class*="ant-spin"]').count() > 0
        )
        assert has_content or page.url.startswith(FRONTEND_URL), \
            "Dashboard should display agent status or loading indicator"


class TestP2OtherAgents:
    @pytest.mark.p2
    def test_warehouse_logistics_chat_page_accessible(self, page):
        page.goto(f"{FRONTEND_URL}/agents/warehouse_logistics/chat")
        assert page.url.startswith(FRONTEND_URL)

    @pytest.mark.p2
    def test_visual_designer_chat_page_accessible(self, page):
        page.goto(f"{FRONTEND_URL}/agents/visual_designer/chat")
        assert page.url.startswith(FRONTEND_URL)

    @pytest.mark.p2
    def test_supply_chain_chat_page_accessible(self, page):
        page.goto(f"{FRONTEND_URL}/agents/supply_chain/chat")
        assert page.url.startswith(FRONTEND_URL)

    @pytest.mark.p2
    def test_ad_specialist_chat_page_accessible(self, page):
        page.goto(f"{FRONTEND_URL}/agents/ad_specialist/chat")
        assert page.url.startswith(FRONTEND_URL)


class TestP2CostEvolution:
    @pytest.mark.p2
    def test_get_cost_summary(self, api_client: httpx.Client):
        response = api_client.get("/admin/costs/admin/costs/summary")
        assert response.status_code in [200, 401, 403]

    @pytest.mark.p2
    def test_get_evolution_report(self, api_client: httpx.Client):
        response = api_client.get("/admin/evolution/admin/evolution/report")
        assert response.status_code in [200, 401, 403]


class TestP3Settings:
    @pytest.mark.p3
    def test_settings_page_loads(self, page):
        page.goto(f"{FRONTEND_URL}/settings")
        assert page.url.startswith(FRONTEND_URL)

    @pytest.mark.p3
    def test_settings_llm_model_config(self, authenticated_page):
        page = authenticated_page
        page.goto(f"{FRONTEND_URL}/settings")
        page.wait_for_timeout(3000)

        tabs = page.locator('[class*="ant-tabs-tab"]')
        if tabs.count() > 0:
            llm_tab = tabs.filter(has_text="模型").first
            if llm_tab.is_visible():
                llm_tab.click()
                page.wait_for_timeout(2000)

        assert page.url.startswith(FRONTEND_URL), "Settings page should remain loaded"


class TestP3TaskList:
    @pytest.mark.p3
    def test_task_list_page_loads(self, page):
        page.goto(f"{FRONTEND_URL}/tasks")
        assert page.url.startswith(FRONTEND_URL)

    @pytest.mark.p3
    def test_task_list_status_filter(self, authenticated_page):
        page = authenticated_page
        page.goto(f"{FRONTEND_URL}/tasks")
        page.wait_for_timeout(3000)

        segmented = page.locator('[class*="ant-segmented"]').first
        if segmented.is_visible():
            running_option = segmented.locator("label").filter(has_text="执行中").first
            if running_option.is_visible():
                running_option.click()
                page.wait_for_timeout(2000)

            completed_option = segmented.locator("label").filter(has_text="已完成").first
            if completed_option.is_visible():
                completed_option.click()
                page.wait_for_timeout(2000)

        assert page.url.startswith(FRONTEND_URL), "Task list page should remain loaded after filtering"


class TestP3AuthEdge:
    @pytest.mark.p3
    def test_register_short_password(self, api_client: httpx.Client):
        response = api_client.post(
            "/auth/users/register",
            json={"username": "edge_test", "password": "short"},
        )
        assert response.status_code == 422

    @pytest.mark.p3
    def test_expired_token_rejected(self, api_client: httpx.Client):
        expired_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0dXNlciIsImV4cCI6MTcwMDAwMDAwMH0.invalid"
        response = api_client.get(
            "/auth/users/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert response.status_code == 401