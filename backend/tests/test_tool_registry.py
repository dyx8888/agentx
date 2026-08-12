"""
xxxxxxxxxxx
xxx ToolRegistry xxxxxxxxxxxxx?
"""

import logging
import os

# xxxxxxxxxxxx Python xx
import sys
from unittest.mock import mock_open as unittest_mock_open
from unittest.mock import patch

import pytest  # type: ignore

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def _reset_tool_registry_singleton():
    """xxxxxxxxxx?ToolRegistry xxxxxxxxxxxxxxxxxxxxxxxxxxxx

    xxxxx API clear() xxxxxxxxxxxxxxx?
    xxxxxxxxxxxxxxx?_tools / _capability_map x?_data_lock xxxxxx?
    """
    instance = ToolRegistry()
    instance.clear()
    yield


class TestToolRegistry:
    """xxxxxxxxxxxx?"""

    def test_1_register_and_get_by_name(self):
        """xxxxxx1xxxxxxxxxxxxxxxxx"""
        # xxxxxxxxxxxxx?
        registry = ToolRegistry()

        # xxxxxxxxx
        def test_func(x):
            return x * 2

        registry.register("test_tool", test_func, description="xxxxxx")

        # xxxxxx
        tools = registry.get_tools_by_names(["test_tool"])

        # xxxxxx
        assert len(tools) == 1
        assert hasattr(tools[0], "name")
        assert tools[0].name == "test_tool"

    def test_2_capability_mapping(self):
        """xxxxxx2xxxxxxxxxxxxxxxxxxxxx?"""
        # xxxxxxxxxxxxx?
        registry = ToolRegistry()

        # xxxxxxxxx
        registry.register("tool_a", lambda x: x + 1, description="xxxA")
        registry.register("tool_b", lambda x: x + 2, description="xxxB")

        # xxxxxx
        registry.map_capability_to_tools("demo", ["tool_a", "tool_b"])

        # xxxxxxxxxx?
        tools = registry.get_tools_by_capabilities(["demo"])

        # xxxxxx
        assert len(tools) == 2
        tool_names = [getattr(tool, "name", "unknown") for tool in tools]
        assert "tool_a" in tool_names
        assert "tool_b" in tool_names

    def test_3_get_nonexistent_tool(self):
        """xxxxxx1xxxxxxxxxxxxxxxxxxxxxx?"""
        # xxxxxxxxxxxxx?
        registry = ToolRegistry()

        # xxxxxxxxxxxx
        tools = registry.get_tools_by_names(["nonexistent"])

        # xxxxxx
        assert len(tools) == 0

    def test_4_duplicate_registration(self):
        """xxxxxx2xxxxxxxxxxxxxxxxxxxxx"""
        # xxxxxxxxxxxxx?
        registry = ToolRegistry()

        # xxxxxxxx?
        registry.register("duplicate_tool", lambda x: x + 1, description="xxxxx?")

        # xxxxxxxxxxxxxxxxx
        registry.register("duplicate_tool", lambda x: x + 2, description="xxxxx?")

        # xxxxxx
        tools = registry.get_tools_by_names(["duplicate_tool"])

        # xxxxxxxxxx?
        assert len(tools) == 1
        # xxxxxxxxxxxxxxxxxxtructuredTool xxxxxxxxxxxxx?invokex?
        result = tools[0].invoke({"x": 3})  # xxxxxxxxx
        assert result == 5  # 3 + 2

    def test_5_list_registered_tools(self):
        """xxxxxx3xxxxxxxxxxxxxxxx?"""
        # xxxxxxxxxxxxx?
        registry = ToolRegistry()

        # xxxxxxxxx
        registry.register("tool1", lambda x: x, description="xxx1")
        registry.register("tool2", lambda x: x, description="xxx2")
        registry.register("tool3", lambda x: x, description="xxx3")

        # xxxxxxxxx?
        tool_names = registry.list_registered_tools()

        # xxxxxx
        assert len(tool_names) == 3
        assert "tool1" in tool_names
        assert "tool2" in tool_names
        assert "tool3" in tool_names

    def test_6_singleton_behavior(self):
        """xxxxxx4xxxxxxxxxx?"""
        # xxxxxxxxx
        registry1 = ToolRegistry()
        registry2 = ToolRegistry()

        # xxxxxxxxxxxxx?
        registry1.register("singleton_test", lambda x: x, description="xxxxxx")

        # xxxxxxxxxxxxxxxxxxxxx?
        tools = registry2.get_tools_by_names(["singleton_test"])
        assert len(tools) == 1

        # xxxxxxxxxxxx?
        assert registry1 is registry2

    def test_7_get_tool_info(self):
        """xxxxxx5xxxxxxxxxxxx?"""
        # xxxxxxxxxxxxx?
        registry = ToolRegistry()

        # xxxxxx
        def test_func(x):
            return x * 3

        registry.register(
            name="info_test",
            func=test_func,
            description="xxxxxxxxx",
            module_path="test.module",
            endpoint="test.endpoint",
        )

        # xxxxxxxxx
        info = registry.get_tool_info("info_test")

        # xxxxxx
        assert info["tool"] is not None
        assert info["module_path"] == "test.module"
        assert info["endpoint"] == "test.endpoint"

    def test_8_register_from_config(self):
        """xxxxxx6xxxxxxxxxxxxxxx"""
        # xxxxxxxxxxxxx?
        registry = ToolRegistry()

        # Mock xxxxxxxxxxxx?providers xxxxxx?register_from_config xxxxx
        mock_config_content = """
providers:
  - name: config_tool1
    module: test.module1
    function: test_func1
  - name: config_tool2
    module: test.module2
    function: test_func2
"""

        # xxx unittest.mock.mock_openxxxxxxxxxxxxxxxxxx yaml.safe_load xxxxxx?
        mock_file = unittest_mock_open(read_data=mock_config_content)

        # xxxxxx?tool() xxxxxxxxxxxxxxx?docstringxxxxxx description xxxxxxx?
        class _FakeModule:
            @staticmethod
            def test_func1(x):
                """xxxxxx1"""
                return x

            @staticmethod
            def test_func2(x):
                """xxxxxx2"""
                return x

        # xxxxxx config_pathxxxxxxxx patch os.path.join xxx langchain xxxxxx
        with (
            patch("builtins.open", mock_file),
            patch("importlib.import_module", return_value=_FakeModule),
        ):
            registry.register_from_config(config_path="mocked_path")

        # xxxxxxxxxx?
        tool_names = registry.list_registered_tools()
        assert "config_tool1" in tool_names
        assert "config_tool2" in tool_names


    def test_9_register_mixed_provider_config(self):
        """x provider xxxMCP xxxxxxxxxxHTTP xxxxx"""
        registry = ToolRegistry()

        mock_config_content = """
providers:
  - name: runtime_mcp
    type: mcp_stdio
    command: python
    args: ["-m", "demo"]
    capabilities: [search]
  - name: local_provider
    type: local
    module: local.module
    function: get_agent_tools
    agent_key: demo_agent
    capabilities: [analysis]
  - name: http_provider
    type: http_endpoint
    url: "http://example.test/tool"
    capabilities: [search]
capability_map:
  analysis: [local_provider]
  search: [runtime_mcp, http_provider]
"""

        def local_tool(value: int = 1):
            """xxxxxx"""
            return value

        def http_tool(**kwargs):
            """HTTP xxxx"""
            return kwargs

        class _FakeLocalModule:
            @staticmethod
            def get_agent_tools(agent_key):
                assert agent_key == "demo_agent"
                return [local_tool]

        def _import_side_effect(module_name):
            if module_name == "local.module":
                return _FakeLocalModule
            raise ModuleNotFoundError(module_name)

        mock_file = unittest_mock_open(read_data=mock_config_content)
        with (
            patch("builtins.open", mock_file),
            patch("app.services.tool_client.create_http_tool", return_value=http_tool),
            patch("importlib.import_module", side_effect=_import_side_effect),
        ):
            registry.register_from_config(config_path="mocked_path")

        assert "local_provider" in registry.list_registered_tools()
        assert "http_provider" in registry.list_registered_tools()
        assert len(registry.get_tools_by_capabilities(["analysis"])) == 1
        assert len(registry.get_tools_by_capabilities(["search"])) == 1

    def test_10_create_http_tool_returns_structured_tool(self):
        """HTTP xxxxxxxxx Agent xxx StructuredToolx"""
        from langchain_core.tools import StructuredTool

        from app.services.tool_client import create_http_tool

        http_tool = create_http_tool(
            name="demo_http_tool",
            description="Demo HTTP tool",
            endpoint="http://example.test/tool",
        )

        assert isinstance(http_tool, StructuredTool)
        assert http_tool.name == "demo_http_tool"
        assert http_tool.description == "Demo HTTP tool"

