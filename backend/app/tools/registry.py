"""
全局工具注册中心
实现 ToolRegistry 单例，支持 MCP 服务启动时自动注册工具，Agent 通过能力名称动态获取工具集

变更说明（修复生产环境问题）：
1. 线程安全：单例创建使用双重检查锁（DCL），字典读写使用 RLock 保护
2. 配置路径：抽取 _resolve_config_path 共享函数，支持 TOOL_PROVIDERS_CONFIG 环境变量覆盖
3. 异常处理：细化动态导入的异常分类（ModuleNotFoundError / AttributeError / KeyError / 其他）
"""

import importlib
import os
import re
import threading
from collections.abc import Callable
from typing import Any

import yaml
from langchain_core.tools import StructuredTool, tool

from app.core.logging import get_logger

logger = get_logger(__name__)


# ============ 配置路径解析（共享函数，避免 DRY 违规）============
# 默认配置文件名
_DEFAULT_CONFIG_FILENAME = "tool_providers.yaml"
# 环境变量名：允许部署时自定义配置文件路径
_CONFIG_PATH_ENV_VAR = "TOOL_PROVIDERS_CONFIG"
_ENV_TEMPLATE_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand_env_template(value: Any) -> Any:
    """Expand ${VAR} and ${VAR:-default} in YAML string values."""
    if not isinstance(value, str):
        return value

    def replace(match: re.Match) -> str:
        name = match.group(1)
        default = match.group(2) if match.group(2) is not None else ""
        return os.getenv(name, default)

    return _ENV_TEMPLATE_RE.sub(replace, value)


def _get_default_config_path() -> str:
    """计算默认配置文件绝对路径。

    基于 __file__ 推导，避免依赖当前工作目录，
    保证在 Docker / 任意 cwd 启动时都能正确定位配置文件。
    """
    # backend/app/tools/registry.py → backend/config/tool_providers.yaml
    backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(backend_root, "config", _DEFAULT_CONFIG_FILENAME)


def _resolve_config_path(config_path: str | None) -> str:
    """解析配置文件路径，优先级：参数 > 环境变量 > 默认路径。

    Args:
        config_path: 调用方显式传入的路径，None 表示使用环境变量或默认值

    Returns:
        实际使用的配置文件绝对路径
    """
    if config_path:
        return config_path
    env_path = os.getenv(_CONFIG_PATH_ENV_VAR)
    if env_path:
        return env_path
    return _get_default_config_path()


