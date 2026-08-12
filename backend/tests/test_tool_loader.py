"""
ToolLoader 回归测试
验证「模式识别三问法」发现的 3 个问题的修复：
1. _enhance_tool_description 改为 async，避免同步 LLM 调用阻塞事件循环
2. _load_config 失败时返回 False，_loaded 保持 False 可重试
3. Schema 缓存返回列表副本，避免调用方修改污染缓存
"""

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.tools.loader import ToolLoadContext, ToolLoader, _ProviderMeta


class TestEnhanceDescriptionAsync:
    """修复1：_enhance_tool_description 必须是 async，否则会在 async 路径里同步阻塞 LLM 调用"""

    def test_enhance_is_coroutine_function(self):
        """_enhance_tool_description 应为协程函数"""
        assert asyncio.iscoroutinefunction(ToolLoader._enhance_tool_description), (
            "_enhance_tool_description 必须是 async def —— "
            "它在 _load_mcp_stdio(async) 里被调用，内部 llm.invoke 是同步阻塞调用，"
            "不改成 async + asyncio.to_thread 会卡死整个事件循环"
        )


class TestConfigLoadRetryable:
    """修复2：配置加载失败时 _loaded 保持 False，下次调用 load 会重试"""

    def test_load_config_returns_false_when_file_missing(self):
        """配置文件不存在时 _load_config 返回 False（而非隐式 return None）"""
        loader = ToolLoader(config_path="/nonexistent/path/to/tool_providers.yaml")
        result = loader._load_config()
        assert result is False

    def test_load_config_returns_false_when_empty_file(self):
        """配置文件为空时 _load_config 返回 False（防御 yaml.safe_load 返回 None 后 .get 报错）"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("")  # 空文件 → safe_load 返回 None
            empty_path = f.name
        try:
            loader = ToolLoader(config_path=empty_path)
            result = loader._load_config()
            assert result is False
        finally:
            os.unlink(empty_path)

    def test_loaded_stays_false_after_failed_config(self):
        """配置加载失败后 _loaded 保持 False，下次 load 会重试（不会被永久标记为已加载）"""
        loader = ToolLoader(config_path="/nonexistent/path/to/tool_providers.yaml")
        ctx = ToolLoadContext(company_id="c1", agent_name="a1", trace_id="t1")
        # 第一次 load：配置加载失败
        asyncio.run(loader.load(ctx))
        assert loader._loaded is False, "配置加载失败后 _loaded 不应被设为 True，否则永远无法重试"

    def test_load_config_returns_true_on_valid_yaml(self):
        """正常 YAML 配置返回 True（确保修复没有破坏正常路径）"""
        yaml_content = """
providers:
  - name: test_provider
    type: local
    module: app.tools.registry
    function: list_registered_tools
    capabilities: [test]
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(yaml_content)
            valid_path = f.name
        try:
            loader = ToolLoader(config_path=valid_path)
            result = loader._load_config()
            assert result is True
            assert len(loader._providers) == 1
            assert loader._providers[0].name == "test_provider"
        finally:
            os.unlink(valid_path)


class TestSchemaCacheIsolation:
    """修复3：Schema 缓存返回列表副本，调用方修改不污染缓存"""

    def test_cache_returns_copy_not_reference(self):
        """缓存命中时返回列表副本，修改返回值不影响缓存原始数据"""
        loader = ToolLoader(config_path="/nonexistent/path.yaml")
        # 模拟缓存已有数据
        cached_tools = ["tool_a", "tool_b"]
        loader._schema_cache["fake_provider"] = cached_tools

        provider = _ProviderMeta(name="fake_provider", type="mcp_stdio", command="fake")
        ctx = ToolLoadContext(company_id="c1", agent_name="a1", trace_id="t1")

        # 命中缓存路径返回
        returned = asyncio.run(loader._load_mcp_stdio(provider, ctx))

        # 返回的应该是副本
        assert returned == ["tool_a", "tool_b"]
        assert returned is not cached_tools, "应返回副本而非同一个列表对象"

        # 修改返回的列表
        returned.append("polluted")
        returned.clear()

        # 验证缓存未被污染
        assert loader._schema_cache["fake_provider"] == ["tool_a", "tool_b"], (
            "调用方修改返回值不应污染缓存"
        )


