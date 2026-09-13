"""Contract tests for the current ``/api/subscription`` surface."""

import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.auth import get_current_active_user
from app.main import app


class TestSubscriptionAPI:
    @classmethod
    def setup_class(cls):
        cls.client = TestClient(app)
        cls.test_user = SimpleNamespace(
            id=1,
            username="testuser",
            email="test@example.com",
            company_id=1,
            is_admin=False,
            disabled=False,
            is_active=True,
        )
        cls.test_plan = {
            "id": 1,
            "name": "品牌商务专员",
            "description": "专门负责品牌商务拓展的数字员工",
            "price_per_month": 299.0,
            "capabilities": "[\"达人搜索\", \"邀约话术\", \"数据分析\"]",
            "is_active": True,
        }

    @classmethod
    def teardown_class(cls):
        app.dependency_overrides.pop(get_current_active_user, None)
        cls.client.close()

    @pytest.fixture(autouse=True)
    def authenticated_user(self):
        app.dependency_overrides[get_current_active_user] = lambda: self.test_user
        yield
        app.dependency_overrides.pop(get_current_active_user, None)

    def _without_auth(self, method, path, **kwargs):
        override = app.dependency_overrides.pop(get_current_active_user, None)
        try:
            return getattr(self.client, method)(path, **kwargs)
        finally:
            if override is not None:
                app.dependency_overrides[get_current_active_user] = override

    def test_1_get_subscription_plans_success(self):
        with patch("app.database.db.get_subscription_plans", return_value=[self.test_plan]):
            response = self.client.get("/api/subscription/plans")

        assert response.status_code == 200
        data = response.json()
        assert data == [
            {
                "id": 1,
                "name": "品牌商务专员",
                "description": "专门负责品牌商务拓展的数字员工",
                "price_per_month": 299.0,
                "capabilities": "[\"达人搜索\", \"邀约话术\", \"数据分析\"]",
                "is_active": True,
            }
        ]

    def test_2_hire_employee_success(self):
        with patch("app.database.db.get_subscription_plan", return_value=self.test_plan), \
            patch("app.database.db.get_company_subscription_by_agent", return_value=None), \
            patch("app.database.db.create_company_subscription", return_value=123) as create, \
            patch("app.database.db.update_company_subscription_status") as update:
            response = self.client.post(
                "/api/subscription/hire",
                json={"plan_id": 1, "agent_name": "BrandBD"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["subscription_id"] == 123
        assert data["company_id"] == 1
        assert data["plan_id"] == 1
        assert data["agent_name"] == "BrandBD"
        assert data["status"] == "active"
        create.assert_called_once()
        update.assert_called_once_with(1, "subscribed")

    def test_3_hire_duplicate_employee_error(self):
        with patch("app.database.db.get_subscription_plan", return_value=self.test_plan), \
            patch(
                "app.database.db.get_company_subscription_by_agent",
                return_value={"id": 456, "status": "active"},
            ):
            response = self.client.post(
                "/api/subscription/hire",
                json={"plan_id": 1, "agent_name": "BrandBD"},
            )

        assert response.status_code == 400
        assert "already hired" in response.json()["message"].lower()

    def test_4_cancel_nonexistent_subscription_error(self):
        with patch("app.database.db.get_company_subscription", return_value=None):
            response = self.client.post(
                "/api/subscription/cancel", json={"subscription_id": 999}
            )

        assert response.status_code == 404
        assert "not found" in response.json()["message"].lower()

    def test_5_hire_without_auth_error(self):
        response = self._without_auth(
            "post",
            "/api/subscription/hire",
            json={"plan_id": 1, "agent_name": "BrandBD"},
        )
        assert response.status_code == 401

    def test_6_renew_subscription_success(self):
        with patch(
            "app.database.db.get_company_subscription",
            return_value={"id": 123, "company_id": 1, "status": "active"},
        ), patch("app.database.db.extend_subscription_end_date") as extend, patch(
            "app.database.db.update_subscription_auto_renew"
        ) as update:
            response = self.client.post(
                "/api/subscription/renew",
                json={"subscription_id": 123, "months": 3},
            )

        assert response.status_code == 200
        assert "renewed for 3 months" in response.json()["message"]
        extend.assert_called_once_with(123, 3)
        update.assert_called_once_with(123, True)

    def test_7_cancel_subscription_success(self):
        with patch(
            "app.database.db.get_company_subscription",
            return_value={"id": 123, "company_id": 1, "status": "active"},
        ), patch("app.database.db.update_subscription_status") as update, patch(
            "app.database.db.get_company_active_subscriptions", return_value=[]
        ), patch("app.database.db.update_company_subscription_status") as company_update:
            response = self.client.post(
                "/api/subscription/cancel", json={"subscription_id": 123}
            )

        assert response.status_code == 200
        assert "cancelled successfully" in response.json()["message"]
        update.assert_called_once_with(123, "cancelled")
        company_update.assert_called_once_with(1, "inactive")
