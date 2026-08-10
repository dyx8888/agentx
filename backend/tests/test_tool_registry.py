"""
工具注册中心测试
验证 ToolRegistry 单例和工具注册功能
"""

import logging
import os

# 添加项目根目录到 Python 路径
import sys
from unittest.mock import patch

import pytest  # type: ignore

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.tools.registry import ToolRegistry


class TestToolRegistry:
    """工具注册中心测试类"""

    def test_1_register_and_get_by_name(self):
        """正常场景1：注册工具后可按名称获取"""
        # 创建新的注册表实例
        registry = ToolRegistry()

        # 注册测试工具
        test_func = lambda x: x * 2
        registry.register("test_tool", test_func, description="测试工具")

        # 获取工具
        tools = registry.get_tools_by_names(["test_tool"])

        # 验证结果
        assert len(tools) == 1
        assert hasattr(tools[0], 'name')
        assert tools[0].name == "test_tool"

    def test_2_capability_mapping(self):
        """正常场景2：能力映射后可按能力获取工具集"""
        # 创建新的注册表实例
        registry = ToolRegistry()

        # 注册两个工具
        registry.register("tool_a", lambda x: x + 1, description="工具A")
        registry.register("tool_b", lambda x: x + 2, description="工具B")

        # 映射能力
        registry.map_capability_to_tools("demo", ["tool_a", "tool_b"])

        # 按能力获取工具
        tools = registry.get_tools_by_capabilities(["demo"])

        # 验证结果
        assert len(tools) == 2
        tool_names = [getattr(tool, 'name', 'unknown') for tool in tools]
        assert "tool_a" in tool_names
        assert "tool_b" in tool_names

    def test_3_get_nonexistent_tool(self):
        """异常场景1：获取未注册的工具名返回空列表"""
        # 创建新的注册表实例
        registry = ToolRegistry()

        # 获取不存在的工具
        tools = registry.get_tools_by_names(["nonexistent"])

        # 验证结果
        assert len(tools) == 0

    def test_4_duplicate_registration(self):
        """异常场景2：重复注册相同名称工具时覆盖"""
        # 创建新的注册表实例
        registry = ToolRegistry()

        # 注册第一个工具
        registry.register("duplicate_tool", lambda x: x + 1, description="第一个工具")

        # 注册同名工具（应该覆盖）
        registry.register("duplicate_tool", lambda x: x + 2, description="第二个工具")

        # 获取工具
        tools = registry.get_tools_by_names(["duplicate_tool"])

        # 验证只有一个工具
        assert len(tools) == 1
        # 验证是最后一个注册的版本
        result = tools[0](3)  # 调用工具函数
        assert result == 6  # x + 2

    def test_5_list_registered_tools(self):
        """正常场景3：列出所有已注册的工具"""
        # 创建新的注册表实例
        registry = ToolRegistry()

        # 注册多个工具
        registry.register("tool1", lambda x: x, description="工具1")
        registry.register("tool2", lambda x: x, description="工具2")
        registry.register("tool3", lambda x: x, description="工具3")

        # 列出所有工具
        tool_names = registry.list_registered_tools()

        # 验证结果
        assert len(tool_names) == 3
        assert "tool1" in tool_names
        assert "tool2" in tool_names
        assert "tool3" in tool_names

    def test_6_singleton_behavior(self):
        """正常场景4：单例模式验证"""
        # 创建两个实例
        registry1 = ToolRegistry()
        registry2 = ToolRegistry()

        # 在第一个实例注册工具
        registry1.register("singleton_test", lambda x: x, description="单例测试")

        # 验证第二个实例也能访问到相同的工具
        tools = registry2.get_tools_by_names(["singleton_test"])
        assert len(tools) == 1

        # 验证确实是同一个实例
        assert registry1 is registry2

    def test_7_get_tool_info(self):
        """正常场景5：获取工具详细信息"""
        # 创建新的注册表实例
        registry = ToolRegistry()

        # 注册工具
        test_func = lambda x: x * 3
        registry.register(
            name="info_test",
            func=test_func,
            description="信息测试工具",
            module_path="test.module",
            endpoint="test.endpoint"
        )

        # 获取工具信息
        info = registry.get_tool_info("info_test")

        # 验证信息
        assert info['tool'] is not None
        assert info['module_path'] == "test.module"
        assert info['endpoint'] == "test.endpoint"

    @patch('os.path.join')
    def test_8_register_from_config(self, mock_join):
        """正常场景6：从配置文件批量注册"""
        # 创建新的注册表实例
        registry = ToolRegistry()

        # Mock 配置文件内容
        mock_config_content = """
tools:
  - name: config_tool1
    module: test.module1
    function: test_func1
    - name: config_tool2
    module: test.module2
    function: test_func2
"""

        # Mock 文件读取
        mock_file = mock_open(mock_config_content)
        mock_join.return_value = "mocked_path"

        with patch('builtins.open', mock_file):
            registry.register_from_config()

        # 验证工具已注册
        tool_names = registry.list_registered_tools()
        assert "config_tool1" in tool_names
        assert "config_tool2" in tool_names


