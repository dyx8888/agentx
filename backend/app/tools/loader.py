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

import importlib
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml
from langchain_core.tools import StructuredTool

from app.core.logging import get_logger

logger = get_logger(__name__)

# 工具描述最小长度阈值（字符）
MIN_DESCRIPTION_LENGTH = 20
# 工具描述质量评分阈值（满分 100）
MIN_DESCRIPTION_SCORE = 60


@dataclass
class ToolLoadContext:
    """工具加载的全局上下文 - 携带租户身份和 trace"""
    company_id: str
    agent_name: str
    trace_id: str
    capabilities: Optional[list[str]] = None


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
    degradation: dict = field(default_factory=dict)  # {critical, cache_ttl, fallback_url, fallback_tool}


class ToolLoader:
    """唯一的工具加载器 - 三种 provider 类型，一条降级链"""

    DEFAULT_CONFIG_PATH = os.path.join(
        os.path.dirname(__file__), '..', '..', 'config', 'tool_providers.yaml'
    )

    def __init__(self, config_path: str = None):
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self._providers: list[_ProviderMeta] = []
        self._loaded = False
        self._schema_cache: dict[str, list] = {}
        # MCP 连接池: {provider_name: MultiServerMCPClient}
        self._mcp_client_pool: dict[str, Any] = {}
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
            self._load_config()
            self._loaded = True

        providers = self._filter_by_capabilities(ctx.capabilities)
        if not providers:
            logger.warning("tool_loader_no_providers_matched",
                           capabilities=ctx.capabilities)
            return []

        all_tools = []
        for p in providers:
            tools = await self._load_provider(p, ctx)
            if tools:
                all_tools.extend(tools)

        logger.info("tool_loader_complete",
                    total=len(all_tools),
                    provider_count=len(providers),
                    capabilities=ctx.capabilities)
        return all_tools

    # ── 工具描述校验与增强 ──────────────────────────────

    def _validate_tool_description(self, tool: Any, provider_name: str) -> tuple[bool, str]:
        """
        校验工具描述质量。
        五原则评分: 命名(20) + 描述(30) + 参数(20) + 错误处理(15) + 职责(15)

        Returns:
            (is_valid, reason): 是否通过校验 + 原因
        """
        desc = getattr(tool, 'description', '') or ''
        name = getattr(tool, 'name', '') or ''

        score = 0
        issues = []

        # 1. 命名清晰度 (20)
        if name and len(name) >= 3:
            score += 20
        else:
            issues.append(f"tool name too short: '{name}'")

        # 2. 描述质量 (30)
        if len(desc) >= MIN_DESCRIPTION_LENGTH:
            has_purpose = any(kw in desc.lower() for kw in ['purpose', '用途', 'return', '返回', 'arg', 'param'])
            if has_purpose:
                score += 30
            else:
                score += 15
                issues.append(f"description missing Purpose/Parameters/Returns sections")
        else:
            issues.append(f"description too short ({len(desc)} chars < {MIN_DESCRIPTION_LENGTH})")

        # 3. 参数说明 (20)
        if hasattr(tool, 'args_schema') and tool.args_schema:
            score += 20
        elif any(kw in desc for kw in ['Args:', 'Parameters:', '参数:', '输入:']):
            score += 15
        else:
            issues.append("no parameter descriptions found")

        # 4. 错误处理 (15) - 检查是否有 error/exception 相关描述
        if any(kw in desc.lower() for kw in ['error', 'exception', 'throw', 'raise', '错误', '异常']):
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

    def _enhance_tool_description(self, tool: Any) -> bool:
        """
        使用 LLM 自动增强工具描述。
        基于函数签名和参数名生成标准化的描述。

        Returns:
            True if enhanced successfully
        """
        try:
            from app.services.model_gateway import ModelGateway

            name = getattr(tool, 'name', 'unknown')
            desc = getattr(tool, 'description', '') or ''
            args_schema = getattr(tool, 'args_schema', None)

            # 提取参数信息
            params_info = ""
            if args_schema and hasattr(args_schema, '__fields__'):
                for field_name, field_info in args_schema.__fields__.items():
                    field_desc = getattr(field_info, 'description', '') or ''
                    field_type = str(getattr(field_info, 'outer_type_', 'Any'))
                    params_info += f"  - {field_name} ({field_type}): {field_desc}\n"

            model_gateway = ModelGateway()
            llm = model_gateway.get_llm("deepseek")

            prompt = f"""你是一个工具文档专家。请为以下 MCP 工具生成标准化的 docstring 描述。

工具名称: {name}
当前描述: {desc if desc else '(无)'}
参数信息:
{params_info if params_info else '(无参数信息)'}

请生成标准的 docstring，包含以下部分:
1. Purpose: 工具用途（一句话）
2. Parameters: 参数说明
3. Returns: 返回值说明
4. Example: 使用示例

要求:
- 简洁明了，总长度不超过 300 字符
- 只返回描述文本，不要包含代码块标记"""
            response = llm.invoke(prompt)
            enhanced = response.content.strip()

            if enhanced and len(enhanced) > MIN_DESCRIPTION_LENGTH:
                tool.description = enhanced
                logger.info("tool_description_enhanced",
                            tool=name,
                            old_len=len(desc),
                            new_len=len(enhanced))
                return True
            return False
        except Exception as e:
            logger.warning("tool_description_enhance_failed",
                           tool=getattr(tool, 'name', 'unknown'),
                           error=str(e))
            return False

    # ── 配置加载 ────────────────────────────────────────

    def _load_config(self):
        """从 tool_providers.yaml 加载所有 provider"""
        try:
            with open(self.config_path, encoding='utf-8') as f:
                config = yaml.safe_load(f)
        except FileNotFoundError:
            logger.warning("tool_providers_config_not_found", path=self.config_path)
            return
        except Exception as e:
            logger.error("tool_providers_config_load_error", error=str(e))
            return

        for entry in config.get('providers', []):
            try:
                meta = _ProviderMeta(
                    name=entry['name'],
                    type=entry['type'],
                    command=entry.get('command', ''),
                    args=entry.get('args', []),
                    module=entry.get('module', ''),
                    function=entry.get('function', ''),
                    agent_key=entry.get('agent_key', ''),
                    url=entry.get('url', ''),
                    timeout_ms=entry.get('timeout_ms', 30000),
                    retry=entry.get('retry', {}),
                    capabilities=entry.get('capabilities', []),
                    danger_level=entry.get('danger_level', 'low'),
                    multi_tenant=entry.get('multi_tenant', False),
                    tools_requiring_approval=entry.get('tools_requiring_approval', []),
                    degradation=entry.get('degradation', {}),
                )
                self._providers.append(meta)
            except KeyError as e:
                logger.warning("tool_provider_missing_field",
                               provider=entry.get('name', 'unknown'),
                               missing=str(e))

        logger.info("tool_providers_loaded", count=len(self._providers))

    def _filter_by_capabilities(self, capabilities: Optional[list[str]]) -> list[_ProviderMeta]:
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
                return await self._load_mcp_stdio(provider, ctx)
            elif provider.type == "local":
                return self._load_local(provider)
            elif provider.type == "http_endpoint":
                return self._load_http_endpoint(provider)
            else:
                logger.warning("unknown_provider_type",
                               provider=provider.name, type=provider.type)
                return []
        except Exception as e:
            logger.warning("provider_load_failed",
                           provider=provider.name, error=str(e))
            return []

    # ── MCP stdio 加载 ─────────────────────────────────

    async def _load_mcp_stdio(self, provider: _ProviderMeta, ctx: ToolLoadContext) -> list:
        """
        通过 MultiServerMCPClient 加载 stdio MCP 服务器工具。
        使用连接池复用连接，避免重复创建 stdio 进程。

        multi_tenant=true 时自动注入 X-Company-Id 和 X-Trace-Id header。
        """
        name = provider.name

        # Schema 缓存
        if name in self._schema_cache:
            logger.debug("tool_schema_cache_hit", provider=name)
            return self._schema_cache[name]

        # 构建 client 配置
        client_config = {
            name: {
                "transport": "stdio",
                "command": provider.command,
                "args": provider.args,
            }
        }

        # 多租户：注入身份 header
        if provider.multi_tenant:
            client_config[name].setdefault("headers", {})
            client_config[name]["headers"]["X-Company-Id"] = ctx.company_id
            client_config[name]["headers"]["X-Trace-Id"] = ctx.trace_id
            logger.info("mcp_tenant_identity_injected",
                        provider=name, company_id=ctx.company_id)

        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient

            # 连接池复用
            if name in self._mcp_client_pool:
                client = self._mcp_client_pool[name]
                logger.debug("mcp_client_pool_hit", provider=name)
            else:
                client = MultiServerMCPClient(client_config)
                self._mcp_client_pool[name] = client
                logger.info("mcp_client_pool_created", provider=name)

            tools = await client.get_tools()

            # 健康检查：标记为健康
            self._mcp_health[name] = True

            # Attach provider metadata to tools
            for t in tools:
                if not hasattr(t, 'metadata') or t.metadata is None:
                    t.metadata = {}
                t.metadata['provider_name'] = name
                t.metadata['danger_level'] = provider.danger_level
                t.metadata['timeout_ms'] = provider.timeout_ms
                t.metadata['degradation'] = provider.degradation
                if provider.tools_requiring_approval:
                    t.metadata['requires_approval'] = (
                        t.name in provider.tools_requiring_approval
                    )
                else:
                    t.metadata['requires_approval'] = False

                # 工具描述校验与增强
                is_valid, reason = self._validate_tool_description(t, name)
                if not is_valid:
                    logger.warning("tool_description_validation_failed",
                                   tool=t.name, provider=name, reason=reason)
                    # 低于阈值时自动增强描述
                    enhanced = self._enhance_tool_description(t)

            # 缓存
            self._schema_cache[name] = tools
            logger.info("mcp_tools_loaded", provider=name, count=len(tools))
            return tools

        except ImportError:
            logger.warning("mcp_adapters_not_available", provider=name)
            self._mcp_health[name] = False
            return self._fallback_to_registry(provider)
        except Exception as e:
            logger.warning("mcp_connection_error", provider=name, error=str(e))
            self._mcp_health[name] = False
            return self._fallback_to_registry(provider)

    # ── 本地模块加载 ────────────────────────────────────

    def _load_local(self, provider: _ProviderMeta) -> list:
        """
        通过 importlib 导入本地 Python 模块获取工具。
        支持 agent_key 参数（AGENT_TOOL_MAP 场景）。
        """
        try:
            mod = importlib.import_module(provider.module)
            func = getattr(mod, provider.function)

            if provider.agent_key:
                tools = func(provider.agent_key)
            else:
                tools = func()

            # 确保返回的是列表
            if not isinstance(tools, list):
                tools = [tools]

            # Attach metadata
            for t in tools:
                if not hasattr(t, 'metadata') or t.metadata is None:
                    t.metadata = {}
                t.metadata['provider_name'] = provider.name
                t.metadata['danger_level'] = provider.danger_level
                t.metadata['timeout_ms'] = provider.timeout_ms
                t.metadata['degradation'] = provider.degradation
                if provider.tools_requiring_approval:
                    t.metadata['requires_approval'] = (
                        t.name in provider.tools_requiring_approval
                    )
                else:
                    t.metadata['requires_approval'] = False

            logger.info("local_tools_loaded", provider=provider.name, count=len(tools))
            return tools

        except ImportError as e:
            logger.error("local_module_import_failed",
                         provider=provider.name, module=provider.module, error=str(e))
            raise
        except AttributeError as e:
            logger.error("local_function_not_found",
                         provider=provider.name, function=provider.function, error=str(e))
            raise

    # ── HTTP 端点加载 ──────────────────────────────────

    def _load_http_endpoint(self, provider: _ProviderMeta) -> list:
        """通过 HTTP 端点加载工具（复用现有 tool_client）"""
        try:
            from app.services.tool_client import create_http_tool

            # 提取 retry 配置
            retry_config = provider.retry
            max_attempts = retry_config.get('max_attempts', 3)

            tool = create_http_tool(
                name=provider.name,
                description=f"HTTP tool: {provider.name}",
                endpoint=provider.url,
            )

            tool.metadata = {
                'provider_name': provider.name,
                'danger_level': provider.danger_level,
                'requires_approval': False,
                'endpoint': provider.url,
                'timeout_ms': provider.timeout_ms,
                'degradation': provider.degradation,
            }

            logger.info("http_endpoint_tool_loaded", provider=provider.name)
            return [tool]

        except Exception as e:
            logger.error("http_endpoint_load_failed",
                         provider=provider.name, error=str(e))
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

                client_config = {
                    name: {
                        "transport": "stdio",
                        "command": provider.command,
                        "args": provider.args,
                    }
                }
                client = MultiServerMCPClient(client_config)
                await client.get_tools()
                self._mcp_health[name] = True
                results[name] = True
                logger.info("mcp_health_check_ok", provider=name)
            except Exception as e:
                self._mcp_health[name] = False
                results[name] = False
                logger.warning("mcp_health_check_failed",
                               provider=name, error=str(e),
                               suggestion="此 MCP Server 将降级为 Registry 兜底")
        return results

    def get_health_status(self) -> dict:
        """获取当前 MCP Server 健康状态快照"""
        return dict(self._mcp_health)

    # ── MCP 资源/提示支持 ─────────────────────────────

    async def list_resources(self, provider_name: str) -> list:
        """
        扩展 MCP Server 支持资源(resources)暴露。
        调用 MCP Server 的 list_resources() 方法。

        Args:
            provider_name: Provider 名称

        Returns:
            资源列表
        """
        if provider_name in self._mcp_client_pool:
            try:
                client = self._mcp_client_pool[provider_name]
                if hasattr(client, 'list_resources'):
                    return await client.list_resources()
            except Exception as e:
                logger.warning("mcp_list_resources_failed",
                               provider=provider_name, error=str(e))
        return []

    async def read_resource(self, provider_name: str, uri: str) -> dict:
        """
        扩展 MCP Server 支持资源读取。
        调用 MCP Server 的 read_resource() 方法。

        Args:
            provider_name: Provider 名称
            uri: 资源 URI

        Returns:
            资源内容
        """
        if provider_name in self._mcp_client_pool:
            try:
                client = self._mcp_client_pool[provider_name]
                if hasattr(client, 'read_resource'):
                    return await client.read_resource(uri)
            except Exception as e:
                logger.warning("mcp_read_resource_failed",
                               provider=provider_name, uri=uri, error=str(e))
        return {}

    async def list_prompts(self, provider_name: str) -> list:
        """
        扩展 MCP Server 支持数据提示(prompts)暴露。
        调用 MCP Server 的 list_prompts() 方法。

        Args:
            provider_name: Provider 名称

        Returns:
            提示模板列表
        """
        if provider_name in self._mcp_client_pool:
            try:
                client = self._mcp_client_pool[provider_name]
                if hasattr(client, 'list_prompts'):
                    return await client.list_prompts()
            except Exception as e:
                logger.warning("mcp_list_prompts_failed",
                               provider=provider_name, error=str(e))
        return []

    async def get_prompt(self, provider_name: str, name: str, arguments: dict = None) -> dict:
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
        if provider_name in self._mcp_client_pool:
            try:
                client = self._mcp_client_pool[provider_name]
                if hasattr(client, 'get_prompt'):
                    return await client.get_prompt(name, arguments or {})
            except Exception as e:
                logger.warning("mcp_get_prompt_failed",
                               provider=provider_name, prompt=name, error=str(e))
        return {}

    # ── 降级：Registry 兜底 ────────────────────────────

    def _fallback_to_registry(self, provider: _ProviderMeta) -> list:
        """
        MCP 连接失败时降级到 ToolRegistry。
        """
        try:
            from app.tools.registry import registry

            # 尝试按 provider name 匹配 registry 中的工具
            registered_names = registry.list_registered_tools()
            # 匹配：包含 provider name 关键字的工具名
            matched_names = [n for n in registered_names
                             if provider.name.replace('_', '') in n.replace('_', '')]
            if not matched_names:
                matched_names = registered_names  # fallback: 全部

            tools = registry.get_tools_by_names(matched_names)
            logger.info("tool_registry_fallback",
                        provider=provider.name, count=len(tools))
            return tools

        except Exception as e:
            logger.error("registry_fallback_failed",
                         provider=provider.name, error=str(e))
            return []


# ── 全局单例 ──────────────────────────────────────────────────

_tool_loader: Optional[ToolLoader] = None


def get_tool_loader() -> ToolLoader:
    """获取全局 ToolLoader 单例"""
    global _tool_loader
    if _tool_loader is None:
        _tool_loader = ToolLoader()
    return _tool_loader