class TestEnhanceDescriptionNoBlocking:
    """修复1 补充：_enhance_tool_description 内部 LLM 调用不阻塞事件循环

    通过 mock 验证调用链：llm.invoke 被包装在 asyncio.to_thread 中执行
    """

    def test_enhance_uses_thread_pool_not_direct_invoke(self):
        """_enhance_tool_description 调用时，LLM invoke 应通过线程池执行而非直接同步调用"""
        loader = ToolLoader(config_path="/nonexistent/path.yaml")

        # 构造一个假的 tool 对象
        class FakeTool:
            name = "fake_tool"
            description = "short"  # 故意短，触发增强逻辑
            args_schema = None

        class FakeResponse:
            content = "这是一个增强后的工具描述，长度超过二十个字符，用于测试"

        class FakeLLM:
            # 用类变量记录，避免 _enhance_tool_description 内部
            # 通过 ModelGateway() 新建实例导致测试持有的是另一个对象
            invoked_in_main_thread = None

            def invoke(self, prompt):
                # 记录调用时是否在主线程（事件循环线程）
                import threading

                FakeLLM.invoked_in_main_thread = (
                    threading.current_thread() is threading.main_thread()
                )
                return FakeResponse()

        class FakeModelGateway:
            def get_llm(self, *args, **kwargs):
                return FakeLLM()

        fake_tool = FakeTool()

        # 用 monkeypatch 替换 import
        import sys as _sys
        import types

        fake_module = types.ModuleType("app.services.model_gateway")
        fake_module.ModelGateway = FakeModelGateway
        original_module = _sys.modules.get("app.services.model_gateway")
        _sys.modules["app.services.model_gateway"] = fake_module

        try:
            # 在事件循环中运行 _enhance_tool_description
            asyncio.run(loader._enhance_tool_description(fake_tool))
            # 验证 llm.invoke 在非主线程执行（即通过 asyncio.to_thread 转入线程池）
            assert FakeLLM.invoked_in_main_thread is False, (
                "llm.invoke 应该通过 asyncio.to_thread 在线程池执行，"
                "而不是在主线程（事件循环线程）同步阻塞"
            )
        finally:
            if original_module is not None:
                _sys.modules["app.services.model_gateway"] = original_module
            else:
                _sys.modules.pop("app.services.model_gateway", None)

    def test_eval_mode_skips_llm_enhancement(self, monkeypatch):
        """Evaluation mode must not call the LLM while loading tool schemas."""
        monkeypatch.setenv("AGENT_EVAL_MODE", "1")
        monkeypatch.setenv("TOOL_DESCRIPTION_AUTO_ENHANCE", "0")
        loader = ToolLoader(config_path="/nonexistent/path.yaml")

        class FakeTool:
            name = "fake_tool"
            description = "short"
            args_schema = None

        class ForbiddenModelGateway:
            def __init__(self, *args, **kwargs):
                raise AssertionError("ModelGateway must not be created in eval mode")

        import sys as _sys
        import types

        fake_module = types.ModuleType("app.services.model_gateway")
        fake_module.ModelGateway = ForbiddenModelGateway
        monkeypatch.setitem(_sys.modules, "app.services.model_gateway", fake_module)

        assert asyncio.run(loader._enhance_tool_description(FakeTool())) is False

    def test_eval_mode_skips_mcp_stdio_startup(self, monkeypatch):
        """Offline evaluation must not start stdio MCP subprocesses."""
        monkeypatch.setenv("AGENT_EVAL_MODE", "1")
        loader = ToolLoader(config_path="/nonexistent/path.yaml")
        provider = _ProviderMeta(
            name="knowledge_retrieval",
            type="mcp_stdio",
            command="python",
            args=["-m", "app.mcp_servers.knowledge_retrieval_server"],
            capabilities=["customer_service"],
        )
        ctx = ToolLoadContext(
            company_id="c1",
            agent_name="customer_service",
            trace_id="t1",
            capabilities=["customer_service"],
        )

        monkeypatch.setattr(loader, "_fallback_to_registry", lambda p, ctx=None: ["fallback_tool"])

        tools = asyncio.run(loader._load_provider(provider, ctx))

        assert tools == ["fallback_tool"]
        assert loader._mcp_client_pool == {}