class TestLogValidation:
    """xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx?"""

    def test_log_tool_registered(self, caplog):
        """xxxxxxxxxxxxxxx logger.info xxx"""
        caplog.set_level(logging.INFO)
        registry = ToolRegistry()
        registry.register("caplog_tool", lambda x: x, description="caplogxxx")
        assert any("tool_registered" in r.message for r in caplog.records)
        assert any("caplog_tool" in r.message for r in caplog.records)

    def test_log_tool_not_found_warning(self, caplog):
        """xxxxxxxxxxxxxxxxxxxxx WARNING xxx"""
        caplog.set_level(logging.WARNING)
        registry = ToolRegistry()
        registry.get_tools_by_names(["nonexistent_tool_xyz"])
        assert any("tool_not_found" in r.message for r in caplog.records)

    def test_log_config_not_found_warning(self, caplog):
        """xxxxxxxxxxxxxxxxxx?WARNING xxx"""
        caplog.set_level(logging.WARNING)
        registry = ToolRegistry()
        registry.register_from_config("/nonexistent/path.yaml")
        assert any("tools_config_not_found" in r.message for r in caplog.records)

    def test_log_capability_mapped_info(self, caplog):
        """xxxxxxxxxxxxxxx INFO xxx"""
        caplog.set_level(logging.INFO)
        registry = ToolRegistry()
        registry.map_capability_to_tools("test_cap", ["tool_a", "tool_b"])
        assert any("capability_mapped" in r.message for r in caplog.records)

    def test_log_initialize_info(self, caplog):
        """xxxxxxxxxxxxx?structured xxx"""
        caplog.set_level(logging.INFO)
        registry = ToolRegistry()
        registry.initialize_from_config()
        assert any("tool_registry_initializing" in r.message for r in caplog.records)


