"""
订阅管理 API 测试
测试订阅计划查询、雇佣/订阅操作、续约与解约 API
"""

import os
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.main import app


class TestSubscriptionAPI:
    """订阅管理 API 测试类"""

    @classmethod
    def setup_class(cls):
        """测试类初始化"""
        # 创建测试客户端
        cls.client = TestClient(app)

        # 测试用户数据
        cls.test_user = {
            "id": 1,
            "username": "testuser",
            "email": "test@example.com",
            "company_id": 1,
            "is_admin": False
        }

        # 测试订阅计划数据
        cls.test_plan = {
            "id": 1,
            "name": "品牌商务专员",
            "description": "专门负责品牌商务拓展的数字员工",
            "price_per_month": 299.0,
            "capabilities": "[\"达人搜索\", \"邀约话术\", \"数据分析\"]",
            "is_active": True
        }

    def setup_method(self):
        """每个测试方法前的设置"""
        # Mock 认证用户
        self.auth_headers = {"Authorization": "Bearer test_token"}

    def test_1_get_subscription_plans_success(self):
        """正常场景1：获取职位列表"""
        # Mock 数据库返回订阅计划列表
        with patch('app.database.db.get_subscription_plans') as mock_get_plans:
            mock_get_plans.return_value = [self.test_plan]

            # 调用 API
            response = self.client.get("/subscription/plans")

            # 验证响应
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["id"] == 1
            assert data[0]["name"] == "品牌商务专员"
            assert data[0]["price_per_month"] == 299.0
            assert data[0]["is_active"] == True

    def test_2_hire_employee_success(self):
        """正常场景2：雇佣一个品牌商务员工"""
        # Mock 数据库操作
        with patch('app.database.db.get_subscription_plan') as mock_get_plan, \
             patch('app.database.db.get_company_subscription_by_agent') as mock_get_subscription, \
             patch('app.database.db.create_company_subscription') as mock_create_subscription, \
             patch('app.database.db.update_company_subscription_status') as mock_update_status:

            # Mock 返回值
            mock_get_plan.return_value = self.test_plan
            mock_get_subscription.return_value = None  # 没有现有订阅
            mock_create_subscription.return_value = 123  # 新订阅ID

            # Mock 认证用户
            with patch('app.api.subscription.get_current_active_user') as mock_get_user:
                mock_get_user.return_value = self.test_user

                # 调用雇佣 API
                hire_request = {
                    "plan_id": 1,
                    "agent_name": "BrandBD"
                }
                response = self.client.post(
                    "/subscription/hire",
                    json=hire_request,
                    headers=self.auth_headers
                )

                # 验证响应
                assert response.status_code == 200
                data = response.json()
                assert data["subscription_id"] == 123
                assert data["company_id"] == 1
                assert data["plan_id"] == 1
                assert data["agent_name"] == "BrandBD"
                assert data["status"] == "active"

                # 验证数据库调用
                mock_create_subscription.assert_called_once()
                mock_update_status.assert_called_once_with(1, "subscribed")

    def test_3_hire_duplicate_employee_error(self):
        """异常场景1：重复雇佣同一岗位"""
        # Mock 数据库操作 - 模拟已存在订阅
        with patch('app.database.db.get_subscription_plan') as mock_get_plan, \
             patch('app.database.db.get_company_subscription_by_agent') as mock_get_subscription:

            # Mock 返回值
            mock_get_plan.return_value = self.test_plan
            mock_get_subscription.return_value = {
                "id": 456,
                "status": "active"
            }  # 已存在活跃订阅

            # Mock 认证用户
            with patch('app.api.subscription.get_current_active_user') as mock_get_user:
                mock_get_user.return_value = self.test_user

                # 调用雇佣 API
                hire_request = {
                    "plan_id": 1,
                    "agent_name": "BrandBD"
                }
                response = self.client.post(
                    "/subscription/hire",
                    json=hire_request,
                    headers=self.auth_headers
                )

                # 验证错误响应
                assert response.status_code == 400
                data = response.json()
                assert "already hired" in data["detail"].lower()

    def test_4_cancel_nonexistent_subscription_error(self):
        """异常场景2：解约不存在的订阅"""
        # Mock 数据库操作
        with patch('app.database.db.get_company_subscription') as mock_get_subscription:
            mock_get_subscription.return_value = None  # 订阅不存在

            # Mock 认证用户
            with patch('app.api.subscription.get_current_active_user') as mock_get_user:
                mock_get_user.return_value = self.test_user

                # 调用解约 API
                cancel_request = {
                    "subscription_id": 999  # 不存在的订阅ID
                }
                response = self.client.post(
                    "/subscription/cancel",
                    json=cancel_request,
                    headers=self.auth_headers
                )

                # 验证错误响应
                assert response.status_code == 404
                data = response.json()
                assert "not found" in data["detail"].lower()

    def test_5_hire_without_auth_error(self):
        """异常场景3：未登录调用 hire 返回 401"""
        # 不提供认证头
        hire_request = {
            "plan_id": 1,
            "agent_name": "BrandBD"
        }

        # 调用雇佣 API（无认证）
        response = self.client.post("/subscription/hire", json=hire_request)

        # 验证未认证错误
        assert response.status_code == 401

    def test_6_renew_subscription_success(self):
        """正常场景3：续约员工"""
        # Mock 数据库操作
        with patch('app.database.db.get_company_subscription') as mock_get_subscription, \
             patch('app.database.db.extend_subscription_end_date') as mock_extend_date, \
             patch('app.database.db.update_subscription_auto_renew') as mock_update_auto_renew:

            # Mock 返回值
            mock_get_subscription.return_value = {
                "id": 123,
                "company_id": 1,
                "status": "active"
            }

            # Mock 认证用户
            with patch('app.api.subscription.get_current_active_user') as mock_get_user:
                mock_get_user.return_value = self.test_user

                # 调用续约 API
                renew_request = {
                    "subscription_id": 123,
                    "months": 3
                }
                response = self.client.post(
                    "/subscription/renew",
                    json=renew_request,
                    headers=self.auth_headers
                )

                # 验证响应
                assert response.status_code == 200
                data = response.json()
                assert "renewed for 3 months" in data["message"]

                # 验证数据库调用
                mock_extend_date.assert_called_once_with(123, 3)
                mock_update_auto_renew.assert_called_once_with(123, True)

    def test_7_cancel_subscription_success(self):
        """正常场景4：解约员工"""
        # Mock 数据库操作
        with patch('app.database.db.get_company_subscription') as mock_get_subscription, \
             patch('app.database.db.update_subscription_status') as mock_update_status, \
             patch('app.database.db.get_company_active_subscriptions') as mock_get_active_subscriptions, \
             patch('app.database.db.update_company_subscription_status') as mock_update_company_status:

            # Mock 返回值
            mock_get_subscription.return_value = {
                "id": 123,
                "company_id": 1,
                "status": "active"
            }
            mock_get_active_subscriptions.return_value = []  # 没有其他活跃订阅

            # Mock 认证用户
            with patch('app.api.subscription.get_current_active_user') as mock_get_user:
                mock_get_user.return_value = self.test_user

                # 调用解约 API
                cancel_request = {
                    "subscription_id": 123
                }
                response = self.client.post(
                    "/subscription/cancel",
                    json=cancel_request,
                    headers=self.auth_headers
                )

                # 验证响应
                assert response.status_code == 200
                data = response.json()
                assert "cancelled successfully" in data["message"]

                # 验证数据库调用
                mock_update_status.assert_called_once_with(123, "cancelled")
                mock_update_company_status.assert_called_once_with(1, "inactive")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