class TestSingletonThreadSafety:
    """修复4：get_tool_loader 双重检查锁，线程安全"""

    def setup_method(self):
        # 每个测试前重置全局单例，避免测试间状态污染
        import app.tools.loader as loader_mod

        self._loader_mod = loader_mod
        self._original = loader_mod._tool_loader
        loader_mod._tool_loader = None

    def teardown_method(self):
        self._loader_mod._tool_loader = self._original

    def test_singleton_returns_same_instance(self):
        """多次调用返回同一实例"""
        from app.tools.loader import get_tool_loader

        a = get_tool_loader()
        b = get_tool_loader()
        assert a is b

    def test_concurrent_creation_is_thread_safe(self):
        """10 个线程并发调用 get_tool_loader，应只创建一个实例"""
        import threading

        from app.tools.loader import get_tool_loader

        instances = []
        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()  # 所有线程同时放行，最大化竞态
            instances.append(get_tool_loader())

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(instances) == 10
        # 所有线程拿到的必须是同一个实例
        assert all(i is instances[0] for i in instances), (
            "并发调用 get_tool_loader 不应创建多个实例"
        )


class TestConfigPathEnvVar:
    """修复6：配置路径支持 TOOL_PROVIDERS_CONFIG 环境变量"""

    def test_env_var_overrides_default(self, monkeypatch):
        """设置了环境变量时，优先用环境变量的路径"""
        monkeypatch.setenv("TOOL_PROVIDERS_CONFIG", "/custom/env/path.yaml")
        loader = ToolLoader()
        assert loader.config_path == "/custom/env/path.yaml"

    def test_explicit_path_takes_priority_over_env(self, monkeypatch):
        """显式传参 > 环境变量"""
        monkeypatch.setenv("TOOL_PROVIDERS_CONFIG", "/env/path.yaml")
        loader = ToolLoader(config_path="/explicit/path.yaml")
        assert loader.config_path == "/explicit/path.yaml"

    def test_default_path_when_no_override(self, monkeypatch):
        """没设环境变量时，用默认相对路径（向后兼容）"""
        monkeypatch.delenv("TOOL_PROVIDERS_CONFIG", raising=False)
        loader = ToolLoader()
        assert loader.config_path.endswith("tool_providers.yaml")


class TestHttpEndpointTenantContext:
    """HTTP endpoint tools must receive tenant context from ToolLoadContext."""

    def test_http_endpoint_loader_binds_company_id(self, monkeypatch):
        import app.services.tool_client as tool_client

        captured = {}

        class FakeTool:
            metadata = None

        def fake_create_http_tool(**kwargs):
            captured.update(kwargs)
            return FakeTool()

        monkeypatch.setattr(tool_client, "create_http_tool", fake_create_http_tool)

        loader = ToolLoader(config_path="/nonexistent/path.yaml")
        provider = _ProviderMeta(
            name="search_kols",
            type="http_endpoint",
            url="http://kol-search:8101/tools/search_kols",
        )
        ctx = ToolLoadContext(company_id="239", agent_name="brand_bd", trace_id="t1")

        tools = asyncio.run(loader._load_provider(provider, ctx))

        assert len(tools) == 1
        assert captured["default_params"] == {"company_id": "239"}
        assert tools[0].metadata["endpoint"] == "http://kol-search:8101/tools/search_kols"

    def test_http_tool_bound_company_id_overrides_llm_param(self, monkeypatch):
        import app.services.tool_client as tool_client

        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"status": "ok"}

        class FakeClient:
            def __init__(self, timeout):
                self.timeout = timeout

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def post(self, endpoint, json):
                captured["endpoint"] = endpoint
                captured["json"] = json
                return FakeResponse()

        monkeypatch.setattr(tool_client.httpx, "Client", FakeClient)

        http_tool = tool_client.create_http_tool(
            name="search_kols",
            description="Search KOLs",
            endpoint="http://kol-search:8101/tools/search_kols",
            default_params={"company_id": "239"},
        )

        result = http_tool.func(category="beauty", company_id="wrong-company")

        assert result == {"status": "ok"}
        assert captured["endpoint"] == "http://kol-search:8101/tools/search_kols"
        assert captured["json"] == {"category": "beauty", "company_id": "239"}

    def test_registry_fallback_rebinds_http_tool_company_id(self, monkeypatch):
        import app.services.tool_client as tool_client
        import app.tools.registry as registry_mod

        captured = {}

        class RegistryHttpTool:
            name = "search_kols"
            description = "Search KOLs"
            metadata = {"endpoint": "http://kol-search:8101/tools/search_kols"}

        class FakeRegistry:
            def list_registered_tools(self):
                return ["search_kols"]

            def get_tools_by_names(self, names):
                assert names == ["search_kols"]
                return [RegistryHttpTool()]

        class FakeBoundTool:
            metadata = None

        def fake_create_http_tool(**kwargs):
            captured.update(kwargs)
            return FakeBoundTool()

        monkeypatch.setattr(registry_mod, "registry", FakeRegistry())
        monkeypatch.setattr(tool_client, "create_http_tool", fake_create_http_tool)

        loader = ToolLoader(config_path="/nonexistent/path.yaml")
        provider = _ProviderMeta(name="search", type="mcp_stdio", command="fake")
        ctx = ToolLoadContext(company_id="239", agent_name="brand_bd", trace_id="t1")

        tools = loader._fallback_to_registry(provider, ctx)

        assert len(tools) == 1
        assert captured["name"] == "search_kols"
        assert captured["endpoint"] == "http://kol-search:8101/tools/search_kols"
        assert captured["default_params"] == {"company_id": "239"}
        assert tools[0].metadata == {"endpoint": "http://kol-search:8101/tools/search_kols"}