class TestSensitiveDataRedaction:
    """xxxxxxxxxxxx"""

    def test_password_field_redacted(self, caplog):
        """xxxxxassword xxxxxxxx?[REDACTED]"""
        from app.core.logging import get_logger

        logger = get_logger(__name__)
        caplog.set_level(logging.INFO)
        logger.info("test_event", user="admin", password="secret123", action="login")
        output = caplog.text
        assert "[REDACTED]" in output
        assert "secret123" not in output

    def test_token_and_api_key_redacted(self, caplog):
        """xxxxxoken / api_key xxxxx?"""
        from app.core.logging import get_logger

        logger = get_logger(__name__)
        caplog.set_level(logging.INFO)
        logger.info("test_event", api_key="sk-abc123", token="bearer-xyz", user="admin")
        output = caplog.text
        assert output.count("[REDACTED]") == 2
        assert "sk-abc123" not in output
        assert "bearer-xyz" not in output

    def test_normal_fields_preserved(self, caplog):
        """xxxxxxxxxxxxxxx?"""
        from app.core.logging import get_logger

        logger = get_logger(__name__)
        caplog.set_level(logging.INFO)
        logger.info("test_event", user="admin", action="login", company_id=42)
        output = caplog.text
        assert "admin" in output
        assert "login" in output
        assert "42" in output


def mock_open(content):
    """Mock xxxxxx"""

    class MockFile:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def read(self, *args, **kwargs):
            return content

    return MockFile


