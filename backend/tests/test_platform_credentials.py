"""
平台凭证管理测试
测试平台账号凭证管理功能
"""

import json
import os
import sys
from pathlib import Path

import pytest

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from app.database import db
from app.main import app
from app.platforms.douyin_star import DouyinStarAdapter


class TestPlatformCredentials:
    """平台凭证管理测试类"""

    @classmethod
    def setup_class(cls):
        """测试类初始化"""
        cls.client = TestClient(app)
        cls.test_company_id = 9999
        cls.no_cred_company_id = 8888

    def setup_method(self):
        """每个测试方法前的设置"""
        # 创建测试公司
        test_company = type(
            "TestCompany",
            (),
            {
                "id": self.test_company_id,
                "name": "Test Company",
                "brand_name": "Test Brand",
                "category": "beauty",
                "platforms_json": "douyin_star,xiaohongshu",
                "platform_credentials": None,
                "created_at": "2023-01-01T00:00:00Z",
            },
        )()

        # 创建无凭证测试公司
        no_cred_company = type(
            "TestCompany",
            (),
            {
                "id": self.no_cred_company_id,
                "name": "No Cred Company",
                "brand_name": "No Cred Brand",
                "category": "fashion",
                "platforms_json": "douyin_star",
                "platform_credentials": None,
                "created_at": "2023-01-01T00:00:00Z",
            },
        )()

        # Mock 数据库方法
        db.get_company = lambda company_id: {
            self.test_company_id: test_company,
            self.no_cred_company_id: no_cred_company,
        }.get(company_id)

        db.update_company_platform_credentials = lambda company_id, credentials: True

    def test_1_company_specific_credentials_loading(self):
        """正常场景 1：为测试公司绑定凭证后，适配器读取到正确凭证"""
        # 设置公司专属凭证
        test_credentials = {
            "douyin_star": {"api_key": "test_company_key", "api_secret": "test_company_secret"}
        }

        # Mock 公司有凭证
        test_company_with_creds = type(
            "TestCompany",
            (),
            {
                "id": self.test_company_id,
                "name": "Test Company",
                "brand_name": "Test Brand",
                "category": "beauty",
                "platforms_json": "douyin_star,xiaohongshu",
                "platform_credentials": json.dumps(test_credentials),
                "created_at": "2023-01-01T00:00:00Z",
            },
        )()

        db.get_company = lambda company_id: (
            test_company_with_creds if company_id == self.test_company_id else None
        )

        # 创建适配器并验证凭证
        adapter = DouyinStarAdapter(company_id=self.test_company_id)

        assert adapter.api_key == "test_company_key", (
            f"Expected test_company_key, got {adapter.api_key}"
        )
        assert adapter.api_secret == "test_company_secret", (
            f"Expected test_company_secret, got {adapter.api_secret}"
        )

    def test_2_fallback_to_environment_variables(self):
        """正常场景 2：未绑定凭证的公司，适配器降级到环境变量"""
        # 设置环境变量
        original_api_key = os.environ.get("DOUYIN_STAR_API_KEY")
        original_api_secret = os.environ.get("DOUYIN_STAR_API_SECRET")

        try:
            os.environ["DOUYIN_STAR_API_KEY"] = "env_test_key"
            os.environ["DOUYIN_STAR_API_SECRET"] = "env_test_secret"

            # 创建适配器（公司无凭证）
            adapter = DouyinStarAdapter(company_id=self.no_cred_company_id)

            # 验证降级到环境变量
            assert adapter.api_key == "env_test_key", (
                f"Expected env_test_key, got {adapter.api_key}"
            )
            assert adapter.api_secret == "env_test_secret", (
                f"Expected env_test_secret, got {adapter.api_secret}"
            )

        finally:
            # 恢复原始环境变量
            if original_api_key:
                os.environ["DOUYIN_STAR_API_KEY"] = original_api_key
            elif "DOUYIN_STAR_API_KEY" in os.environ:
                del os.environ["DOUYIN_STAR_API_KEY"]

            if original_api_secret:
                os.environ["DOUYIN_STAR_API_SECRET"] = original_api_secret
            elif "DOUYIN_STAR_API_SECRET" in os.environ:
                del os.environ["DOUYIN_STAR_API_SECRET"]

    def test_3_bind_credentials_api_permission_denied(self):
        """异常场景 1：绑定凭证 API 拒绝无权限用户"""
        from types import SimpleNamespace

        from app.auth import get_current_active_user

        # Mock 无权限用户
        mock_user = SimpleNamespace(
            id=2,
            username="normal_user",
            company_id=1234,  # 不是目标公司
            is_admin=False,
        )

        # 使用 dependency_overrides 覆盖认证依赖
        app.dependency_overrides[get_current_active_user] = lambda: mock_user

        try:
            # 尝试为其他公司绑定凭证（使用 T4.1 升级后的动态字段格式）
            credentials_data = {
                "platform": "douyin_star",
                "credentials": {
                    "app_id": "test_app_id",
                    "app_secret": "test_app_secret",
                    "access_token": "test_access_token",
                    "advertiser_id": "test_advertiser_id",
                },
            }

            response = self.client.post(
                f"/api/admin/companies/{self.test_company_id}/credentials", json=credentials_data
            )

            # 验证权限被拒绝
            assert response.status_code == 403, f"Expected 403, got {response.status_code}"

        finally:
            # 恢复原始认证依赖
            app.dependency_overrides.clear()

    def test_4_unbind_nonexistent_platform(self):
        """异常场景 2：解绑不存在的平台时不崩溃"""
        from types import SimpleNamespace

        from app.auth import get_current_active_user

        # Mock 管理员用户
        mock_admin = SimpleNamespace(
            id=1, username="admin", company_id=self.test_company_id, is_admin=True
        )

        # 使用 dependency_overrides 覆盖认证依赖
        app.dependency_overrides[get_current_active_user] = lambda: mock_admin

        try:
            # 尝试解绑不存在的平台
            response = self.client.delete(
                f"/api/admin/companies/{self.test_company_id}/credentials?platform=nonexistent_platform"
            )

            # 验证不崩溃，返回成功或明确提示
            assert response.status_code in [200, 404], (
                f"Expected 200 or 404, got {response.status_code}"
            )

            if response.status_code == 200:
                result = response.json()
                assert "message" in result, "Response should contain message"

        finally:
            # 恢复原始认证依赖
            app.dependency_overrides.clear()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
