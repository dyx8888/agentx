"""
品牌商务工作流测试
测试品牌商务标准工作流的模板加载和执行功能
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.workflow.engine import WorkflowEngine


class TestBrandWorkflow:
    """品牌商务工作流测试类"""

    @classmethod
    def setup_class(cls):
        """测试类初始化"""
        cls.test_company_id = 9999
        cls.test_context = {
            'category': 'beauty',
            'product_name': '测试产品',
            'order_id': 'ORD001',
            'campaign_id': 'CMP001'
        }

    def setup_method(self):
        """每个测试方法前的设置"""
        # 创建 WorkflowEngine 实例
        self.engine = WorkflowEngine()

    def test_1_load_workflow_template_success(self):
        """正常场景 1：工作流模板加载成功"""
        try:
            # 调用模板加载方法
            template = self.engine.load_workflow_template('brand_bd_workflow')

            # 验证返回的字典结构
            assert 'name' in template, "Template should have 'name' field"
            assert 'description' in template, "Template should have 'description' field"
            assert 'nodes' in template, "Template should have 'nodes' field"

            # 验证节点数量和ID
            nodes = template['nodes']
            assert len(nodes) == 6, f"Expected 6 nodes, got {len(nodes)}"

            node_ids = [node['id'] for node in nodes]
            assert 'search_kols_node' in node_ids, "Should contain search_kols_node"
            assert 'generate_outreach_node' in node_ids, "Should contain generate_outreach_node"
            assert 'generate_script_node' in node_ids, "Should contain generate_script_node"
            assert 'check_delivery_node' in node_ids, "Should contain check_delivery_node"
            assert 'arrival_script_node' in node_ids, "Should contain arrival_script_node"
            assert 'performance_report_node' in node_ids, "Should contain performance_report_node"

            # 验证模板名称
            assert template['name'] == 'brand_bd_standard', f"Expected 'brand_bd_standard', got {template['name']}"

        except Exception as e:
            pytest.fail(f"Template loading failed: {e}")

    def test_2_execute_brand_bd_workflow_success(self):
        """正常场景 2：使用指定上下文执行工作流并返回 ID"""
        # Mock 数据库操作
        with patch('app.database.db.create_workflow') as mock_create_workflow, \
             patch('app.database.db.create_a2a_message') as mock_create_message, \
             patch('app.database.db.update_a2a_message_status') as mock_update_message, \
             patch('app.database.db.update_workflow_status') as mock_update_workflow:

            # Mock 数据库返回工作流ID
            mock_create_workflow.return_value = 12345

            # Mock A2A消息创建
            mock_create_message.return_value = 1001

            # Mock Agent 执行
            with patch('app.workflow.engine.get_agent_for_tools') as mock_get_agent:
                mock_agent = MagicMock()
                mock_agent.search_kols.return_value = {"data": [{"name": "测试达人"}]}
                mock_agent.generate_outreach.return_value = "邀约话术生成成功"
                mock_agent.generate_script.return_value = "脚本生成成功"
                mock_agent.check_delivery_status.return_value = {"status": "已发货"}
                mock_agent.generate_arrival_script.return_value = "到货提醒生成成功"
                mock_agent.generate_performance_report.return_value = "报告生成成功"
                mock_get_agent.return_value = (mock_agent, mock_agent)

                # 调用品牌商务工作流执行
                result = self.engine.execute_brand_bd_workflow(self.test_company_id, self.test_context)

                # 验证返回的工作流ID不为空
                assert result is not None, "Workflow ID should not be None"
                assert result != "Error executing brand BD workflow", "Should not return error message"

                # 验证数据库调用
                mock_create_workflow.assert_called_once()
                call_args = mock_create_workflow.call_args
                assert call_args[0] == self.test_company_id, "Company ID should match"
                assert call_args[1] == 'brand_bd_standard', "Workflow name should match"

                # 验证模板变量替换
                definition_json = call_args[2]
                assert 'beauty' in definition_json, "Category should be replaced"
                assert '测试产品' in definition_json, "Product name should be replaced"
                assert 'ORD001' in definition_json, "Order ID should be replaced"
                assert 'CMP001' in definition_json, "Campaign ID should be replaced"

    def test_3_load_nonexistent_template_error(self):
        """异常场景 1：模板文件不存在时抛出明确错误"""
        with pytest.raises(FileNotFoundError) as exc_info:
            # 尝试加载不存在的模板
            self.engine.load_workflow_template('non_existent_template')

        # 验证错误信息
        error_message = str(exc_info.value)
        assert 'not found' in error_message.lower(), "Error message should mention not found"
        assert 'non_existent_template' in error_message, "Error message should mention template name"

    def test_4_execute_with_missing_context_params(self):
        """异常场景 2：上下文缺少必要参数时使用默认值"""
        # Mock 数据库操作
        with patch('app.database.db.create_workflow') as mock_create_workflow, \
             patch('app.database.db.create_a2a_message') as mock_create_message, \
             patch('app.database.db.update_a2a_message_status') as mock_update_message, \
             patch('app.database.db.update_workflow_status') as mock_update_workflow:

            # Mock 数据库返回工作流ID
            mock_create_workflow.return_value = 12345

            # Mock A2A消息创建
            mock_create_message.return_value = 1001

            # Mock Agent 执行
            with patch('app.workflow.engine.get_agent_for_tools') as mock_get_agent:
                mock_agent = MagicMock()
                mock_agent.search_kols.return_value = {"data": [{"name": "测试达人"}]}
                mock_agent.generate_outreach.return_value = "邀约话术生成成功"
                mock_get_agent.return_value = (mock_agent, mock_agent)

                # 调用品牌商务工作流执行，但缺少部分上下文参数
                incomplete_context = {
                    'category': 'beauty',
                    'product_name': '测试产品'
                    # 缺少 order_id 和 campaign_id
                }

                result = self.engine.execute_brand_bd_workflow(self.test_company_id, incomplete_context)

                # 验证仍然可以创建工作流（不会崩溃）
                assert result is not None, "Workflow ID should not be None"
                assert result != "Error executing brand BD workflow", "Should not return error message"

                # 验证数据库调用
                mock_create_workflow.assert_called_once()

                # 验证模板变量替换（缺失的参数应该为空字符串或默认值）
                definition_json = mock_create_workflow.call_args[2]
                assert 'beauty' in definition_json, "Category should be replaced"
                assert '测试产品' in definition_json, "Product name should be replaced"

    def test_5_template_variable_replacement(self):
        """测试模板变量替换功能"""
        # 测试简单变量替换
        template_str = '{"category": "{{category}}", "product": "{{product_name}}"}'
        context = {'category': 'beauty', 'product_name': '测试产品'}

        result = self.engine._replace_template_variables(template_str, context)

        assert 'beauty' in result, "Category should be replaced"
        assert '测试产品' in result, "Product name should be replaced"
        assert '{{category}}' not in result, "Placeholder should be replaced"
        assert '{{product_name}}' not in result, "Placeholder should be replaced"

    def test_6_nested_variable_replacement(self):
        """测试嵌套变量替换功能"""
        # 测试嵌套变量替换
        template_str = '{"kol_name": "{{search_kols_node.result.name}}", "status": "{{check_delivery_node.result.status}}"}'
        context = {
            'search_kols_node': {'result': {'name': '测试达人'}},
            'check_delivery_node': {'result': {'status': '已发货'}}
        }

        result = self.engine._replace_template_variables(template_str, context)

        assert '测试达人' in result, "Nested variable should be replaced"
        assert '已发货' in result, "Nested variable should be replaced"
        assert '{{search_kols_node.result.name}}' not in result, "Placeholder should be replaced"

    def test_7_template_json_validation(self):
        """测试模板JSON格式验证"""
        # 测试无效JSON文件
        with patch('builtins.open', create=True) as mock_open:
            # 模拟无效JSON内容
            mock_file = MagicMock()
            mock_file.__enter__.return_value = mock_file
            mock_file.read.return_value = '{"invalid": json, content,}'
            mock_open.return_value = mock_file

            with patch('os.path.exists', return_value=True):
                with pytest.raises(json.JSONDecodeError):
                    self.engine.load_workflow_template('invalid_template')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
