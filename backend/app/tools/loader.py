"""
ToolLoader - 统一的工具加载器
替代 agent.py 中分散的 4 个加载函数，提供单一的工具加载入口。

支持三种 provider 类型:
  - mcp_stdio: 通过 MultiServerMCPClient 连接 stdio MCP 服务器
  - local: 通过 importlib 导入本地 Python 模块
  - http_endpoint: 通过 HTTP 调用外部工具服务

加载链:
  load() → _filter_by_capabilities() → _load_provider() → [mcp_stdio | local | http_endpoint]
  失败时: _load_mcp_stdio() → _fallback_to_registry()
"""

import asyncio
import importlib
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any

import yaml

from app.core.logging import get_logger

logger = get_logger(__name__)

# 工具描述最小长度阈值（字符）
MIN_DESCRIPTION_LENGTH = 20
# 工具描述质量评分阈值（满分 100）
MIN_DESCRIPTION_SCORE = 60
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TOOL_DESCRIPTION_AUTO_ENHANCE_ENV = "TOOL_DESCRIPTION_AUTO_ENHANCE"
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


def _agent_eval_mode_enabled() -> bool:
    """Return whether the current process is running offline Agent evaluation."""
    return os.getenv("AGENT_EVAL_MODE", "").lower() in {"1", "true", "yes", "on"}


def _tool_description_auto_enhance_enabled() -> bool:
    """Return whether ToolLoader may call an LLM to enrich tool descriptions."""
    if _agent_eval_mode_enabled():
        return False
    value = os.getenv(TOOL_DESCRIPTION_AUTO_ENHANCE_ENV)
    if value is None:
        return True
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _build_stdio_env(company_id: str = "", trace_id: str = "") -> dict[str, str]:
    """Build an MCP stdio subprocess environment that can import backend/app."""
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    pythonpath_parts = [BACKEND_DIR]
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    env.setdefault("FASTMCP_SHOW_SERVER_BANNER", "false")
    env.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")
    env.setdefault("FASTMCP_LOG_LEVEL", "ERROR")
    env.setdefault("FASTMCP_ENABLE_RICH_LOGGING", "false")
    env.setdefault("FASTMCP_ENABLE_RICH_TRACEBACKS", "false")
    env.setdefault("LOG_TO_STDERR", "true")
    env.setdefault("LOG_LEVEL", "ERROR")
    if company_id:
        env["AGENTX_COMPANY_ID"] = company_id
    if trace_id:
        env["AGENTX_TRACE_ID"] = trace_id
    return env


@dataclass
class ToolLoadContext:
    """工具加载的全局上下文 - 携带租户身份和 trace"""

    company_id: str
    agent_name: str
    trace_id: str
    capabilities: list[str] | None = None


@dataclass
class _ProviderMeta:
    """Provider 元数据（内部使用）"""

    name: str
    type: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    module: str = ""
    function: str = ""
    agent_key: str = ""
    url: str = ""
    timeout_ms: int = 30000
    retry: dict = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=list)
    danger_level: str = "low"
    multi_tenant: bool = False
    tools_requiring_approval: list[str] = field(default_factory=list)
    # 降级配置
    degradation: dict = field(
        default_factory=dict
    )  # {critical, cache_ttl, fallback_url, fallback_tool}