class TestFallbackTokenMatch:
    """修复8：fallback 按 token 精确匹配，避免子字符串误匹配"""

    def test_search_does_not_match_research_tool(self):
        """provider.name='search' 应匹配 'search_kols'，不应匹配 'research_tool'"""
        from unittest.mock import MagicMock, patch

        loader = ToolLoader(config_path="/nonexistent/path.yaml")

        mock_registry = MagicMock()
        mock_registry.list_registered_tools.return_value = [
            "research_tool",
            "search_kols",
            "data_analyzer",
        ]
        mock_registry.get_tools_by_names.return_value = []

        with patch("app.tools.registry.registry", mock_registry):
            provider = _ProviderMeta(name="search", type="mcp_stdio", command="fake")
            loader._fallback_to_registry(provider)

        # 检查传给 get_tools_by_names 的工具名列表
        called_names = mock_registry.get_tools_by_names.call_args[0][0]
        assert "search_kols" in called_names, "'search' 应匹配 'search_kols'"
        assert "research_tool" not in called_names, (
            "'search' 不应误匹配 'research_tool'（子字符串误匹配 bug）"
        )
        assert "data_analyzer" not in called_names

    def test_multi_token_provider_matches_shared_token(self):
        """provider.name='search_douyin' 应匹配含 'search' 或 'douyin' 的工具"""
        from unittest.mock import MagicMock, patch

        loader = ToolLoader(config_path="/nonexistent/path.yaml")

        mock_registry = MagicMock()
        mock_registry.list_registered_tools.return_value = [
            "search_kols",
            "douyin_analytics",
            "data_analyzer",
        ]
        mock_registry.get_tools_by_names.return_value = []

        with patch("app.tools.registry.registry", mock_registry):
            provider = _ProviderMeta(name="search_douyin", type="mcp_stdio", command="fake")
            loader._fallback_to_registry(provider)

        called_names = mock_registry.get_tools_by_names.call_args[0][0]
        assert "search_kols" in called_names
        assert "douyin_analytics" in called_names
        assert "data_analyzer" not in called_names

    def test_no_match_falls_back_to_all(self):
        """完全无匹配时，fallback 到全部工具（保留原兜底行为）"""
        from unittest.mock import MagicMock, patch

        loader = ToolLoader(config_path="/nonexistent/path.yaml")

        mock_registry = MagicMock()
        mock_registry.list_registered_tools.return_value = ["tool_a", "tool_b"]
        mock_registry.get_tools_by_names.return_value = []

        with patch("app.tools.registry.registry", mock_registry):
            provider = _ProviderMeta(name="nonexistent_xyz", type="mcp_stdio", command="fake")
            loader._fallback_to_registry(provider)

        called_names = mock_registry.get_tools_by_names.call_args[0][0]
        assert called_names == ["tool_a", "tool_b"]  # fallback 到全部
