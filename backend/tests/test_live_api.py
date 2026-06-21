"""
真实 API 对接测试
测试小红书/抖音真实 API 对接功能
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.mcp_servers.kol_search_server import search_kols
from app.platforms.douyin_star import DouyinStarAdapter


class TestLiveAPI:
    """真实 API 对接测试类"""

    @classmethod
    def setup_class(cls):
        """测试类初始化"""
        cls.test_category = "beauty"
        cls.test_count = 3

    def test_1_mock_data_fallback_available(self):
        """正常场景 1：Mock 数据降级可用"""
        # 不设置真实 API 凭证
        original_api_key = os.environ.get('DOUYIN_STAR_API_KEY')
        original_api_secret = os.environ.get('DOUYIN_STAR_API_SECRET')

        try:
            # 清除环境变量
            if 'DOUYIN_STAR_API_KEY' in os.environ:
                del os.environ['DOUYIN_STAR_API_KEY']
            if 'DOUYIN_STAR_API_SECRET' in os.environ:
                del os.environ['DOUYIN_STAR_API_SECRET']

            # 调用 search_kols，应该返回 Mock 数据
            result = search_kols(self.test_category, self.test_count)

            # 验证返回 Mock 数据
            assert isinstance(result, list), f"Expected list, got {type(result)}"
            assert len(result) == self.test_count, f"Expected {self.test_count} items, got {len(result)}"

            # 验证 Mock 数据格式
            if result:
                kol = result[0]
                assert 'name' in kol, "Mock KOL should have 'name' field"
                assert 'platform' in kol, "Mock KOL should have 'platform' field"
                assert 'followers' in kol, "Mock KOL should have 'followers' field"

        finally:
            # 恢复原始环境变量
            if original_api_key:
                os.environ['DOUYIN_STAR_API_KEY'] = original_api_key
            if original_api_secret:
                os.environ['DOUYIN_STAR_API_SECRET'] = original_api_secret

    def test_2_adapter_with_credentials_no_crash(self):
        """正常场景 2：带凭证适配器不崩溃"""
        # 设置测试环境变量
        original_api_key = os.environ.get('DOUYIN_STAR_API_KEY')
        original_api_secret = os.environ.get('DOUYIN_STAR_API_SECRET')

        try:
            os.environ['DOUYIN_STAR_API_KEY'] = 'test_key_12345'
            os.environ['DOUYIN_STAR_API_SECRET'] = 'test_secret_67890'

            # 创建适配器并调用搜索
            adapter = DouyinStarAdapter(company_id=None)

            # 验证适配器初始化成功
            assert adapter.api_key == 'test_key_12345', "API key should be set"
            assert adapter.api_secret == 'test_secret_67890', "API secret should be set"

            # 调用搜索方法（可能会失败但不应该崩溃）
            result = adapter.search_creators(self.test_category, self.test_count)

            # 验证返回结果（可能是真实数据或 Mock 数据）
            assert isinstance(result, list), f"Expected list, got {type(result)}"
            # API 可能失败，所以应该返回 Mock 数据
            assert len(result) <= self.test_count, f"Expected at most {self.test_count} items, got {len(result)}"

        finally:
            # 恢复原始环境变量
            if original_api_key:
                os.environ['DOUYIN_STAR_API_KEY'] = original_api_key
            elif 'DOUYIN_STAR_API_KEY' in os.environ:
                del os.environ['DOUYIN_STAR_API_KEY']

            if original_api_secret:
                os.environ['DOUYIN_STAR_API_SECRET'] = original_api_secret
            elif 'DOUYIN_STAR_API_SECRET' in os.environ:
                del os.environ['DOUYIN_STAR_API_SECRET']

    @patch('requests.get')
    def test_3_invalid_credentials_graceful_fallback(self, mock_get):
        """异常场景 1：无效 API 凭证时优雅降级"""
        # 设置无效的 API Key
        original_api_key = os.environ.get('DOUYIN_STAR_API_KEY')
        original_api_secret = os.environ.get('DOUYIN_STAR_API_SECRET')

        try:
            os.environ['DOUYIN_STAR_API_KEY'] = 'invalid_key'
            os.environ['DOUYIN_STAR_API_SECRET'] = 'invalid_secret'

            # 模拟 API 返回错误
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.text = 'Unauthorized'
            mock_get.return_value = mock_response

            # 调用搜索
            adapter = DouyinStarAdapter(company_id=None)
            result = adapter.search_creators(self.test_category, self.test_count)

            # 验证返回 Mock 数据（降级）
            assert isinstance(result, list), f"Expected list, got {type(result)}"
            assert len(result) == self.test_count, f"Expected {self.test_count} items, got {len(result)}"

            # 验证 API 被调用
            mock_get.assert_called_once()

        finally:
            # 恢复原始环境变量
            if original_api_key:
                os.environ['DOUYIN_STAR_API_KEY'] = original_api_key
            elif 'DOUYIN_STAR_API_KEY' in os.environ:
                del os.environ['DOUYIN_STAR_API_KEY']

            if original_api_secret:
                os.environ['DOUYIN_STAR_API_SECRET'] = original_api_secret
            elif 'DOUYIN_STAR_API_SECRET' in os.environ:
                del os.environ['DOUYIN_STAR_API_SECRET']

    @patch('requests.get')
    def test_4_network_timeout_not_blocking(self, mock_get):
        """异常场景 2：网络超时时不阻塞"""
        # 设置测试环境变量
        original_api_key = os.environ.get('DOUYIN_STAR_API_KEY')
        original_api_secret = os.environ.get('DOUYIN_STAR_API_SECRET')

        try:
            os.environ['DOUYIN_STAR_API_KEY'] = 'test_key_12345'
            os.environ['DOUYIN_STAR_API_SECRET'] = 'test_secret_67890'

            # 模拟网络超时
            import requests
            mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

            # 创建适配器并设置极短的超时时间
            adapter = DouyinStarAdapter(company_id=None)
            adapter.timeout = 0.001  # 极短超时

            # 调用搜索，应该在超时后降级到 Mock 数据
            import time
            start_time = time.time()
            result = adapter.search_creators(self.test_category, self.test_count)
            end_time = time.time()

            # 验证在合理时间内返回（包含降级时间）
            elapsed = end_time - start_time
            assert elapsed < 5.0, f"Request timed out for too long: {elapsed}s"

            # 验证返回 Mock 数据
            assert isinstance(result, list), f"Expected list, got {type(result)}"
            assert len(result) == self.test_count, f"Expected {self.test_count} items, got {len(result)}"

        finally:
            # 恢复原始环境变量
            if original_api_key:
                os.environ['DOUYIN_STAR_API_KEY'] = original_api_key
            elif 'DOUYIN_STAR_API_KEY' in os.environ:
                del os.environ['DOUYIN_STAR_API_KEY']

            if original_api_secret:
                os.environ['DOUYIN_STAR_API_SECRET'] = original_api_secret
            elif 'DOUYIN_STAR_API_SECRET' in os.environ:
                del os.environ['DOUYIN_STAR_API_SECRET']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