class ToolLoader:
    """唯一的工具加载器 - 三种 provider 类型，一条降级链"""

    DEFAULT_CONFIG_PATH = os.path.join(
        os.path.dirname(__file__), "..", "..", "config", "tool_providers.yaml"
    )

    def __init__(self, config_path: str = None):
        # 优先级：显式传参 > 环境变量 TOOL_PROVIDERS_CONFIG > 默认相对路径
        self.config_path = (
            config_path or os.environ.get("TOOL_PROVIDERS_CONFIG") or self.DEFAULT_CONFIG_PATH
        )
        self._providers: list[_ProviderMeta] = []
        self._loaded = False
        self._schema_cache: dict[tuple[str, str], list] = {}
        # MCP 进程环境包含租户身份，因此连接和工具 schema 都必须按租户隔离。
        self._mcp_client_pool: dict[tuple[str, str], Any] = {}
        # MCP 健康状态: {provider_name: bool}
        self._mcp_health: dict[str, bool] = {}

    # ── 公共入口 ────────────────────────────────────────

    async def load(self, ctx: ToolLoadContext) -> list:
        """
        唯一对外入口。按 context 中的 capabilities 过滤 provider。
        内部按 type 分类调用对应的加载方法。

        Args:
            ctx: 工具加载上下文（company_id, agent_name, trace_id, capabilities）

        Returns:
            合并后的工具列表
        """
        if not self._loaded:
            # 配置加载成功才标记为已加载，失败时保留 False 以便下次重试
            if self._load_config():
                self._loaded = True
            else:
                logger.warning(
                    "tool_loader_config_not_loaded_will_retry", config_path=self.config_path
                )

        providers = self._filter_by_capabilities(ctx.capabilities)
        if not providers:
            logger.warning("tool_loader_no_providers_matched", capabilities=ctx.capabilities)
            return []

        all_tools = []
        for p in providers:
            tools = await self._load_provider(p, ctx)
            if tools:
                all_tools.extend(tools)

        logger.info(
            "tool_loader_complete",
            total=len(all_tools),
            provider_count=len(providers),
            capabilities=ctx.capabilities,
        )
        return all_tools

    # ── 工具描述校验与增强 ──────────────────────────────

    def _validate_tool_description(self, tool: Any, provider_name: str) -> tuple[bool, str]:
        """
        校验工具描述质量。
        五原则评分: 命名(20) + 描述(30) + 参数(20) + 错误处理(15) + 职责(15)

        Returns:
            (is_valid, reason): 是否通过校验 + 原因
        """
        desc = getattr(tool, "description", "") or ""
        name = getattr(tool, "name", "") or ""

        score = 0
        issues = []

        # 1. 命名清晰度 (20)
        if name and len(name) >= 3:
            score += 20
        else:
            issues.append(f"tool name too short: '{name}'")

        # 2. 描述质量 (30)
        if len(desc) >= MIN_DESCRIPTION_LENGTH:
            has_purpose = any(
                kw in desc.lower() for kw in ["purpose", "用途", "return", "返回", "arg", "param"]
            )
            if has_purpose:
                score += 30
            else:
                score += 15
                issues.append("description missing Purpose/Parameters/Returns sections")
        else:
            issues.append(f"description too short ({len(desc)} chars < {MIN_DESCRIPTION_LENGTH})")

        # 3. 参数说明 (20)
        if hasattr(tool, "args_schema") and tool.args_schema:
            score += 20
        elif any(kw in desc for kw in ["Args:", "Parameters:", "参数:", "输入:"]):
            score += 15
        else:
            issues.append("no parameter descriptions found")

        # 4. 错误处理 (15) - 检查是否有 error/exception 相关描述
        if any(
            kw in desc.lower() for kw in ["error", "exception", "throw", "raise", "错误", "异常"]
        ):
            score += 15
        else:
            score += 5

        # 5. 职责单一性 (15) - 检查描述是否涵盖多个不相关功能
        if len(desc) < 500:
            score += 15
        else:
            score += 5

        is_valid = score >= MIN_DESCRIPTION_SCORE
        reason = f"score={score}/100" + (f"; issues: {'; '.join(issues)}" if issues else "")
        return is_valid, reason

    async def _enhance_tool_description(self, tool: Any) -> bool:
        """
        使用 LLM 自动增强工具描述。
        基于函数签名和参数名生成标准化的描述。

        Returns:
            True if enhanced successfully

        Note:
            本方法被 _load_mcp_stdio (async) 调用，内部 LLM 调用通过
            asyncio.to_thread 转入线程池执行，避免阻塞事件循环。
        """
        if not _tool_description_auto_enhance_enabled():
            logger.info(
                "tool_description_enhance_skipped",
                tool=getattr(tool, "name", "unknown"),
                reason="disabled_by_env",
            )
            return False

        try:
            from app.services.model_gateway import ModelGateway

            name = getattr(tool, "name", "unknown")
            desc = getattr(tool, "description", "") or ""
            args_schema = getattr(tool, "args_schema", None)

            # 提取参数信息
            params_info = ""
            if args_schema and hasattr(args_schema, "__fields__"):
                for field_name, field_info in args_schema.__fields__.items():
                    field_desc = getattr(field_info, "description", "") or ""
                    field_type = str(getattr(field_info, "outer_type_", "Any"))
                    params_info += f"  - {field_name} ({field_type}): {field_desc}\n"

            model_gateway = ModelGateway()
            llm = model_gateway.get_llm("deepseek")

            prompt = f"""你是一个工具文档专家。请为以下 MCP 工具生成标准化的 docstring 描述。

工具名称: {name}
当前描述: {desc if desc else "(无)"}
参数信息:
{params_info if params_info else "(无参数信息)"}

请生成标准的 docstring，包含以下部分:
1. Purpose: 工具用途（一句话）
2. Parameters: 参数说明
3. Returns: 返回值说明
4. Example: 使用示例

要求:
- 简洁明了，总长度不超过 300 字符
- 只返回描述文本，不要包含代码块标记"""
            # 同步 LLM 调用通过线程池执行，避免阻塞 async 事件循环
            response = await asyncio.to_thread(llm.invoke, prompt)
            enhanced = response.content.strip()

            if enhanced and len(enhanced) > MIN_DESCRIPTION_LENGTH:
                tool.description = enhanced
                logger.info(
                    "tool_description_enhanced", tool=name, old_len=len(desc), new_len=len(enhanced)
                )
                return True
            return False
        except Exception as e:
            logger.warning(
                "tool_description_enhance_failed",
                tool=getattr(tool, "name", "unknown"),
                error=str(e),
            )
            return False

    # ── 配置加载 ────────────────────────────────────────

    def _load_config(self) -> bool:
        """从 tool_providers.yaml 加载所有 provider。成功返回 True，失败返回 False。"""
        try:
            with open(self.config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f)
        except FileNotFoundError:
            logger.warning("tool_providers_config_not_found", path=self.config_path)
            return False
        except Exception as e:
            logger.error("tool_providers_config_load_error", error=str(e))
            return False

        # 防御：YAML 文件为空时 safe_load 返回 None，后续 .get 会抛 AttributeError
        if not config:
            logger.warning("tool_providers_config_empty", path=self.config_path)
            return False

        for entry in config.get("providers", []):
            try:
                degradation = dict(entry.get("degradation", {}))
                if degradation.get("fallback_url"):
                    degradation["fallback_url"] = _expand_env_template(degradation["fallback_url"])

                meta = _ProviderMeta(
                    name=entry["name"],
                    type=entry["type"],
                    command=entry.get("command", ""),
                    args=entry.get("args", []),
                    module=entry.get("module", ""),
                    function=entry.get("function", ""),
                    agent_key=entry.get("agent_key", ""),
                    url=_expand_env_template(entry.get("url", "")),
                    timeout_ms=entry.get("timeout_ms", 30000),
                    retry=entry.get("retry", {}),
                    capabilities=entry.get("capabilities", []),
                    danger_level=entry.get("danger_level", "low"),
                    multi_tenant=entry.get("multi_tenant", False),
                    tools_requiring_approval=entry.get("tools_requiring_approval", []),
                    degradation=degradation,
                )
                self._providers.append(meta)
            except KeyError as e:
                logger.warning(
                    "tool_provider_missing_field",
                    provider=entry.get("name", "unknown"),
                    missing=str(e),
                )

        logger.info("tool_providers_loaded", count=len(self._providers))
        return True

    def _filter_by_capabilities(self, capabilities: list[str] | None) -> list[_ProviderMeta]:
        """按 capabilities 过滤 provider（OR 逻辑）"""
        if not capabilities:
            return list(self._providers)

        matched = []
        for p in self._providers:
            if any(c in p.capabilities for c in capabilities):
                matched.append(p)

        if not matched:
            logger.warning("no_providers_matched_capabilities", requested=capabilities)

        return matched

    # ── Provider 加载分发 ──────────────────────────────

    async def _load_provider(self, provider: _ProviderMeta, ctx: ToolLoadContext) -> list:
        """按 provider.type 分发到对应的加载方法"""
        try:
            if provider.type == "mcp_stdio":
                if _agent_eval_mode_enabled():
                    logger.info(
                        "mcp_stdio_skipped_in_eval_mode",
                        provider=provider.name,
                        capabilities=ctx.capabilities,
                    )
                    return self._fallback_to_registry(provider, ctx)
                return await self._load_mcp_stdio(provider, ctx)
            elif provider.type == "local":
                return self._load_local(provider)
            elif provider.type == "http_endpoint":
                return self._load_http_endpoint(provider, ctx)
            else:
                logger.warning("unknown_provider_type", provider=provider.name, type=provider.type)
                return []
        except Exception as e:
            logger.warning("provider_load_failed", provider=provider.name, error=str(e))
            return []

    # ── MCP stdio 加载 ─────────────────────────────────

    async def _load_mcp_stdio(self, provider: _ProviderMeta, ctx: ToolLoadContext) -> list:
        """
        通过 MultiServerMCPClient 加载 stdio MCP 服务器工具。
        使用连接池复用连接，避免重复创建 stdio 进程。

        multi_tenant=true 时自动注入 X-Company-Id 和 X-Trace-Id header。
        """
        name = provider.name
        cache_key = (name, str(ctx.company_id or ""))

        # Schema 缓存
        if cache_key in self._schema_cache:
            logger.debug("tool_schema_cache_hit", provider=name, company_id=ctx.company_id)
            # 返回列表浅拷贝，避免调用方 append/clear 污染缓存
            return list(self._schema_cache[cache_key])

        # 构建 client 配置
        client_config = {
            name: {
                "transport": "stdio",
                "command": provider.command,
                "args": provider.args,
                "env": _build_stdio_env(ctx.company_id, ctx.trace_id),
                "cwd": BACKEND_DIR,
            }
        }

        # stdio transport does not support HTTP headers; pass tenant identity via env.
        if provider.multi_tenant:
            logger.info("mcp_tenant_identity_injected", provider=name, company_id=ctx.company_id)

        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient

            # 连接池复用
            if cache_key in self._mcp_client_pool:
                client = self._mcp_client_pool[cache_key]
                logger.debug("mcp_client_pool_hit", provider=name, company_id=ctx.company_id)
            else:
                client = MultiServerMCPClient(client_config)
                self._mcp_client_pool[cache_key] = client
                logger.info("mcp_client_pool_created", provider=name, company_id=ctx.company_id)

            tools = await client.get_tools()

            # 健康检查：标记为健康
            self._mcp_health[name] = True

            # Attach provider metadata to tools
            for t in tools:
                if not hasattr(t, "metadata") or t.metadata is None:
                    t.metadata = {}
                t.metadata["provider_name"] = name
                t.metadata["danger_level"] = provider.danger_level
                t.metadata["timeout_ms"] = provider.timeout_ms
                t.metadata["degradation"] = provider.degradation
                if provider.tools_requiring_approval:
                    t.metadata["requires_approval"] = t.name in provider.tools_requiring_approval
                else:
                    t.metadata["requires_approval"] = False

                # 工具描述校验与增强
                is_valid, reason = self._validate_tool_description(t, name)
                if not is_valid:
                    logger.warning(
                        "tool_description_validation_failed",
                        tool=t.name,
                        provider=name,
                        reason=reason,
                    )
                    # 低于阈值时自动增强描述（async，不阻塞事件循环）
                    await self._enhance_tool_description(t)

            # 缓存
            self._schema_cache[cache_key] = tools
            logger.info("mcp_tools_loaded", provider=name, count=len(tools))
            return tools

        except ImportError:
            logger.warning("mcp_adapters_not_available", provider=name)
            self._mcp_health[name] = False
            return self._fallback_to_registry(provider, ctx)
        except Exception as e:
            logger.warning("mcp_connection_error", provider=name, error=str(e))
            self._mcp_health[name] = False
            return self._fallback_to_registry(provider, ctx)

    # ── 本地模块加载 ────────────────────────────────────

    def _load_local(self, provider: _ProviderMeta) -> list:
        """
        通过 importlib 导入本地 Python 模块获取工具。
        支持 agent_key 参数（AGENT_TOOL_MAP 场景）。
        """
        try:
            mod = importlib.import_module(provider.module)
            func = getattr(mod, provider.function)

            tools = func(provider.agent_key) if provider.agent_key else func()

            # 确保返回的是列表
            if not isinstance(tools, list):
                tools = [tools]

            # Attach metadata
            for t in tools:
                if not hasattr(t, "metadata") or t.metadata is None:
                    t.metadata = {}
                t.metadata["provider_name"] = provider.name
                t.metadata["danger_level"] = provider.danger_level
                t.metadata["timeout_ms"] = provider.timeout_ms
                t.metadata["degradation"] = provider.degradation
                if provider.tools_requiring_approval:
                    t.metadata["requires_approval"] = t.name in provider.tools_requiring_approval
                else:
                    t.metadata["requires_approval"] = False

            logger.info("local_tools_loaded", provider=provider.name, count=len(tools))
            return tools

        except ImportError as e:
            logger.error(
                "local_module_import_failed",
                provider=provider.name,
                module=provider.module,
                error=str(e),
            )
            raise
        except AttributeError as e:
            logger.error(
                "local_function_not_found",
                provider=provider.name,
                function=provider.function,
                error=str(e),
            )
            raise

    # ── HTTP 端点加载 ──────────────────────────────────

    def _load_http_endpoint(self, provider: _ProviderMeta, ctx: ToolLoadContext) -> list:
        """通过 HTTP 端点加载工具（复用现有 tool_client）"""
        try:
            from app.services.tool_client import create_http_tool

            # 注意：retry 当前由 create_http_tool 内部硬编码（max_retries=3）
            # provider.retry 配置暂未生效，待 create_http_tool 支持 retry 参数后启用
            tool = create_http_tool(
                name=provider.name,
                description=f"HTTP tool: {provider.name}",
                endpoint=provider.url,
                default_params={"company_id": ctx.company_id} if ctx.company_id else None,
            )

            tool.metadata = {
                "provider_name": provider.name,
                "danger_level": provider.danger_level,
                "requires_approval": False,
                "endpoint": provider.url,
                "timeout_ms": provider.timeout_ms,
                "degradation": provider.degradation,
            }

            logger.info("http_endpoint_tool_loaded", provider=provider.name)
            return [tool]

        except Exception as e:
            logger.error("http_endpoint_load_failed", provider=provider.name, error=str(e))
            return []

    # ── MCP 健康检查 ─────────────────────────────────

    async def health_check(self) -> dict[str, bool]:
        """
        启动时验证所有 MCP Server 连接。
        不健康时 WARNING 日志 + 自动降级标记。

        Returns:
            {provider_name: is_healthy}
        """
        results = {}
        for provider in self._providers:
            if provider.type != "mcp_stdio":
                continue
            name = provider.name
            try:
                from langchain_mcp_adapters.client import MultiServerMCPClient

                # 复用连接池，避免重复创建 stdio 子进程（与 _load_mcp_stdio 一致）
                cache_key = (name, "")
                if cache_key in self._mcp_client_pool:
                    client = self._mcp_client_pool[cache_key]
                    logger.debug("mcp_health_check_pool_hit", provider=name)
                else:
                    client_config = {
                        name: {
                            "transport": "stdio",
                            "command": provider.command,
                            "args": provider.args,
                            "env": _build_stdio_env(),
                            "cwd": BACKEND_DIR,
                        }
                    }
                    client = MultiServerMCPClient(client_config)
                    self._mcp_client_pool[cache_key] = client
                    logger.info("mcp_health_check_pool_created", provider=name)
                await client.get_tools()
                self._mcp_health[name] = True
                results[name] = True
                logger.info("mcp_health_check_ok", provider=name)
            except Exception as e:
                self._mcp_health[name] = False
                results[name] = False
                logger.warning(
                    "mcp_health_check_failed",
                    provider=name,
                    error=str(e),
                    suggestion="此 MCP Server 将降级为 Registry 兜底",
                )
        return results

    def get_health_status(self) -> dict:
        """获取当前 MCP Server 健康状态快照"""
        return dict(self._mcp_health)

    # ── MCP 资源/提示支持 ─────────────────────────────

    def _pooled_client(self, provider_name: str, company_id: str | None = None):
        if company_id is not None:
            return self._mcp_client_pool.get((provider_name, str(company_id)))
        matches = [
            client
            for (name, _tenant), client in self._mcp_client_pool.items()
            if name == provider_name
        ]
        return matches[0] if len(matches) == 1 else None

    async def list_resources(self, provider_name: str, company_id: str | None = None) -> list:
        """
        扩展 MCP Server 支持资源(resources)暴露。
        调用 MCP Server 的 list_resources() 方法。

        Args:
            provider_name: Provider 名称

        Returns:
            资源列表
        """
        client = self._pooled_client(provider_name, company_id)
        if client is not None:
            try:
                if hasattr(client, "list_resources"):
                    return await client.list_resources()
            except Exception as e:
                logger.warning("mcp_list_resources_failed", provider=provider_name, error=str(e))
        return []

    async def read_resource(
        self,
        provider_name: str,
        uri: str,
        company_id: str | None = None,
    ) -> dict:
        """
        扩展 MCP Server 支持资源读取。
        调用 MCP Server 的 read_resource() 方法。

        Args:
            provider_name: Provider 名称
            uri: 资源 URI

        Returns:
            资源内容
        """
        client = self._pooled_client(provider_name, company_id)
        if client is not None:
            try:
                if hasattr(client, "read_resource"):
                    return await client.read_resource(uri)
            except Exception as e:
                logger.warning(
                    "mcp_read_resource_failed", provider=provider_name, uri=uri, error=str(e)
                )
        return {}

    async def list_prompts(self, provider_name: str, company_id: str | None = None) -> list:
        """
        扩展 MCP Server 支持数据提示(prompts)暴露。
        调用 MCP Server 的 list_prompts() 方法。

        Args:
            provider_name: Provider 名称

        Returns:
            提示模板列表
        """
        client = self._pooled_client(provider_name, company_id)
        if client is not None:
            try:
                if hasattr(client, "list_prompts"):
                    return await client.list_prompts()
            except Exception as e:
                logger.warning("mcp_list_prompts_failed", provider=provider_name, error=str(e))
        return []

    async def get_prompt(
        self,
        provider_name: str,
        name: str,
        arguments: dict = None,
        company_id: str | None = None,
    ) -> dict:
        """
        扩展 MCP Server 支持获取提示。
        调用 MCP Server 的 get_prompt() 方法。

        Args:
            provider_name: Provider 名称
            name: 提示名称
            arguments: 提示参数

        Returns:
            提示内容
        """
        client = self._pooled_client(provider_name, company_id)
        if client is not None:
            try:
                if hasattr(client, "get_prompt"):
                    return await client.get_prompt(name, arguments or {})
            except Exception as e:
                logger.warning(
                    "mcp_get_prompt_failed", provider=provider_name, prompt=name, error=str(e)
                )
        return {}

    # ── 降级：Registry 兜底 ────────────────────────────

    def _fallback_to_registry(
        self, provider: _ProviderMeta, ctx: ToolLoadContext | None = None
    ) -> list:
        """
        MCP 连接失败时降级到 ToolRegistry。
        """
        try:
            from app.tools.registry import registry

            # 尝试按 provider name 匹配 registry 中的工具
            registered_names = registry.list_registered_tools()
            # 按 token 精确匹配：provider.name 和工具名按 _ 拆分后有共同 token 才算命中
            # 避免子字符串误匹配（如 "search" 误命中 "research_tool"）
            provider_tokens = set(provider.name.replace("_", " ").lower().split())
            matched_names = [
                n
                for n in registered_names
                if provider_tokens & set(n.replace("_", " ").lower().split())
            ]
            if not matched_names:
                matched_names = registered_names  # fallback: 全部

            tools = registry.get_tools_by_names(matched_names)
            if ctx and ctx.company_id:
                tools = [self._bind_registry_http_tool(t, ctx) for t in tools]
            logger.info("tool_registry_fallback", provider=provider.name, count=len(tools))
            return tools

        except Exception as e:
            logger.error("registry_fallback_failed", provider=provider.name, error=str(e))
            return []

    @staticmethod
    def _bind_registry_http_tool(tool_obj: Any, ctx: ToolLoadContext) -> Any:
        """Recreate registry HTTP tools with current tenant context bound."""
        metadata = getattr(tool_obj, "metadata", {}) or {}
        endpoint = metadata.get("endpoint")
        if not endpoint:
            return tool_obj

        from app.services.tool_client import create_http_tool

        rebound = create_http_tool(
            name=getattr(tool_obj, "name", "http_tool"),
            description=getattr(tool_obj, "description", "") or "HTTP tool",
            endpoint=endpoint,
            default_params={"company_id": ctx.company_id},
        )
        rebound.metadata = dict(metadata)
        return rebound


# ── 全局单例 ──────────────────────────────────────────────────

_tool_loader: ToolLoader | None = None
_tool_loader_lock = threading.RLock()


def get_tool_loader() -> ToolLoader:
    """获取全局 ToolLoader 单例（双重检查锁，线程安全）"""
    global _tool_loader
    if _tool_loader is None:
        with _tool_loader_lock:
            # 双重检查：拿到锁后再次确认，防止等待期间已被其他线程创建
            if _tool_loader is None:
                _tool_loader = ToolLoader()
    return _tool_loader