class ToolRegistry:
    """全局工具注册中心单例（线程安全实现）

    线程安全保证：
    - 单例创建：双重检查锁（DCL）避免竞态创建多实例
    - 字典读写：RLock 保护 _tools / _capability_map 的并发访问
      使用 RLock 而非 Lock，因为 register_from_config 内部会调用 register，
      存在锁重入场景
    """

    _instance = None
    _singleton_lock = threading.Lock()  # 保护单例创建

    def __new__(cls):
        """单例模式实现（双重检查锁，线程安全）"""
        # 快速路径：无锁读取，命中则直接返回（CPython GIL 保证引用读取原子性）
        if cls._instance is not None:
            return cls._instance

        # 慢速路径：加锁后再次检查，避免竞态创建多实例
        with cls._singleton_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._tools = {}
                instance._capability_map = {}
                # RLock 允许同一线程内多次 acquire（register_from_config → register 重入）
                instance._data_lock = threading.RLock()
                cls._instance = instance
            return cls._instance

    def register(
        self,
        name: str,
        func: Callable,
        description: str = None,
        module_path: str = None,
        endpoint: str = None,
    ):
        """
        注册一个工具（线程安全）

        Args:
            name: 工具名称
            func: 工具函数或 StructuredTool 实例
            description: 工具描述
            module_path: 模块路径
            endpoint: 端点信息
        """
        # 如果 func 已经是 StructuredTool 实例，直接使用；否则用 @tool 包装
        if isinstance(func, StructuredTool):
            wrapped = func
        else:
            # 将 description 传入 tool()，避免无 docstring 函数在包装阶段抛 ValueError
            wrapped = tool(func, description=description)
            wrapped.name = name

        # 设置描述
        if description:
            wrapped.description = description

        # 加锁保护字典写入，避免与并发读取产生不一致视图
        with self._data_lock:
            self._tools[name] = {"tool": wrapped, "module_path": module_path, "endpoint": endpoint}

        tool_id = name  # 以工具名作为唯一标识，与 self._tools 的键一致
        logger.info("tool_registered", tool_name=name, tool_id=tool_id)

    def _register_tool_result(
        self,
        provider_name: str,
        result: Any,
        description: str | None = None,
        module_path: str | None = None,
        endpoint: str | None = None,
    ) -> list[str]:
        """Register one provider result, whether it is one tool or many tools."""
        if result is None:
            return []

        candidates = list(result) if isinstance(result, (list, tuple, set)) else [result]
        registered_names: list[str] = []

        for index, candidate in enumerate(candidates):
            if not candidate:
                continue

            if isinstance(candidate, StructuredTool):
                tool_name = getattr(candidate, "name", None) or provider_name
                self.register(
                    name=tool_name,
                    func=candidate,
                    description=description or getattr(candidate, "description", None),
                    module_path=module_path,
                    endpoint=endpoint,
                )
                registered_names.append(tool_name)
                continue

            if callable(candidate):
                tool_name = getattr(candidate, "name", None) or provider_name
                if len(candidates) > 1 and tool_name == provider_name:
                    tool_name = f"{provider_name}_{index + 1}"
                self.register(
                    name=tool_name,
                    func=candidate,
                    description=description or getattr(candidate, "description", None),
                    module_path=module_path,
                    endpoint=endpoint,
                )
                registered_names.append(tool_name)
                continue

            logger.warning(
                "tool_provider_result_not_callable",
                provider=provider_name,
                result_type=type(candidate).__name__,
            )

        return registered_names

    def register_from_config(self, config_path: str = None):
        """
        从 tool_providers.yaml 配置文件批量注册工具（线程安全 + 细化异常处理）。

        异常处理策略：
        - FileNotFoundError: 配置文件缺失，记 WARNING 后返回（不阻塞启动）
        - YAMLError: 配置文件格式错误，记 ERROR 后返回
        - ModuleNotFoundError: 模块不存在，跳过该工具继续处理下一个
        - AttributeError: 函数不存在，跳过该工具继续处理下一个
        - KeyError: 配置项缺少必需字段，跳过该工具继续处理下一个
        - 其他异常: 记录后跳过该工具，不影响其他工具注册

        Args:
            config_path: 配置文件路径，默认通过 _resolve_config_path 解析
        """
        resolved_path = _resolve_config_path(config_path)

        try:
            with open(resolved_path, encoding="utf-8") as f:
                config = yaml.safe_load(f)
        except FileNotFoundError:
            logger.warning("tools_config_not_found", path=resolved_path)
            return
        except yaml.YAMLError as e:
            logger.error("tools_config_parse_error", path=resolved_path, error=str(e))
            return
        except Exception as e:
            logger.error("tools_config_load_error", path=resolved_path, error=str(e))
            return

        if not config or not isinstance(config, dict):
            logger.warning("tools_config_empty_or_invalid", path=resolved_path)
            return

        providers = config.get("providers", [])
        if not providers:
            logger.warning("tools_config_no_providers", path=resolved_path)
            return

        success_count = 0
        fail_count = 0
        skipped_count = 0
        provider_tool_names: dict[str, list[str]] = {}
        capability_tool_names: dict[str, list[str]] = {}

        for tool_config in providers:
            # 防御性获取 name 字段，避免 KeyError 在日志记录时再次抛出
            tool_name = (
                tool_config.get("name", "<unknown>")
                if isinstance(tool_config, dict)
                else "<invalid>"
            )

            try:
                # 校验必需字段
                if not isinstance(tool_config, dict):
                    raise ValueError(
                        f"tool config must be a dict, got {type(tool_config).__name__}"
                    )
                if "name" not in tool_config:
                    raise KeyError("name")

                provider_type = tool_config.get("type", "local")

                if provider_type == "mcp_stdio":
                    logger.info("tool_config_skipped_runtime_provider", tool_name=tool_name)
                    skipped_count += 1
                    continue

                if provider_type == "http_endpoint":
                    if "url" not in tool_config:
                        raise KeyError("url")
                    try:
                        from app.services.tool_client import create_http_tool

                        endpoint_url = _expand_env_template(tool_config["url"])
                        http_tool = create_http_tool(
                            name=tool_config["name"],
                            description=tool_config.get("description")
                            or f"HTTP tool: {tool_config['name']}",
                            endpoint=endpoint_url,
                        )
                    except Exception as e:
                        logger.error(
                            "http_endpoint_tool_create_failed",
                            tool_name=tool_name,
                            endpoint=endpoint_url,
                            error=str(e),
                        )
                        fail_count += 1
                        continue

                    registered_names = self._register_tool_result(
                        provider_name=tool_config["name"],
                        result=http_tool,
                        description=tool_config.get("description"),
                        endpoint=endpoint_url,
                    )
                    success_count += len(registered_names)
                    provider_tool_names[tool_config["name"]] = registered_names
                    for capability in tool_config.get("capabilities", []):
                        capability_tool_names.setdefault(capability, []).extend(registered_names)
                    continue

                if provider_type != "local":
                    logger.error(
                        "tool_config_unknown_provider_type",
                        tool_name=tool_name,
                        provider_type=provider_type,
                    )
                    fail_count += 1
                    continue

                if "module" not in tool_config:
                    raise KeyError("module")
                if "function" not in tool_config:
                    raise KeyError("function")

                # 动态导入模块
                try:
                    module = importlib.import_module(tool_config["module"])
                except ModuleNotFoundError as e:
                    logger.error(
                        "tool_module_not_found",
                        tool_name=tool_name,
                        module=tool_config["module"],
                        error=str(e),
                    )
                    fail_count += 1
                    continue

                # 获取工具函数
                try:
                    func = getattr(module, tool_config["function"])
                except AttributeError as e:
                    logger.error(
                        "tool_function_not_found",
                        tool_name=tool_name,
                        module=tool_config["module"],
                        function=tool_config["function"],
                        error=str(e),
                    )
                    fail_count += 1
                    continue

                # 注册工具
                try:
                    if "agent_key" in tool_config:
                        provider_result = func(tool_config["agent_key"])
                    else:
                        try:
                            provider_result = func()
                        except TypeError:
                            provider_result = func
                except Exception as e:
                    logger.error(
                        "tool_provider_factory_failed",
                        tool_name=tool_name,
                        module=tool_config["module"],
                        function=tool_config["function"],
                        error=str(e),
                    )
                    fail_count += 1
                    continue

                registered_names = self._register_tool_result(
                    provider_name=tool_config["name"],
                    result=provider_result,
                    description=tool_config.get("description"),
                    module_path=tool_config["module"],
                    endpoint=tool_config.get("endpoint"),
                )
                if not registered_names:
                    logger.warning("tool_provider_registered_no_tools", tool_name=tool_name)
                success_count += len(registered_names)
                provider_tool_names[tool_config["name"]] = registered_names
                for capability in tool_config.get("capabilities", []):
                    capability_tool_names.setdefault(capability, []).extend(registered_names)

            except KeyError as e:
                logger.error(
                    "tool_config_missing_field",
                    tool_name=tool_name,
                    missing_field=str(e),
                    config=tool_config,
                )
                fail_count += 1
            except ValueError as e:
                logger.error("tool_config_invalid", tool_name=tool_name, error=str(e))
                fail_count += 1
            except Exception as e:
                # 兜底：未知异常不阻塞后续工具注册
                logger.exception("tool_register_config_error", tool_name=tool_name, error=str(e))
                fail_count += 1

        for capability, configured_names in (config.get("capability_map") or {}).items():
            expanded_names: list[str] = []
            for configured_name in configured_names or []:
                if configured_name in provider_tool_names:
                    expanded_names.extend(provider_tool_names[configured_name])
                elif configured_name in self._tools:
                    expanded_names.append(configured_name)
            if expanded_names:
                capability_tool_names.setdefault(capability, []).extend(expanded_names)

        for capability, names in capability_tool_names.items():
            unique_names = list(dict.fromkeys(names))
            if unique_names:
                self.map_capability_to_tools(capability, unique_names)

        logger.info(
            "tools_config_register_summary",
            path=resolved_path,
            success=success_count,
            failed=fail_count,
            skipped=skipped_count,
            total=len(providers),
        )

    def get_tools_by_names(self, names: list[str]) -> list[Any]:
        """
        根据工具名列表返回工具对象列表（线程安全）

        Args:
            names: 工具名称列表

        Returns:
            工具对象列表
        """
        tools = []
        with self._data_lock:
            for name in names:
                if name in self._tools:
                    tools.append(self._tools[name]["tool"])
                else:
                    logger.warning("tool_not_found", tool_name=name)
        return tools

    def map_capability_to_tools(self, capability: str, tool_names: list[str]):
        """
        将一个能力名称映射到一组工具名（线程安全）

        Args:
            capability: 能力名称
            tool_names: 工具名称列表
        """
        with self._data_lock:
            self._capability_map[capability] = tool_names
        logger.info("capability_mapped", capability=capability, tools=tool_names)

    def get_tools_by_capabilities(self, capabilities: list[str]) -> list[Any]:
        """
        根据能力名称列表返回工具对象列表（线程安全）

        Args:
            capabilities: 能力名称列表

        Returns:
            工具对象列表
        """
        tool_names = set()
        with self._data_lock:
            for cap in capabilities:
                if cap in self._capability_map:
                    tool_names.update(self._capability_map[cap])

        return self.get_tools_by_names(list(tool_names))

    def list_registered_tools(self) -> list[str]:
        """
        列出所有已注册的工具名（线程安全快照）

        Returns:
            工具名称列表
        """
        with self._data_lock:
            return list(self._tools.keys())

    def get_tool_info(self, name: str) -> dict[str, Any]:
        """
        获取工具详细信息（线程安全）

        Args:
            name: 工具名称

        Returns:
            工具信息字典
        """
        with self._data_lock:
            return self._tools.get(name, {})

    def initialize_from_config(self):
        """
        从配置文件初始化所有工具
        """
        logger.info("tool_registry_initializing_from_config")
        self.register_from_config()

        with self._data_lock:
            has_configured_capabilities = bool(self._capability_map)

        if not has_configured_capabilities:
            self.map_capability_to_tools("search", ["search_kols", "search_douyin"])
            self.map_capability_to_tools("analysis", ["analyze_performance", "generate_report"])
            self.map_capability_to_tools("content", ["create_content", "edit_content"])

        logger.info("tool_registry_initialized", tool_count=len(self.list_registered_tools()))

    def clear(self):
        """清空注册表状态（主要用于测试隔离）。

        生产代码不应调用此方法。线程安全地重置内部字典，
        避免测试 fixture 中直接操作私有字段破坏锁语义。
        """
        with self._data_lock:
            self._tools.clear()
            self._capability_map.clear()


# 创建全局单例实例
registry = ToolRegistry()
