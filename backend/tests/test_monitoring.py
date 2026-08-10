"""
监控与可观测性测试
验证 Prometheus 指标端点和中间件功能
"""

import pytest
import re
import time
from fastapi.testclient import TestClient

# 添加项目根目录到 Python 路径
import sys
import os
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app

class TestMonitoring:
    """监控功能测试类"""
    
    @pytest.mark.asyncio
    async def test_1_metrics_endpoint_accessible(self):
        """正常场景1：/metrics 端点可访问且返回 Prometheus 格式"""
        with TestClient(app) as client:
            # 请求指标端点
            response = client.get("/metrics")
            
            # 验证响应
            assert response.status_code == 200
            assert "text/plain" in response.headers["content-type"]
            
            # 验证包含基本指标
            content = response.text
            assert "agentx_requests_total" in content
            assert "agentx_request_latency_seconds" in content
            assert "agentx_agent_tasks_total" in content
            assert "agentx_tool_calls_total" in content
            assert "agentx_llm_tokens_total" in content
    
    @pytest.mark.asyncio
    async def test_2_request_count_increments(self):
        """正常场景2：发送请求后指标计数增加"""
        with TestClient(app) as client:
            # 获取初始指标
            initial_response = client.get("/metrics")
            initial_content = initial_response.text
            
            # 解析初始请求数
            initial_count_match = re.search(r'agentx_requests_total\{[^}]*\} ([0-9]+)', initial_content)
            initial_count = int(initial_count_match.group(1)) if initial_count_match else 0
            
            # 发送一个健康检查请求
            client.get("/health")
            
            # 再次获取指标
            updated_response = client.get("/metrics")
            updated_content = updated_response.text
            
            # 解析更新后请求数
            updated_count_match = re.search(r'agentx_requests_total\{[^}]*\} ([0-9]+)', updated_content)
            updated_count = int(updated_count_match.group(1)) if updated_count_match else 0
            
            # 验证计数增加
            assert updated_count == initial_count + 2  # 健康检查 + 指标请求
    
    @pytest.mark.asyncio
    async def test_3_metrics_endpoint_public(self):
        """异常场景1：/metrics 端点不受权限控制（可公开访问）"""
        with TestClient(app) as client:
            # 不携带认证信息访问指标端点
            response = client.get("/metrics")
            
            # 应该成功访问
            assert response.status_code == 200
            assert len(response.text) > 0
    
    @pytest.mark.asyncio
    async def test_4_middleware_no_impact(self):
        """异常场景2：中间件不影响现有 API 的正常响应"""
        with TestClient(app) as client:
            # 发送认证请求（即使返回 401）
            auth_response = client.post("/auth/token", json={
                "username": "testuser",
                "password": "wrongpassword"
            })
            
            # 发送健康检查请求
            health_response = client.get("/health")
            
            # 验证健康检查正常
            assert health_response.status_code == 200
            assert "status" in health_response.json()
            
            # 验证指标端点仍可访问
            metrics_response = client.get("/metrics")
            assert metrics_response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_5_latency_histogram_works(self):
        """正常场景3：延迟直方图指标正常工作"""
        with TestClient(app) as client:
            # 发送多个请求以测试延迟
            for i in range(3):
                start_time = time.time()
                client.get("/health")
                time.sleep(0.1)  # 模拟处理时间
            
            # 获取指标
            response = client.get("/metrics")
            content = response.text
            
            # 验证包含延迟指标
            assert "agentx_request_latency_seconds" in content
            assert "histogram" in content.lower()
    
    @pytest.mark.asyncio
    async def test_6_metrics_format_valid(self):
        """正常场景4：指标格式符合 Prometheus 标准"""
        with TestClient(app) as client:
            response = client.get("/metrics")
            content = response.text
            
            # 验证 Prometheus 格式
            lines = content.strip().split('\n')
            
            # 检查基本指标格式
            metric_lines = [line for line in lines if line.startswith('# TYPE')]
            assert len(metric_lines) > 0
            
            # 检查指标定义行
            for line in metric_lines:
                assert '{' in line and '}' in line
                assert 'HELP' in line or 'TYPE' in line


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