class TestLogValidation:
    """日志验证测试：确保关键操作有结构化日志输出"""

    def test_log_tool_registered(self, caplog):
        """验证：注册工具时产生 logger.info 日志"""
        caplog.set_level(logging.INFO)
        registry = ToolRegistry()
        registry.register("caplog_tool", lambda x: x, description="caplog测试")
        assert any("tool_registered" in r.message for r in caplog.records)
        assert any("caplog_tool" in r.message for r in caplog.records)

    def test_log_tool_not_found_warning(self, caplog):
        """验证：获取不存在的工具时产生 WARNING 日志"""
        caplog.set_level(logging.WARNING)
        registry = ToolRegistry()
        registry.get_tools_by_names(["nonexistent_tool_xyz"])
        assert any("tool_not_found" in r.message for r in caplog.records)

    def test_log_config_not_found_warning(self, caplog):
        """验证：配置文件不存在时产生 WARNING 日志"""
        caplog.set_level(logging.WARNING)
        registry = ToolRegistry()
        registry.register_from_config("/nonexistent/path.yaml")
        assert any("tools_config_not_found" in r.message for r in caplog.records)

    def test_log_capability_mapped_info(self, caplog):
        """验证：映射能力时产生 INFO 日志"""
        caplog.set_level(logging.INFO)
        registry = ToolRegistry()
        registry.map_capability_to_tools("test_cap", ["tool_a", "tool_b"])
        assert any("capability_mapped" in r.message for r in caplog.records)

    def test_log_initialize_info(self, caplog):
        """验证：初始化时产生 structured 日志"""
        caplog.set_level(logging.INFO)
        registry = ToolRegistry()
        registry.initialize_from_config()
        assert any("tool_registry_initializing" in r.message for r in caplog.records)


class TestSensitiveDataRedaction:
    """敏感信息脱敏验证"""

    def test_password_field_redacted(self, caplog):
        """验证：password 字段值被替换为 [REDACTED]"""
        from app.core.logging import get_logger
        logger = get_logger(__name__)
        caplog.set_level(logging.INFO)
        logger.info("test_event", user="admin", password="secret123", action="login")
        output = caplog.text
        assert "[REDACTED]" in output
        assert "secret123" not in output

    def test_token_and_api_key_redacted(self, caplog):
        """验证：token / api_key 字段被脱敏"""
        from app.core.logging import get_logger
        logger = get_logger(__name__)
        caplog.set_level(logging.INFO)
        logger.info("test_event", api_key="sk-abc123", token="bearer-xyz", user="admin")
        output = caplog.text
        assert output.count("[REDACTED]") == 2
        assert "sk-abc123" not in output
        assert "bearer-xyz" not in output

    def test_normal_fields_preserved(self, caplog):
        """验证：普通字段不被脱敏"""
        from app.core.logging import get_logger
        logger = get_logger(__name__)
        caplog.set_level(logging.INFO)
        logger.info("test_event", user="admin", action="login", company_id=42)
        output = caplog.text
        assert "admin" in output
        assert "login" in output
        assert "42" in output


def mock_open(content):
    """Mock 文件打开"""
    class MockFile:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self, *args, **kwargs):
            return content
    return MockFile


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