class TestThreadSafetyFix:
    """xxxxxxxxxxxxxxxxxxxxxx1x?

    xxxx?
    - xxxxxxxxxxxxxxxxxxxCLx?
    - xxxxxxxxx RLock xxx
    """

    def test_singleton_creation_is_thread_safe(self):
        """xxxxxx ToolRegistry xxxxxxxxxxxxxxxxx"""
        import threading

        instances = []
        barrier = threading.Barrier(10)  # 10 xxxxxxxxxxxxxxxxxxxxx?

        def _create_instance():
            barrier.wait()  # xxxxxxxxxxxx?__new__
            instances.append(ToolRegistry())

        threads = [threading.Thread(target=_create_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # xxxxxxxxxxxxxxxxxxxxx?
        assert len(instances) == 10
        first = instances[0]
        assert all(inst is first for inst in instances)

    def test_concurrent_register_and_read(self):
        """xxxxxxxxxxxxxxxxxxxxxxxxxx?"""
        import threading

        registry = ToolRegistry()
        registry.clear()

        errors = []
        writer_done = threading.Event()

        def _writer():
            try:
                for i in range(50):
                    # xxxxxxxxxxxxxxxxxx?lambda xxxxxx?@tool xxxxxxxx
                    def _tool_func(x):
                        return x

                    registry.register(
                        f"concurrent_tool_{i}", _tool_func, description=f"xxxxxx{i}"
                    )
            except Exception as e:
                errors.append(("writer", e))
            finally:
                writer_done.set()

        def _reader():
            try:
                while not writer_done.is_set():
                    names = registry.list_registered_tools()
                    # xxxxxxxxxxxxx?
                    _ = registry.get_tools_by_names(names[:5] if names else [])
            except Exception as e:
                errors.append(("reader", e))

        writer_thread = threading.Thread(target=_writer)
        reader_thread = threading.Thread(target=_reader)

        writer_thread.start()
        reader_thread.start()

        writer_thread.join(timeout=5)
        writer_done.set()
        reader_thread.join(timeout=5)

        # xxxx?
        assert errors == [], f"xxxxxxxxxxxx: {errors}"
        # xxxxxxxxxxxx?
        names = registry.list_registered_tools()
        assert len(names) == 50

    def test_data_lock_is_reentrant(self):
        """RLock xxxxxxxxxxxxxegister_from_config x?registerx?"""
        registry = ToolRegistry()
        registry.clear()

        # xxx register_from_config xxxxxx register xxxxxxx?
        # xxxxxx Lock xxx RLockxxxxxxxxx
        mock_config_content = """
providers:
  - name: reentrant_test_1
    module: test.module_reentrant_1
    function: test_func
  - name: reentrant_test_2
    module: test.module_reentrant_2
    function: test_func
"""

        class _FakeModule:
            @staticmethod
            def test_func(x):
                """xxxxxx"""
                return x

        mock_file = unittest_mock_open(read_data=mock_config_content)
        with (
            patch("builtins.open", mock_file),
            patch("importlib.import_module", return_value=_FakeModule),
        ):
            # xxxxxx RLockxxxxxxxxxxxx
            registry.register_from_config(config_path="mocked_path")

        names = registry.list_registered_tools()
        assert "reentrant_test_1" in names
        assert "reentrant_test_2" in names


class TestConfigPathResolutionFix:
    """xxxxxxxxxxxxxxxxxxxxxxxx2x?

    xxxx?
    - xxx _resolve_config_path xxxxxx
    - xx TOOL_PROVIDERS_CONFIG xxxxxxx
    - xxx __file__ xxxxxxxxxxxx cwd
    """

    def test_explicit_config_path_takes_priority(self, monkeypatch):
        """xxxxxxx?config_path xxxxxxx?"""
        from app.tools.registry import _resolve_config_path

        # xxxxxxx
        monkeypatch.setenv("TOOL_PROVIDERS_CONFIG", "/env/path.yaml")

        result = _resolve_config_path("/explicit/path.yaml")
        assert result == "/explicit/path.yaml"

    def test_env_var_overrides_default(self, monkeypatch):
        """xxxxxxxxxxxxxxxxx?"""
        from app.tools.registry import _resolve_config_path

        monkeypatch.setenv("TOOL_PROVIDERS_CONFIG", "/from/env/config.yaml")
        result = _resolve_config_path(None)
        assert result == "/from/env/config.yaml"

    def test_default_path_when_no_override(self, monkeypatch):
        """xxxxxxxxxxxxxxxxxxxx?"""
        from app.tools.registry import _get_default_config_path, _resolve_config_path

        monkeypatch.delenv("TOOL_PROVIDERS_CONFIG", raising=False)
        result = _resolve_config_path(None)
        expected = _get_default_config_path()
        assert result == expected
        # xxxxxxxxxxxxx?
        assert os.path.isabs(result)
        # xxxxxxx tool_providers.yaml
        assert result.endswith("tool_providers.yaml")

    def test_default_path_does_not_depend_on_cwd(self, monkeypatch):
        """xxxxxxx __file__ xxxxxx?cwd xxxxxx"""
        from app.tools.registry import _get_default_config_path

        monkeypatch.delenv("TOOL_PROVIDERS_CONFIG", raising=False)
        original_cwd = os.getcwd()
        try:
            # xxxxxxxxxx?
            os.chdir(os.path.dirname(original_cwd) or "/")
            path = _get_default_config_path()
            # xxxxxxxxxxx?
            assert os.path.isabs(path)
            assert path.endswith("tool_providers.yaml")
        finally:
            os.chdir(original_cwd)


class TestDynamicImportExceptionHandlingFix:
    """xxxxxxxxxxxxxxxxxxxxxxxxxx3x?

    xxxx?
    - xxx ModuleNotFoundError / AttributeError / KeyError xxxxxx
    - xxxxxxx?name xxxxxxxxxxxxxxxxxx
    - xxxxxxxxxxxxxxxxxxxxxx?
    """

    def test_missing_module_field_logged_correctly(self, caplog):
        """xxxxxxx?module xxxxx?KeyError xxxxxxxxx"""
        import logging

        caplog.set_level(logging.ERROR)

        registry = ToolRegistry()
        registry.clear()

        mock_config_content = """
providers:
  - name: missing_module_tool
    function: test_func
    # xxx module xx
"""

        mock_file = unittest_mock_open(read_data=mock_config_content)
        with patch("builtins.open", mock_file):
            registry.register_from_config(config_path="mocked_path")

        # xxxxxxx missing_field xx
        assert any("tool_config_missing_field" in r.message for r in caplog.records)
        assert any("module" in r.message for r in caplog.records)

    def test_missing_function_field_logged_correctly(self, caplog):
        """xxxxxxx?function xxxxx?KeyError"""
        import logging

        caplog.set_level(logging.ERROR)

        registry = ToolRegistry()
        registry.clear()

        mock_config_content = """
providers:
  - name: missing_func_tool
    module: test.module
    # xxx function xx
"""

        mock_file = unittest_mock_open(read_data=mock_config_content)
        with patch("builtins.open", mock_file):
            registry.register_from_config(config_path="mocked_path")

        assert any("tool_config_missing_field" in r.message for r in caplog.records)
        assert any("function" in r.message for r in caplog.records)

    def test_missing_name_field_does_not_crash_logging(self, caplog):
        """xxxxxxx?name xxxxxxxxxxxxxxxxxxxxx?KeyError"""
        import logging

        caplog.set_level(logging.ERROR)

        registry = ToolRegistry()
        registry.clear()

        mock_config_content = """
providers:
  - module: test.module
    function: test_func
    # xxx name xx
"""

        mock_file = unittest_mock_open(read_data=mock_config_content)
        with patch("builtins.open", mock_file):
            # xxxxxxxxx
            registry.register_from_config(config_path="mocked_path")

        # xxx?missing_field xxxxool_name x?<unknown>
        assert any("tool_config_missing_field" in r.message for r in caplog.records)

    def test_module_not_found_does_not_block_others(self, caplog):
        """xxxxxxxxxxxxxxxxxxxxxxxxxx"""
        import logging

        caplog.set_level(logging.ERROR)

        registry = ToolRegistry()
        registry.clear()

        mock_config_content = """
providers:
  - name: nonexistent_module_tool
    module: nonexistent.module.xyz
    function: test_func
  - name: valid_tool_after_failure
    module: valid.module
    function: test_func
"""

        class _FakeValidModule:
            @staticmethod
            def test_func(x):
                """xxxxxx"""
                return x

        mock_file = unittest_mock_open(read_data=mock_config_content)

        # x?importlib x?nonexistent xxxx?ModuleNotFoundErrorxx valid xxxxxxxxxx?
        def _import_side_effect(module_name):
            if module_name == "nonexistent.module.xyz":
                raise ModuleNotFoundError(f"No module named '{module_name}'")
            return _FakeValidModule

        with (
            patch("builtins.open", mock_file),
            patch("importlib.import_module", side_effect=_import_side_effect),
        ):
            registry.register_from_config(config_path="mocked_path")

        # xxxxxxxxxxxx
        names = registry.list_registered_tools()
        assert "nonexistent_module_tool" not in names
        # xxxxxxxxxxxxxxxxxx?
        assert "valid_tool_after_failure" in names
        # xxxxxxx module_not_found xx
        assert any("tool_module_not_found" in r.message for r in caplog.records)

    def test_function_not_found_logged_correctly(self, caplog):
        """xxxxxxxxxxxxxxxxxxxxxx AttributeError"""
        import logging

        caplog.set_level(logging.ERROR)

        registry = ToolRegistry()
        registry.clear()

        mock_config_content = """
providers:
  - name: missing_func_tool
    module: existing.module
    function: nonexistent_function
"""

        class _FakeModuleWithoutFunc:
            """xxxxxxxxxxxxx?nonexistent_function"""

            pass

        mock_file = unittest_mock_open(read_data=mock_config_content)
        with (
            patch("builtins.open", mock_file),
            patch("importlib.import_module", return_value=_FakeModuleWithoutFunc),
        ):
            registry.register_from_config(config_path="mocked_path")

        assert any("tool_function_not_found" in r.message for r in caplog.records)
        assert any("nonexistent_function" in r.message for r in caplog.records)

    def test_register_summary_logged(self, caplog):
        """xxxxxxxxxxxxxxxxxxxsuccess / failed / totalx?"""
        import logging

        caplog.set_level(logging.INFO)

        registry = ToolRegistry()
        registry.clear()

        mock_config_content = """
providers:
  - name: summary_test_1
    module: test.module
    function: test_func
  - name: summary_test_2
    module: test.module
    function: test_func
"""

        class _FakeModule:
            @staticmethod
            def test_func(x):
                """xxx"""
                return x

        mock_file = unittest_mock_open(read_data=mock_config_content)
        with (
            patch("builtins.open", mock_file),
            patch("importlib.import_module", return_value=_FakeModule),
        ):
            registry.register_from_config(config_path="mocked_path")

        # xxxxxx?
        summary_logs = [r for r in caplog.records if "tools_config_register_summary" in r.message]
        assert len(summary_logs) == 1
        summary_msg = summary_logs[0].message
        assert "success" in summary_msg
        assert "failed" in summary_msg
        assert "total" in summary_msg

    def test_empty_config_logs_warning(self, caplog):
        """xxxxxxxxxxx WARNING xxxxxxxxx"""
        import logging

        caplog.set_level(logging.WARNING)

        registry = ToolRegistry()
        registry.clear()

        mock_config_content = ""
        mock_file = unittest_mock_open(read_data=mock_config_content)
        with patch("builtins.open", mock_file):
            registry.register_from_config(config_path="mocked_path")

        # xxxxxxxxxx WARNING
        assert any(
            "tools_config_empty_or_invalid" in r.message or "tools_config_no_providers" in r.message
            for r in caplog.records
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
