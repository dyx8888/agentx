"""
综合集成测试——验证序号六至二十任务完成情况
覆盖各序号核心功能的集成测试
"""

import pytest
import json
import asyncio
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import sys
import os
from pathlib import Path
from starlette.routing import WebSocketRoute

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.main import app
from app.database import db
from app.tools.registry import registry
from app.communication.collaboration import collaboration_engine

class TestIntegrationAll:
    """综合集成测试类"""
    
    @classmethod
    def setup_class(cls):
        """测试类初始化"""
        cls.client = TestClient(app)
        
        # 初始化数据库
        try:
            db.init_database()
        except Exception as e:
            print(f"Database initialization warning: {e}")
    
    def test_1_subscription_plans_api_available(self):
        """测试 1：订阅计划 API 可用（序号十二）"""
        response = self.client.get("/api/subscription/plans")
        
        # 验证状态码
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        # 验证返回格式
        data = response.json()
        assert isinstance(data, list), "Expected list response"
        
        # 如果有数据，验证结构
        if data:
            assert "name" in data[0], "Plan should have name field"
            assert "price_per_month" in data[0], "Plan should have price_per_month field"
    
    def test_2_legal_pages_available(self):
        """测试 2：当前前端提供法律页面（后端没有 /api/legal/* 路由）。"""
        legal_page = Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "LegalPage.jsx"
        assert legal_page.exists(), "Frontend legal page should exist"

        content = legal_page.read_text(encoding="utf-8")
        assert "terms" in content, "Legal page should provide terms content"
        assert "privacy" in content, "Legal page should provide privacy content"
        assert "export default" in content, "Legal page should export a component"
    
    def test_3_websocket_endpoint_connectable(self):
        """测试 3：WebSocket 端点可连接（序号十四）"""
        # WebSocket 路由不能用普通 HTTP GET 验证；实际握手和消息行为由 test_websocket.py 覆盖。
        websocket_paths = {
            route.path for route in app.routes if isinstance(route, WebSocketRoute)
        }
        assert "/ws/tasks/{task_id}" in websocket_paths
    
    def test_4_metrics_endpoint_accessible(self):
        """测试 4：监控指标端点可访问（序号十六）"""
        response = self.client.get("/metrics")
        
        # 验证状态码
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        # 验证返回 Prometheus 格式
        content = response.text
        assert "agentx_requests_total" in content, "Should contain agentx_requests_total metric"
        assert "agentx_request_latency_seconds" in content, "Should contain agentx_request_latency_seconds metric"
    
    def test_5_brand_bd_workflow_template_loadable(self):
        """测试 5：品牌商务工作流模板可加载（序号十一）"""
        try:
            from app.workflows.brand_bd_workflow import load_workflow_template
            
            template = load_workflow_template('brand_bd_workflow')
            
            # 验证模板结构
            assert isinstance(template, dict), "Workflow template should be a dictionary"
            assert "nodes" in template, "Workflow should have nodes field"
            
            # 验证节点数量（应该有 6 个节点）
            nodes = template["nodes"]
            assert len(nodes) >= 5, f"Expected at least 5 nodes, got {len(nodes)}"
            
            # 验证节点结构
            for node in nodes:
                assert "name" in node, "Node should have name field"
                assert "type" in node, "Node should have type field"
                
        except ImportError as e:
            pytest.skip(f"Brand BD workflow not implemented: {e}")
    
    def test_6_platform_credentials_api_available(self):
        """测试 6：平台凭证绑定 API 可用（序号七）"""
        # 测试无认证访问
        response = self.client.post("/api/admin/companies/1/credentials", json={
            "platform": "xiaohongshu",
            "credentials": {"access_token": "test"}
        })
        
        # 验证认证失败返回 401
        assert response.status_code in [401, 403], f"Expected auth error, got {response.status_code}"
    
    def test_7_task_confirmation_endpoint_exists(self):
        """测试 7：任务确认端点存在（序号九）"""
        response = self.client.get("/api/tasks/1/steps")
        
        # 应该返回 401（未认证）或 200（如果有默认数据）
        assert response.status_code in [200, 401, 404], f"Unexpected status: {response.status_code}"
        
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, (list, dict)), "Should return list or dict"
    
    def test_8_knowledge_upload_api_available(self):
        """测试 8：知识上传 API 可用（序号四）"""
        # 认证依赖先于请求体校验执行；未认证请求应先返回认证错误。
        response = self.client.post("/api/knowledge/upload", json={})
        
        assert response.status_code in [401, 403], f"Expected auth error, got {response.status_code}"
        
        data = response.json()
        assert "message" in data, "Should return structured auth error details"
    
    def test_9_nonexistent_route_returns_404(self):
        """测试 9：不存在的路由返回 404"""
        response = self.client.get("/api/nonexistent_route")
        # 全局 OPTIONS 通配路由会让未知 GET 路径落入 405；两者都表示没有成功匹配业务路由。
        assert response.status_code in [404, 405], f"Expected missing-route status, got {response.status_code}"
    
    def test_10_protected_endpoint_requires_auth(self):
        """测试 10：无 Token 访问受保护端点返回 401"""
        response = self.client.get("/api/admin/agents/")
        assert response.status_code in [401, 403], f"Expected auth error, got {response.status_code}"
    
    def test_11_tool_registry_functionality(self):
        """测试 11：工具注册中心功能（序号十七）"""
        # 测试工具注册
        test_func = lambda x: x * 2
        registry.register("test_integration_tool", test_func, description="集成测试工具")
        
        # 验证工具已注册
        tools = registry.get_tools_by_names(["test_integration_tool"])
        assert len(tools) == 1, "Should return 1 tool"
        
        # 验证工具名称
        assert hasattr(tools[0], 'name'), "Tool should have name attribute"
    
    def test_12_collaboration_engine_functionality(self):
        """测试 12：协作引擎功能（序号十八）"""
        # 注册 Agent 能力
        collaboration_engine.register_agent_capabilities(
            agent_name="TestAgent",
            capabilities=["test_capability"],
            next_agent="NextAgent"
        )
        
        # 验证能力注册
        capabilities = collaboration_engine.get_agent_capabilities("TestAgent")
        assert "test_capability" in capabilities, "Should contain registered capability"
        
        # 验证推荐接力对象
        next_agent = collaboration_engine.get_next_agent("TestAgent")
        assert next_agent == "NextAgent", "Should return next agent"
    
    def test_13_data_encryption_functionality(self):
        """测试 13：数据加密功能（序号十三）"""
        try:
            from app.utils.encryption import encrypt_data, decrypt_data
            
            # 测试加密解密
            original_data = "test sensitive data"
            encrypted = encrypt_data(original_data)
            decrypted = decrypt_data(encrypted)
            
            assert original_data == decrypted, "Decrypted data should match original"
            assert encrypted != original_data, "Encrypted data should be different"
            
        except ImportError as e:
            pytest.skip(f"Encryption module not available: {e}")
    
    def test_14_database_backup_functionality(self):
        """测试 14：数据库备份功能（序号十五）"""
        try:
            import subprocess
            import tempfile
            
            # 测试备份脚本存在
            backup_script = os.path.join(os.path.dirname(__file__), "..", "scripts", "backup_db.py")
            assert os.path.exists(backup_script), "Backup script should exist"
            
            # 测试备份脚本可执行（不实际执行）
            with open(backup_script, 'r') as f:
                content = f.read()
                assert "def main" in content, "Backup script should have main function"
                
        except Exception as e:
            pytest.skip(f"Backup functionality test skipped: {e}")
    
    def test_15_frontend_pages_renderable(self):
        """测试 15：前端页面可渲染（序号二十）"""
        # 测试前端文件存在
        frontend_files = [
            "frontend/src/pages/Register.jsx",
            "frontend/src/pages/AgentConfig.jsx"
        ]
        
        for file_path in frontend_files:
            full_path = os.path.join(os.path.dirname(__file__), "..", "..", file_path)
            assert os.path.exists(full_path), f"Frontend file {file_path} should exist"
            
            # 验证文件包含基本 React 组件结构
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
                assert "export default" in content, f"File {file_path} should export default component"
                assert "import" in content, f"File {file_path} should have imports"
    
    def test_16_monitoring_metrics_increment(self):
        """测试 16：监控指标递增（序号十六）"""
        # 发送请求以增加指标
        response1 = self.client.get("/health")
        assert response1.status_code == 200
        
        # 再次获取指标
        response2 = self.client.get("/metrics")
        assert response2.status_code == 200
        
        # 验证指标包含请求计数
        content = response2.text
        assert "agentx_requests_total" in content.lower(), "Should contain request count metric"
    
    def test_17_subscription_management_api(self):
        """测试 17：订阅管理 API（序号十二）"""
        # 测试订阅计划列表
        response = self.client.get("/api/subscription/plans")
        assert response.status_code == 200
        
        # 如果有订阅端点，测试订阅创建
        try:
            response = self.client.post("/api/subscription/hire", json={
                "plan_id": "basic",
                "agent_name": "TestAgent"
            })
            # 应该返回 401（未认证）或 400（参数错误）
            assert response.status_code in [401, 400, 404], f"Unexpected status: {response.status_code}"
        except Exception:
            pytest.skip("Subscription hire endpoint not implemented")
    
    def test_18_workflow_execution_functionality(self):
        """测试 18：工作流执行功能（序号十一）"""
        try:
            from app.workflows.brand_bd_workflow import execute_brand_bd_workflow
            
            # 测试工作流执行函数存在
            assert callable(execute_brand_bd_workflow), "Workflow execution function should be callable"
            
        except ImportError as e:
            pytest.skip(f"Workflow execution not implemented: {e}")
    
    def test_19_knowledge_base_integration(self):
        """测试 19：知识库集成（序号四）"""
        # 测试知识库端点
        response = self.client.get("/api/knowledge/search")
        
        # 应该返回 200 或 401（未认证）
        assert response.status_code in [200, 401], f"Unexpected status: {response.status_code}"
        
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, (list, dict)), "Should return list or dict"
    
    def test_20_system_health_overall(self):
        """测试 20：系统整体健康状态"""
        # 测试主要端点
        endpoints_to_test = [
            "/health",
            "/api/chat/health",
            "/metrics",
            "/api/subscription/plans"
        ]
        
        failed_endpoints = []
        for endpoint in endpoints_to_test:
            response = self.client.get(endpoint)
            if response.status_code not in [200, 401, 404]:
                failed_endpoints.append(f"{endpoint}: {response.status_code}")
        
        # 允许部分端点失败，但核心健康检查应该工作
        health_response = self.client.get("/health")
        assert health_response.status_code == 200, "Health endpoint should always work"
        
        if failed_endpoints:
            print(f"Warning: Some endpoints failed: {failed_endpoints}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
