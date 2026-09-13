"""
MasterAgentRouter — master Agent 智能路由执行器

变更② T2.3：本次重构的核心组件。

master 不依赖 LangGraph state machine，而是根据 ContextPackage 智能选择四种执行路径之一：
  WORKFLOW             — 匹配预定义 SOP 模板，DAG 节点执行
  REACT                — 简单单步任务，master 自己调工具
  PLAN_EXECUTE_REFLECT — 复杂多步任务，复用 AgentRuntime
  ENGINE               — 确定性计算，调 Engine（零 LLM）

所有方法返回 async generator，yield SSE 事件字典。
事件类型: routing / plan / action / observation / reflection / result / error / done

文档依据: 02-主Agent编排重构.md 第 4.3 节
"""

import asyncio
import importlib
import inspect
import json
import os
import re
from collections.abc import AsyncIterator

from app.agents.master_routing import (
    WORKFLOW_MAP,
    ExecutionPath,
    select_path,
)
from app.core.high_risk_actions import detect_high_risk_action
from app.core.logging import get_logger
from app.perception.context_package import ContextPackage

logger = get_logger(__name__)

# workflow 模板根目录
WORKFLOW_CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config",
    "workflows",
)
# 工具 Provider 配置根目录（master 专属工具集加载）
TOOL_CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config",
)
# 审查重试上限
REVIEW_MAX_RETRIES = 2

HIGH_RISK_DIRECT_TERMS = (
    "直接",
    "立刻",
    "马上",
    "自动",
    "不用审核",
    "不要审核",
    "不需要审核",
    "不用人工确认",
    "不要人工确认",
    "绕过审核",
    "立即执行",
)

HIGH_RISK_ACTION_RULES = (
    {
        "domain": "price_change",
        "action_terms": ("改价", "修改价格", "调价", "降价到", "涨价到", "改成"),
        "scope_terms": ("商品", "产品", "SKU", "价格", "上架"),
        "label": "商品改价/上架",
    },
    {
        "domain": "order_creation",
        "action_terms": ("下单", "代客下单", "创建订单", "提交订单"),
        "scope_terms": ("客户", "用户", "订单", "商品"),
        "label": "下单/创建订单",
    },
    {
        "domain": "customer_blacklist",
        "action_terms": ("拉黑", "加入黑名单", "封禁客户", "禁言客户", "屏蔽客户"),
        "scope_terms": ("客户", "用户", "买家", "会员"),
        "label": "客户拉黑/封禁",
    },
    {
        "domain": "external_message",
        "action_terms": ("发消息", "发送消息", "群发消息", "自动回复", "发私信"),
        "scope_terms": ("客户", "用户", "达人", "买家", "粉丝"),
        "label": "外联消息发送",
    },
)

def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term and term in text for term in terms)


def _build_approval_required_response(action_label: str) -> str:
    return (
        f"{action_label}属于需要人工确认的高风险业务动作。"
        "我不会代替人工完成资金、订单、价格、物流、账号处置或外联发送。"
        "我可以先整理背景、影响范围、风险点和建议话术，生成待人工审核草稿；"
        "负责人确认后再由有权限的人或系统执行。"
    )


def _detect_master_high_risk_action(message: str, agent_name: str = "master") -> dict | None:
    """Detect high-risk actions at the master router boundary before model/tool execution."""

    core_decision = detect_high_risk_action(message, agent_name)
    if core_decision is not None:
        return {
            "risk_domain": core_decision.risk_domain,
            "risk_level": core_decision.risk_level,
            "response": core_decision.response,
            "requires_human_review": core_decision.requires_human_review,
        }

    text = (message or "").strip()
    if not text:
        return None

    for rule in HIGH_RISK_ACTION_RULES:
        action_terms = rule["action_terms"]
        scope_terms = rule["scope_terms"]
        if not _contains_any(text, action_terms):
            continue
        if not (_contains_any(text, scope_terms) or _contains_any(text, HIGH_RISK_DIRECT_TERMS)):
            continue
        return {
            "risk_domain": rule["domain"],
            "risk_level": "L2",
            "response": _build_approval_required_response(rule["label"]),
            "requires_human_review": True,
        }

    return None


# LLM slot-filling 提示词：从自由文本查询抽取结构化引擎入参
SLOT_FILL_PROMPT = """你是参数抽取器。请从用户查询中抽取结构化参数，用于调用确定性计算引擎。

## 可用引擎方法
{methods_desc}

## 用户查询
{query}

## 输出要求
仅以 JSON 返回（不要输出多余文字）:
{{
  "method_name": "方法名",
  "params": {{"参数名": 值}}
}}

## 规则
1. 选择最匹配用户意图的方法
2. 参数值必须是数值（int/float）或字符串类型
3. 查询中未提及的数值参数使用 0，字符串参数使用空字符串
4. 无法匹配任何方法时返回 {{"method_name": "", "params": {{}}}}
"""

# LLM 验收提示词：对比执行结果与原始意图
REVIEW_PROMPT = """请判断【执行结果】是否满足【用户意图】。

## 用户意图
{query}

## 执行结果
{result}

## 输出要求
仅以 JSON 返回（不要输出多余文字）:
{{
  "accept": true或false,
  "reason": "判断理由（简短）"
}}

## 判断标准
1. 结果是否回应了用户意图的核心诉求
2. 结果内容是否完整、相关、无明显错误
3. 结果非空且有实质内容
若结果完整、相关、无明显错误，accept=true。
"""


class MasterToolLoader:
    """从 config/tool_providers.yaml 加载 master 专属工具集。

    加载策略：
    1. 优先读取 type=local 且 agent_key="master" 或 capabilities 含 "master" 的 provider
    2. 若无 master 专属 provider，降级到 capability_map.core 的 local provider
    3. MCP/HTTP provider 不在此加载（需独立连接管理），仅加载本地 Python 工具
    4. 任一步骤失败返回空列表，调用方降级到 get_core_tools()
    """

    def __init__(self, config_path: str = None):
        self._config_path = config_path or os.path.join(
            TOOL_CONFIG_DIR,
            "tool_providers.yaml",
        )
        self._tools: list | None = None  # 缓存，避免重复加载

    def load(self) -> list:
        """加载 master 工具集，失败返回空列表。"""
        if self._tools is not None:
            return self._tools
        self._tools = self._load_from_config()
        return self._tools

    def _load_from_config(self) -> list:
        """从 tool_providers.yaml 加载 master 专属工具集。"""
        try:
            import yaml

            with open(self._config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.info("master_tool_config_not_found", path=self._config_path)
            return []
        except Exception as e:
            logger.warning("master_tool_config_load_failed", error=str(e))
            return []

        providers = config.get("providers", [])
        capability_map = config.get("capability_map", {})

        # 1. 找 agent_key == "master" 或 capabilities 含 "master" 的 local providers
        master_providers = [
            p
            for p in providers
            if p.get("type") == "local"
            and (p.get("agent_key") == "master" or "master" in (p.get("capabilities") or []))
        ]

        # 2. 若没有 master 专属 provider，用 core capability 的 local providers 兜底
        if not master_providers:
            core_names = set(capability_map.get("core", []))
            master_providers = [
                p for p in providers if p.get("type") == "local" and p.get("name") in core_names
            ]

        if not master_providers:
            logger.info("master_tool_no_provider", config_path=self._config_path)
            return []

        # 3. 加载每个 provider 的工具
        tools: list = []
        for p in master_providers:
            module_path = p.get("module")
            func_name = p.get("function")
            if not module_path or not func_name:
                continue
            try:
                mod = importlib.import_module(module_path)
                func = getattr(mod, func_name, None)
                if func is None:
                    continue
                # get_core_tools() 无参数；get_agent_tools(agent_key) 需参数
                sig = inspect.signature(func)
                provider_tools = func() if len(sig.parameters) == 0 else func("master")
                if isinstance(provider_tools, list):
                    tools.extend(provider_tools)
                logger.info(
                    "master_tool_provider_loaded",
                    provider=p.get("name"),
                    count=len(provider_tools) if isinstance(provider_tools, list) else 0,
                )
            except Exception as e:
                logger.warning(
                    "master_tool_provider_load_failed",
                    provider=p.get("name"),
                    error=str(e),
                )
                continue

        logger.info("master_tools_loaded", count=len(tools))
        return tools


class MasterAgentRouter:
    """master Agent 智能路由执行器。

    master 不仅路由，自己也能执行简单任务（REACT 路径）。

    使用方式:
        router = MasterAgentRouter()
        async for event in router.execute(context_package):
            # event 是 SSE 事件字典: {"type": "routing", "path": "react"}
            yield sse_event(event)

    事件流示例（REACT 路径）:
        {"type": "routing", "path": "react"}
        {"type": "action", "data": "调用工具 search_kols"}
        {"type": "observation", "data": "找到 3 个达人"}
        {"type": "result", "data": "最终回复内容"}
        {"type": "done"}
    """

    def __init__(
        self, model_gateway=None, agent_runtime=None, master_dispatcher=None, tool_loader=None
    ):
        """构造函数。

        Args:
            model_gateway: ModelGateway 实例，None 时延迟获取
            agent_runtime: AgentRuntime 实例，None 时延迟创建
            master_dispatcher: MasterDispatcher 实例，None 时延迟创建
            tool_loader: master 专属工具集加载器（MasterToolLoader 或 callable），
                None 时延迟创建 MasterToolLoader 实例
        """
        self._model_gateway = model_gateway
        self._agent_runtime = agent_runtime
        self._master_dispatcher = master_dispatcher
        self._tool_loader = tool_loader

    @staticmethod
    def _selected_model_key(context: ContextPackage) -> str | None:
        value = (getattr(context, "intent_entities", {}) or {}).get("model_provider", "")
        value = str(value or "").strip()
        return value or None

    @staticmethod
    def _context_company_id(context: ContextPackage) -> int | None:
        company_id = getattr(context, "company_id", None)
        try:
            return int(company_id) if company_id else None
        except (TypeError, ValueError):
            return None

    # ==================== 主入口 ====================

    async def execute(self, context: ContextPackage) -> AsyncIterator[dict]:
        """master Agent 主执行流程。

        Step 1: 智能路由 → 选 execution_path
        Step 2: 按路径执行（审查层不合格时触发重试，最多 REVIEW_MAX_RETRIES 次）
        Step 3: 审查结果（LLM 验收 + 结构化校验降级）

        Args:
            context: 感知层产出的综合上下文包

        Yields:
            SSE 事件字典（含 retry/warning 新事件类型，前端忽略未知类型不影响）
        """
        guard_decision = _detect_master_high_risk_action(
            context.raw_input or context.rewritten_query or "",
            "master",
        )
        if guard_decision:
            yield {
                "type": "routing",
                "path": "guardrail",
                "guarded": True,
                "risk_domain": guard_decision["risk_domain"],
            }
            yield {
                "type": "result",
                "data": guard_decision["response"],
                "guarded": True,
                "requires_human_review": guard_decision["requires_human_review"],
                "risk_domain": guard_decision["risk_domain"],
            }
            yield {"type": "done", "guarded": True}
            return

        # Step 1: 智能路由
        path = select_path(context)
        yield {"type": "routing", "path": path.value}

        logger.info(
            "master_execute_start",
            path=path.value,
            intent_type=context.intent_type,
            query_length=len(context.raw_input),
        )

        # Step 2: 按路径执行
        # 跟踪路径是否产出 result 事件及其内容，供 Step 3 审查使用
        result_produced = False
        error_produced = False
        final_result_text = ""
        try:
            async for event in self._run_path_events(path, context):
                if event.get("type") == "result":
                    result_produced = True
                    final_result_text = str(event.get("data", ""))
                elif event.get("type") == "error":
                    error_produced = True
                yield event
        except Exception as e:
            logger.error("master_execute_path_failed", path=path.value, error=str(e))
            error_event = self._model_config_error_event(e)
            yield error_event or {
                "type": "error",
                "data": f"执行路径 {path.value} 失败: {str(e)}",
            }
            error_produced = True

        if error_produced and not result_produced:
            yield {"type": "done"}
            return

        # Step 3: 审查结果（含 LLM 验收层 + 重试循环）
        async for event in self._review_and_finalize(
            context, path, result_produced, final_result_text
        ):
            yield event

    async def _run_path_events(
        self, path: ExecutionPath, context: ContextPackage
    ) -> AsyncIterator[dict]:
        """按路径执行的统一入口，供 execute 和审查重试循环复用。"""
        if path == ExecutionPath.WORKFLOW:
            async for event in self._run_workflow(context):
                yield event
        elif path == ExecutionPath.REACT:
            async for event in self._run_react(context):
                yield event
        elif path == ExecutionPath.PLAN_EXECUTE_REFLECT:
            async for event in self._run_plan_execute_reflect(context):
                yield event
        elif path == ExecutionPath.ENGINE:
            async for event in self._run_engine(context):
                yield event

    # ==================== 路径 1: WORKFLOW ====================

    async def _run_workflow(self, context: ContextPackage) -> AsyncIterator[dict]:
        """WORKFLOW 路径：加载预定义 SOP 模板 → DAG 执行 → 每个节点调对应 Agent。

        workflow 模板格式（JSON/YAML）:
        {
            "name": "workflow_name",
            "nodes": [
                {"id": "node_1", "agent": "BrandBD", "action": "search_kols", "depends_on": []},
                {"id": "node_2", "agent": "BrandBD", "action": "generate_outreach", "depends_on": ["node_1"]}
            ]
        }

        执行策略：
        1. 按 depends_on 拓扑排序
        2. 无依赖的节点用 asyncio.gather 并行执行
        3. depends_on 的节点结果作为输入注入
        4. MasterDispatcher 不可用时降级到 _execute_workflow_node 逐节点串行执行
        """
        # 确定匹配的 workflow 文件
        workflow_file = self._resolve_workflow_file(context)
        if not workflow_file:
            yield {"type": "error", "data": "无法匹配 workflow 模板，降级到 PLAN_EXECUTE_REFLECT"}
            # 降级到 PLAN_EXECUTE_REFLECT
            async for event in self._run_plan_execute_reflect(context):
                yield event
            return

        yield {"type": "plan", "data": f"加载 workflow 模板: {workflow_file}"}

        # 加载 workflow 定义
        workflow_def = self._load_workflow_def(workflow_file)
        if not workflow_def:
            yield {"type": "error", "data": f"workflow 模板加载失败: {workflow_file}"}
            return

        nodes = workflow_def.get("nodes", [])
        if not nodes:
            yield {"type": "error", "data": "workflow 模板无节点定义"}
            return

        # 优先走 MasterDispatcher.orchestrate_stream（节点级并行 + 依赖结果注入）
        dispatcher = self._get_master_dispatcher()
        if dispatcher is not None:
            logger.info("workflow_via_dispatcher", workflow=workflow_def.get("name", ""))
            try:
                async for event in dispatcher.orchestrate_stream(context, workflow_def):
                    yield event
                return
            except Exception as e:
                logger.warning(
                    "workflow_dispatcher_failed",
                    workflow=workflow_def.get("name", ""),
                    error=str(e),
                )
                # 降级到逐节点串行执行

        # 降级：通过 _execute_workflow_node 逐节点串行执行（单节点 fallback）
        executed: dict[str, dict] = {}  # node_id → node_result
        for node in nodes:
            node_id = node.get("id", "")
            node_agent = node.get("agent", "")
            node_action = node.get("action", "")
            node_desc = node.get("description", node_action)

            yield {"type": "action", "data": f"[{node_agent}] {node_desc}"}

            # 执行节点（委派给对应 Agent）
            try:
                node_result = await self._execute_workflow_node(
                    node=node,
                    context=context,
                    executed_results=executed,
                )
                executed[node_id] = node_result
                yield {"type": "observation", "data": node_result.get("summary", "节点执行完成")}
            except Exception as e:
                logger.warning("workflow_node_failed", node_id=node_id, error=str(e))
                executed[node_id] = {"error": str(e), "summary": f"节点 {node_id} 执行失败"}
                yield {"type": "observation", "data": f"节点 {node_id} 执行失败: {str(e)}"}

        # 汇总 workflow 结果
        final_summary = self._summarize_workflow_results(workflow_def.get("name", ""), executed)
        yield {"type": "result", "data": final_summary}

    def _resolve_workflow_file(self, context: ContextPackage) -> str | None:
        """根据 context 解析匹配的 workflow 文件名。"""
        # 优先从 entities 获取 target_agent
        target_agent = context.intent_entities.get("target_agent", "")
        if target_agent and target_agent in WORKFLOW_MAP:
            return WORKFLOW_MAP[target_agent]

        # 从 matched_skills 获取
        for skill in context.matched_skills:
            skill_agent = getattr(skill, "agent_name", "")
            if skill_agent and skill_agent in WORKFLOW_MAP:
                return WORKFLOW_MAP[skill_agent]

        # 从 entities 获取 workflow
        workflow_name = context.intent_entities.get("workflow", "")
        if workflow_name and workflow_name in WORKFLOW_MAP:
            return WORKFLOW_MAP[workflow_name]

        return None

    def _load_workflow_def(self, filename: str) -> dict:
        """加载 workflow 模板文件（支持 JSON 和 YAML）。"""
        filepath = os.path.join(WORKFLOW_CONFIG_DIR, filename)
        try:
            with open(filepath, encoding="utf-8") as f:
                content = f.read()
            if filename.endswith(".json"):
                return json.loads(content)
            else:
                import yaml

                return yaml.safe_load(content)
        except FileNotFoundError:
            logger.warning("workflow_file_not_found", path=filepath)
            return {}
        except Exception as e:
            logger.warning("workflow_load_failed", path=filepath, error=str(e))
            return {}

    async def _execute_workflow_node(
        self,
        node: dict,
        context: ContextPackage,
        executed_results: dict,
    ) -> dict:
        """执行单个 workflow 节点：委派给对应 Agent 执行 action（单节点 fallback）。

        当 MasterDispatcher.orchestrate_stream 不可用时，作为逐节点串行执行的 fallback。
        1. 从 AGENT_REGISTRY 查找节点指定的 agent（兼容 registry key 与显示名）
        2. 若 agent 存在且 active，通过 AgentRuntime.run() 真实委派执行
        3. 若 AgentRuntime 不可用或 agent 未激活，返回结构化待委派响应
        """
        from app.agents import AGENT_REGISTRY  # 延迟导入避免循环依赖

        node_id = node.get("id", "")
        node_agent = node.get("agent", "")
        node_action = node.get("action", "")
        node_desc = node.get("description", node_action)

        # --- 解析 agent_key：兼容 "data_analysis" / "BrandBD" / "数据分析" 等形式 ---
        agent_key = self._resolve_agent_key(node_agent, AGENT_REGISTRY)
        agent_info = AGENT_REGISTRY.get(agent_key) if agent_key else None

        if not agent_info or not agent_info.get("active", True):
            # agent 未注册或当前阶段未激活（如 S-OUT-04 排除项）
            return {
                "node_id": node_id,
                "agent": node_agent,
                "agent_key": agent_key,
                "action": node_action,
                "summary": f"agent {node_agent} 未激活或未注册，节点待委派",
                "status": "pending_delegation",
            }

        # --- 通过 AgentRuntime 真实委派 ---
        runtime = self._get_agent_runtime()
        if runtime is None:
            return {
                "node_id": node_id,
                "agent": node_agent,
                "agent_key": agent_key,
                "action": node_action,
                "summary": f"AgentRuntime 不可用，节点 {node_id} 待委派",
                "status": "pending_delegation",
            }

        company_id = self._context_company_id(context)
        # 节点任务消息：action 为主，description 为辅
        task_message = (
            f"{node_action}: {node_desc}" if node_desc and node_desc != node_action else node_action
        )
        try:
            result = await runtime.run(
                message=task_message,
                agent_name=agent_key,
                company_id=str(company_id) if company_id else "",
                model_key=self._selected_model_key(context),
            )
            response = result.get("response", "")
            success = result.get("success", True)
            return {
                "node_id": node_id,
                "agent": node_agent,
                "agent_key": agent_key,
                "action": node_action,
                "summary": response or f"{agent_key} 执行 {node_action} 完成",
                "status": "completed" if success else "partial",
                "success": success,
            }
        except Exception as e:
            logger.warning(
                "workflow_node_delegate_failed",
                node_id=node_id,
                agent_key=agent_key,
                error=str(e),
            )
            return {
                "node_id": node_id,
                "agent": node_agent,
                "agent_key": agent_key,
                "action": node_action,
                "summary": f"节点 {node_id} 委派失败: {str(e)}",
                "status": "failed",
                "error": str(e),
            }

    @staticmethod
    def _resolve_agent_key(agent_name: str, registry: dict) -> str:
        """从 AGENT_REGISTRY 解析 agent_key，兼容 registry key 与显示名。

        匹配顺序：
        1. 精确 key 匹配（如 "data_analysis"）
        2. 规范化匹配：去除非字母数字字符并小写（如 "BrandBD" ↔ "brand_bd"）
        3. 显示名匹配（如 "数据分析" → "data_analysis"）
        """
        if not agent_name:
            return ""
        if agent_name in registry:
            return agent_name
        norm = re.sub(r"[^a-z0-9]", "", agent_name.lower())
        for key in registry:
            if re.sub(r"[^a-z0-9]", "", key.lower()) == norm:
                return key
        for key, info in registry.items():
            if info.get("name_display") == agent_name:
                return key
        return ""

    def _summarize_workflow_results(self, workflow_name: str, executed: dict) -> str:
        """汇总 workflow 所有节点的执行结果。"""
        if not executed:
            return f"workflow {workflow_name} 无执行结果"

        parts = [f"workflow {workflow_name} 执行完成，共 {len(executed)} 个节点:"]
        for node_id, result in executed.items():
            status = result.get("status", "unknown")
            summary = result.get("summary", "")
            parts.append(f"  - [{node_id}] {status}: {summary}")

        return "\n".join(parts)

    # ==================== 路径 2: REACT ====================

    async def _run_react(self, context: ContextPackage) -> AsyncIterator[dict]:
        """REACT 路径：复用 build_reaction_graph() → master 自己调工具。

        master 直接使用 ReAct 模式（思考→行动→观察→思考...），
        不委派给子 Agent，适合简单单步任务。
        """
        raw_query = context.raw_input or ""
        query = context.rewritten_query or raw_query
        exact_reply = self._extract_exact_reply_request(raw_query)
        if exact_reply:
            yield {"type": "action", "data": "deterministic exact reply short path"}
            yield {"type": "observation", "data": "skipped agent orchestration for exact reply request"}
            yield {"type": "result", "data": exact_reply}
            return

        rag_answer_chunks = self._get_rag_answer_chunks(context)
        if rag_answer_chunks:
            yield {"type": "action", "data": f"RAG answer from knowledge base: {query[:50]}..."}
            try:
                result = await self._answer_from_rag(query, context)
                warning_event = self._model_fallback_warning_event(
                    result.get("model_fallback")
                )
                if warning_event:
                    yield warning_event
                yield {"type": "observation", "data": result.get("intermediate", "")}
                yield {"type": "result", "data": result.get("answer", query)}
            except Exception as e:
                logger.warning("rag_answer_failed", error=str(e))
                fallback = self._format_rag_fallback(rag_answer_chunks)
                yield {"type": "observation", "data": "RAG answer fallback used"}
                yield {"type": "result", "data": fallback or query}
            return

        yield {"type": "action", "data": f"master ReAct 模式处理: {query[:50]}..."}

        try:
            # 复用 app/agent.py 的 build_reaction_graph 构建 ReAct 图并 ainvoke
            result = await self._react_execute(query, context)
            warning_event = self._model_fallback_warning_event(
                result.get("model_fallback")
            )
            if warning_event:
                yield warning_event
            yield {"type": "observation", "data": result.get("intermediate", "")}
            yield {"type": "result", "data": result.get("answer", query)}
        except Exception as e:
            logger.warning("react_execute_failed", error=str(e))
            error_event = self._model_config_error_event(e)
            if error_event:
                yield error_event
                return
            # 降级：直接返回查询作为结果
            yield {"type": "result", "data": f"ReAct 执行遇到问题，原始查询: {query}"}

    @staticmethod
    def _extract_model_fallback_metadata(response) -> dict | None:
        metadata = getattr(response, "response_metadata", None)
        if not isinstance(metadata, dict):
            return None

        fallback = metadata.get("model_fallback")
        if not isinstance(fallback, dict):
            return None

        from_model = str(fallback.get("from_model") or "").strip()
        to_model = str(fallback.get("to_model") or "").strip()
        error = str(fallback.get("error") or "").strip()
        if not from_model and not to_model:
            return None

        return {
            "from_model": from_model,
            "to_model": to_model,
            "error": error[:200],
        }

    @staticmethod
    def _model_fallback_warning_event(fallback: dict | None) -> dict | None:
        if not fallback:
            return None

        from_model = str(fallback.get("from_model") or "").strip()
        to_model = str(fallback.get("to_model") or "").strip()
        message = "主模型暂时不可用，已自动切换到备用模型继续处理。"
        if from_model and to_model:
            message = f"主模型 {from_model} 暂时不可用，已切换到 {to_model} 继续处理。"

        return {
            "type": "warning",
            "code": "model_fallback",
            "message": message,
            "from_model": from_model,
            "to_model": to_model,
            "error": str(fallback.get("error") or "")[:200],
        }

    @staticmethod
    def _model_config_error_event(exc: Exception) -> dict | None:
        if getattr(exc, "code", "") != "model_api_key_missing":
            return None

        if hasattr(exc, "to_public_payload"):
            payload = exc.to_public_payload()
        else:
            payload = {
                "code": "model_api_key_missing",
                "message": str(exc),
                "requires_config": True,
                "config_target": "llm_api_key",
            }
        message = str(payload.get("message") or "模型 API Key 未配置。")
        return {
            "type": "error",
            "code": "model_api_key_missing",
            "message": message,
            "content": message,
            "requires_config": bool(payload.get("requires_config", True)),
            "config_target": payload.get("config_target", "llm_api_key"),
            "provider": payload.get("provider", ""),
            "model": payload.get("model", ""),
            "env_keys": payload.get("env_keys", []),
        }

    @staticmethod
    def _get_rag_answer_chunks(context: ContextPackage) -> list[dict]:
        """Return model-facing RAG evidence, falling back to legacy rag_chunks."""
        evidence_chunks = getattr(context, "rag_evidence_chunks", None) or []
        if evidence_chunks:
            return evidence_chunks
        return getattr(context, "rag_chunks", None) or []

    async def _answer_from_rag(self, query: str, context: ContextPackage) -> dict:
        """Answer directly from retrieved RAG chunks before generic agent routing."""
        from langchain_core.messages import HumanMessage, SystemMessage

        rag_answer_chunks = self._get_rag_answer_chunks(context)
        mg = self._get_model_gateway()
        if mg is None:
            return {
                "answer": self._format_rag_fallback(rag_answer_chunks),
                "intermediate": "model gateway unavailable; returned retrieved RAG content",
            }

        company_id_int = self._context_company_id(context)
        llm = mg.get_llm(
            model_key=self._selected_model_key(context),
            company_id=company_id_int,
        )
        references = self._format_rag_references(rag_answer_chunks)
        prompt = (
            "User question:\n"
            f"{query}\n\n"
            "Retrieved knowledge base references:\n"
            f"{references}\n\n"
            "Answer requirements:\n"
            "1. Answer only from the retrieved references.\n"
            "2. If the answer is directly present, provide it directly and concisely.\n"
            "3. Do not say the task is outside the platform scope when references answer it.\n"
            "4. If references are insufficient, say that the knowledge base does not contain enough information."
        )
        messages = [
            SystemMessage(
                content=(
                    "You are AgentX's knowledge-base answerer. "
                    "Use retrieved references as the source of truth."
                )
            ),
            HumanMessage(content=prompt),
        ]
        response = await llm.ainvoke(messages, company_id=company_id_int)
        answer = response.content if hasattr(response, "content") else str(response)
        model_fallback = self._extract_model_fallback_metadata(response)
        return {
            "answer": answer.strip() or self._format_rag_fallback(rag_answer_chunks),
            "intermediate": f"answered from {len(rag_answer_chunks)} RAG reference(s)",
            "model_fallback": model_fallback,
        }

    @staticmethod
    def _format_rag_references(rag_chunks: list[dict]) -> str:
        parts = []
        for idx, chunk in enumerate(rag_chunks[:5], 1):
            content = str(chunk.get("content") or chunk.get("text") or "").strip()
            if not content:
                continue
            source = chunk.get("source_file") or chunk.get("source") or chunk.get("filename") or ""
            score = chunk.get("score") or chunk.get("distance") or ""
            meta = []
            if source:
                meta.append(f"source={source}")
            if score != "":
                meta.append(f"score={score}")
            header = f"[{idx}]"
            if meta:
                header += " " + ", ".join(meta)
            parts.append(f"{header}\n{content[:2000]}")
        return "\n\n".join(parts)

    @classmethod
    def _format_rag_fallback(cls, rag_chunks: list[dict]) -> str:
        references = cls._format_rag_references(rag_chunks)
        if not references:
            return ""
        return "I found the following relevant knowledge base content:\n\n" + references

    async def _react_execute(self, query: str, context: ContextPackage) -> dict:
        """ReAct 模式执行：构建 master 的 ReAct 图并 ainvoke。

        增强实现：
        1. 获取 model_gateway + llm
        2. 获取 master 系统提示词（MASTER_SYSTEM_PROMPT）+ master 专属工具集
        3. master 专属工具集从 config/tool_providers.yaml 加载（MasterToolLoader），
           加载失败时降级到 get_core_tools() 通用核心工具兜底
        4. 构建 agent_node（llm.bind_tools + ainvoke）→ build_reaction_graph
        5. react_app.ainvoke(state) 执行 ReAct 循环
        6. 从最终消息提取答案，从 tool_calls 提取中间步骤
        """
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            from app.agent import (
                bind_tenant_core_tools,
                build_reaction_graph,
                get_tenant_core_tools,
            )
            from app.agents.master import MASTER_SYSTEM_PROMPT

            mg = self._get_model_gateway()
            if mg is None:
                return {"answer": query, "intermediate": "model_gateway 不可用，ReAct 降级"}

            company_id_int = self._context_company_id(context)
            llm = mg.get_llm(
                model_key=self._selected_model_key(context),
                company_id=company_id_int,
            )

            # 工具：优先用 master 专属工具集（从 tool_providers.yaml 加载），
            # 加载失败或为空时降级到 get_core_tools() 兜底
            tools = self._load_master_tools()
            if tools:
                tools = bind_tenant_core_tools(tools, company_id_int)
            else:
                try:
                    tools = get_tenant_core_tools(company_id_int) if company_id_int else []
                    logger.info("react_tools_fallback_core", count=len(tools))
                except Exception as tool_err:
                    logger.warning("react_tools_unavailable", error=str(tool_err))
                    tools = []

            llm_with_tools = llm.bind_tools(tools) if tools else llm
            model_fallbacks: list[dict] = []

            async def agent_node(state):
                messages = state["messages"]
                messages_with_system = [SystemMessage(content=MASTER_SYSTEM_PROMPT)] + messages
                response = await llm_with_tools.ainvoke(
                    messages_with_system, company_id=company_id_int
                )
                model_fallback = self._extract_model_fallback_metadata(response)
                if model_fallback:
                    model_fallbacks.append(model_fallback)
                return {"messages": [response]}

            react_app, _ = build_reaction_graph(agent_node, tools, mg)

            state = {
                "messages": [HumanMessage(content=query)],
                "company_context": {
                    "agent_name": "master",
                    "company_id": str(company_id_int) if company_id_int else "",
                },
            }
            result_state = await react_app.ainvoke(state)
            final_messages = result_state.get("messages", [])
            answer = final_messages[-1].content if final_messages else query

            # 收集中间工具调用作为 observation
            intermediate_parts = []
            for m in final_messages:
                tool_calls = getattr(m, "tool_calls", None) or []
                for tc in tool_calls:
                    intermediate_parts.append(f"调用工具: {tc.get('name', '')}")
            intermediate = "; ".join(intermediate_parts) if intermediate_parts else "ReAct 执行完成"
            return {
                "answer": answer,
                "intermediate": intermediate,
                "model_fallback": model_fallbacks[0] if model_fallbacks else None,
            }
        except Exception as e:
            if self._model_config_error_event(e):
                raise
            logger.warning("react_execute_failed", error=str(e))
            return {"answer": query, "intermediate": f"ReAct 降级模式: {str(e)}"}

    def _load_master_tools(self) -> list:
        """加载 master 专属工具集。

        优先通过 MasterToolLoader 从 config/tool_providers.yaml 加载，
        loader 不可用或加载失败时返回空列表，调用方降级到 get_core_tools()。
        """
        try:
            loader = self._get_tool_loader()
            if loader is None:
                return []
            if hasattr(loader, "load"):
                return loader.load() or []
            # 兼容 callable 形式的 loader
            if callable(loader):
                return loader() or []
            return []
        except Exception as e:
            logger.warning("master_tools_load_failed", error=str(e))
            return []

    # ==================== 路径 3: PLAN_EXECUTE_REFLECT ====================

    async def _run_plan_execute_reflect(self, context: ContextPackage) -> AsyncIterator[dict]:
        """PLAN_EXECUTE_REFLECT 路径：通过 MasterDispatcher 拆解 → 委派 → 审查。

        T2.5：替换 T2.3 的简化实现，接入 MasterDispatcher.orchestrate_stream()，
        让委派过程通过 SSE delegation 事件实时推给前端。
        """
        try:
            dispatcher = self._get_master_dispatcher()
            if dispatcher is not None:
                async for event in dispatcher.orchestrate_stream(context):
                    yield event
            else:
                # 降级：MasterDispatcher 不可用时走旧 AgentRuntime
                query = context.rewritten_query or context.raw_input
                yield {"type": "plan", "data": f"master 拆解任务: {query[:50]}..."}
                runtime = self._get_agent_runtime()
                if runtime is not None:
                    company_id = self._context_company_id(context)
                    async for event in runtime.run_stream(
                        message=query,
                        agent_name="master",
                        company_id=str(company_id) if company_id else "",
                        model_key=self._selected_model_key(context),
                    ):
                        yield event
                else:
                    yield {"type": "error", "data": "AgentRuntime 不可用"}
                    yield {"type": "result", "data": query}
        except Exception as e:
            error_event = self._model_config_error_event(e)
            if error_event:
                yield error_event
                return
            logger.warning("plan_execute_reflect_failed", error=str(e))
            yield {"type": "error", "data": f"Plan-Execute-Reflect 失败: {str(e)}"}
            yield {"type": "result", "data": context.raw_input}

    # ==================== 路径 4: ENGINE ====================

    async def _run_engine(self, context: ContextPackage) -> AsyncIterator[dict]:
        """ENGINE 路径：调 app/engines/ 对应的 Engine。

        引擎计算本身是确定性的（零 LLM），但用 LLM 做参数抽取（slot-filling），
        从自由文本查询中抽取结构化入参后反射调用引擎方法。
        LLM 不可用时降级返回能力清单。
        """
        query = context.rewritten_query or context.raw_input

        yield {"type": "action", "data": f"确定性计算引擎处理: {query[:50]}..."}

        try:
            result = await self._engine_execute(query, context)
            yield {"type": "observation", "data": result.get("detail", "")}
            yield {"type": "result", "data": result.get("answer", "计算完成")}
        except Exception as e:
            logger.warning("engine_execute_failed", error=str(e))
            yield {"type": "error", "data": f"计算引擎失败: {str(e)}"}
            yield {"type": "result", "data": f"计算失败，请稍后重试: {query}"}

    async def _engine_execute(self, query: str, context: ContextPackage) -> dict:
        """调用确定性计算引擎（含 LLM slot-filling）。

        根据查询内容选择合适的 Engine：
        - ROI/利润/转化率 → MetricsEngine
        - 物流时效 → WarehouseLogisticsEngine
        - 选品评分 → ProductScoringEngine
        - 投放成本 → AdDeliveryEngine

        执行流程：
        1. 通过 load_engine_for_agent 加载目标引擎
        2. 反射引擎可用方法及其签名
        3. LLM slot-filling：从 query 抽取结构化入参（method_name + params）
        4. 反射调用引擎对应方法（如 MetricsEngine.calculate_metrics(**params)）
        5. LLM 输出解析失败或引擎调用失败时，降级返回能力清单
        """
        try:
            from app.agents import load_engine_for_agent

            # 根据查询内容选择 agent_key
            agent_key = self._select_engine_agent_key(query)
            if not agent_key:
                return {"answer": "无法匹配计算引擎", "detail": ""}

            engine = load_engine_for_agent(agent_key)
            if engine is None:
                return {"answer": "计算引擎不可用", "detail": f"agent_key={agent_key}"}

            # 反射引擎可用方法（排除私有/魔术方法）
            engine_obj = engine if isinstance(engine, type) else engine.__class__
            engine_instance = engine if not isinstance(engine, type) else engine
            methods = self._reflect_engine_methods(engine_obj)

            if not methods:
                return {"answer": f"计算引擎 {agent_key} 无可用方法", "detail": ""}

            # LLM slot-filling：从 query 抽取结构化入参
            slot_result = await self._llm_slot_fill(query, methods, context)

            if slot_result and slot_result.get("method_name"):
                method_name = slot_result["method_name"]
                params = slot_result.get("params", {}) or {}

                try:
                    method = getattr(engine_instance, method_name, None)
                    if method is None:
                        method = getattr(engine_obj, method_name, None)
                    if method is None or not callable(method):
                        raise ValueError(f"方法 {method_name} 不存在于引擎 {engine_obj.__name__}")

                    # 过滤无效参数，只保留方法签名中存在的参数
                    params = self._filter_method_params(method, params)

                    logger.info(
                        "engine_slot_fill_invoke",
                        agent_key=agent_key,
                        method=method_name,
                        params=params,
                    )

                    # 调用引擎方法（支持同步/异步方法）
                    if asyncio.iscoroutinefunction(method):
                        result = await method(**params)
                    else:
                        result = method(**params)

                    result_str = self._format_engine_result(result, method_name, params)
                    return {
                        "answer": result_str,
                        "detail": (
                            f"查询: {query}\n"
                            f"引擎: {engine_obj.__name__}\n"
                            f"方法: {method_name}\n"
                            f"参数: {params}"
                        ),
                        "engine_agent_key": agent_key,
                        "engine_method": method_name,
                        "status": "completed",
                    }
                except Exception as e:
                    logger.warning(
                        "engine_invoke_failed",
                        agent_key=agent_key,
                        method=method_name,
                        error=str(e),
                    )
                    # 降级到能力清单
            else:
                logger.info(
                    "engine_slot_fill_no_method",
                    agent_key=agent_key,
                    query=query[:50],
                )

            # 降级：返回能力清单
            return self._build_engine_capability_response(agent_key, engine_obj, methods, query)
        except Exception as e:
            logger.warning("engine_load_failed", error=str(e))
            return {"answer": "计算引擎加载失败", "detail": str(e)}

    def _reflect_engine_methods(self, engine_obj) -> list[dict]:
        """反射引擎可用方法，返回 [{name, signature, doc}]。"""
        methods: list[dict] = []
        for name in dir(engine_obj):
            if name.startswith("_"):
                continue
            attr = getattr(engine_obj, name, None)
            if not callable(attr):
                continue
            try:
                sig = inspect.signature(attr)
                doc = inspect.getdoc(attr) or ""
                methods.append(
                    {
                        "name": name,
                        "signature": str(sig),
                        "doc": doc[:200],
                    }
                )
            except (ValueError, TypeError):
                continue
        return methods

    async def _llm_slot_fill(
        self, query: str, methods: list[dict], context: ContextPackage
    ) -> dict | None:
        """LLM slot-filling：从 query 抽取结构化入参。

        返回 {"method_name": str, "params": dict} 或 None（LLM 不可用/解析失败）。
        """
        mg = self._get_model_gateway()
        if mg is None:
            return None
        try:
            company_id_int = self._context_company_id(context)
            llm = mg.get_llm(
                model_key=self._selected_model_key(context),
                company_id=company_id_int,
            )
        except Exception as e:
            logger.warning("slot_fill_llm_unavailable", error=str(e))
            return None

        # 构建方法描述（限制数量避免 prompt 过长）
        methods_desc = "\n".join(
            f"- {m['name']}{m['signature']}: {m['doc'][:100]}" for m in methods[:10]
        )

        prompt = SLOT_FILL_PROMPT.format(methods_desc=methods_desc, query=query)
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            messages = [
                SystemMessage(content="你是参数抽取器，仅输出 JSON。"),
                HumanMessage(content=prompt),
            ]
            resp = await llm.ainvoke(messages, company_id=company_id_int)
            content = resp.content if hasattr(resp, "content") else str(resp)

            data = self._extract_json(content)
            if not data:
                logger.warning("slot_fill_parse_failed", content=content[:200])
                return None
            logger.info(
                "engine_slot_fill_result",
                method=data.get("method_name"),
                params=data.get("params"),
            )
            return data
        except Exception as e:
            logger.warning("slot_fill_llm_failed", error=str(e))
            return None

    @staticmethod
    def _filter_method_params(method, params: dict) -> dict:
        """过滤参数，只保留方法签名中存在的参数，并尝试类型转换。"""
        try:
            sig = inspect.signature(method)
            valid_params = set(sig.parameters.keys())
            filtered: dict = {}
            for k, v in params.items():
                if k not in valid_params:
                    continue
                param_obj = sig.parameters[k]
                annotation = param_obj.annotation
                # 尝试按注解做类型转换
                if annotation is int:
                    try:
                        filtered[k] = int(float(v)) if v not in (None, "", 0, "0") else 0
                    except (ValueError, TypeError):
                        filtered[k] = 0
                elif annotation is float:
                    try:
                        filtered[k] = float(v) if v not in (None, "") else 0.0
                    except (ValueError, TypeError):
                        filtered[k] = 0.0
                else:
                    filtered[k] = v
            return filtered
        except (ValueError, TypeError):
            return params

    @staticmethod
    def _format_engine_result(result, method_name: str, params: dict) -> str:
        """格式化引擎计算结果为可读字符串。"""
        try:
            if hasattr(result, "__dict__"):
                # dataclass 实例：逐字段输出
                parts = [f"引擎方法 {method_name} 计算结果:"]
                for k, v in vars(result).items():
                    parts.append(f"  {k}: {v}")
                return "\n".join(parts)
            if isinstance(result, dict):
                parts = [f"引擎方法 {method_name} 计算结果:"]
                for k, v in result.items():
                    parts.append(f"  {k}: {v}")
                return "\n".join(parts)
            if isinstance(result, list):
                parts = [f"引擎方法 {method_name} 计算结果（共 {len(result)} 项）:"]
                for i, item in enumerate(result[:10], 1):
                    parts.append(f"  {i}. {item}")
                return "\n".join(parts)
            return f"引擎方法 {method_name} 计算结果: {result}"
        except Exception:
            return f"引擎方法 {method_name} 计算完成"

    def _build_engine_capability_response(
        self,
        agent_key: str,
        engine_obj,
        methods: list[dict],
        query: str,
    ) -> dict:
        """构建引擎能力清单响应（LLM slot-filling 失败时的降级）。"""
        method_names = [m["name"] for m in methods]
        return {
            "answer": f"计算引擎 {agent_key} 已就绪，可用方法: {', '.join(method_names[:8])}",
            "detail": (
                f"查询: {query}\n"
                f"引擎: {engine_obj.__name__}\n"
                f"可用方法: {method_names}\n"
                f"（LLM slot-filling 未匹配到方法，返回能力清单）"
            ),
            "engine_agent_key": agent_key,
            "engine_methods": method_names,
            "status": "engine_ready_pending_input",
        }

    def _select_engine_agent_key(self, query: str) -> str:
        """根据查询内容选择计算引擎对应的 agent_key。"""
        query_lower = query.lower()
        # ROI/利润/转化率/点击率 → data_analysis (MetricsEngine)
        if any(
            kw in query or kw.lower() in query_lower
            for kw in ["roi", "利润", "转化率", "点击率", "ctr", "cvr"]
        ):
            return "data_analysis"
        # 物流时效/库存 → warehouse_logistics
        if any(kw in query for kw in ["物流", "时效", "库存", "周转", "运费"]):
            return "warehouse_logistics"
        # 选品评分 → product_selector
        if any(kw in query for kw in ["选品", "评分", "商品评分", "产品评分"]):
            return "product_selector"
        # 投放成本 → smart_ad_delivery
        if any(kw in query or kw.lower() in query_lower for kw in ["投放", "cpm", "cpc", "cpa"]):
            return "smart_ad_delivery"
        # 默认 → data_analysis
        return "data_analysis"

    # ==================== 审查 ====================

    async def _review_and_finalize(
        self,
        context: ContextPackage,
        path: ExecutionPath,
        result_produced: bool = False,
        final_result_text: str = "",
    ) -> AsyncIterator[dict]:
        """审查结果 → LLM 验收 → 不合格重试 → 最终输出。

        增强实现：
        1. 结构化格式校验：查询非空、intent_type 存在、result 事件非空
        2. LLM 验收层：用 LLM 对比 final_result_text 与原始 query 的 intent，
           输出 {accept: bool, reason: str}
        3. 不合格时触发重试循环（REVIEW_MAX_RETRIES=2）：
           重新执行路径，每次重试 yield {"type": "retry", "attempt": N, "reason": "..."}
        4. 重试仍不合格则标记 partial，yield {"type": "warning", "data": "..."} 后产出最终结果
        5. LLM 验收失败（model_gateway 不可用）时降级到结构化格式校验
        """
        # 初次审查
        passed, reason = await self._review_result(
            context,
            path,
            result_produced,
            final_result_text,
        )

        # 不合格则触发重试循环
        if not passed:
            for attempt in range(1, REVIEW_MAX_RETRIES + 1):
                logger.info(
                    "master_review_retry",
                    attempt=attempt,
                    reason=reason,
                    path=path.value,
                )
                yield {"type": "retry", "attempt": attempt, "reason": reason}

                # 重新执行路径
                result_produced = False
                final_result_text = ""
                try:
                    async for event in self._run_path_events(path, context):
                        if event.get("type") == "result":
                            result_produced = True
                            final_result_text = str(event.get("data", ""))
                        yield event
                except Exception as e:
                    logger.error(
                        "master_retry_path_failed",
                        path=path.value,
                        attempt=attempt,
                        error=str(e),
                    )
                    yield {"type": "error", "data": f"重试执行路径 {path.value} 失败: {str(e)}"}

                # 重新审查
                passed, reason = await self._review_result(
                    context,
                    path,
                    result_produced,
                    final_result_text,
                )
                if passed:
                    break

        # 输出审查结论
        if passed:
            yield {
                "type": "reflection",
                "data": (
                    f"审查通过: 路径={path.value}, 意图={context.intent_type}, "
                    f"结果长度={len(final_result_text)}"
                ),
            }
        else:
            # 重试次数耗尽，标记 partial 并产出最终结果
            yield {"type": "warning", "data": f"审查未通过，结果标记为 partial: {reason}"}
            yield {
                "type": "reflection",
                "data": (
                    f"审查未通过（partial）: 路径={path.value}, 意图={context.intent_type}, "
                    f"原因: {reason}"
                ),
            }

        # 最终完成事件
        yield {"type": "done"}

    async def _review_result(
        self,
        context: ContextPackage,
        path: ExecutionPath,
        result_produced: bool,
        final_result_text: str,
    ) -> tuple[bool, str]:
        """单次审查：结构化格式校验 + LLM 验收层。

        返回 (passed, reason)。LLM 不可用时降级到结构化格式校验。
        """
        query = context.rewritten_query or context.raw_input

        logger.info(
            "master_review_start",
            path=path.value,
            intent_type=context.intent_type,
            query_length=len(query),
            result_produced=result_produced,
        )

        # 1. 结构化格式校验
        issues: list[str] = []
        if not query.strip():
            issues.append("查询内容为空")
        if not getattr(context, "intent_type", ""):
            issues.append("intent_type 缺失")
        if not result_produced:
            issues.append(f"路径 {path.value} 未产出 result 事件")
        elif not final_result_text.strip():
            issues.append("result 事件内容为空")

        if issues:
            return False, "; ".join(issues)

        rag_answer_chunks = self._get_rag_answer_chunks(context)
        if (
            os.getenv("MASTER_REVIEW_SKIP_RAG_DIRECT", "true").strip().lower()
            in {"1", "true", "yes", "on"}
            and rag_answer_chunks
            and final_result_text.strip()
        ):
            logger.info(
                "master_review_skipped_rag_direct",
                path=path.value,
                intent_type=context.intent_type,
                reference_count=len(rag_answer_chunks),
            )
            return True, "RAG direct answer passed structural validation"

        # 2. LLM 验收层：对比 final_result_text 与原始 query 的 intent
        exact_reply = self._extract_exact_reply_request(context.raw_input or query)
        if exact_reply and final_result_text.strip() == exact_reply:
            logger.info(
                "master_review_skipped_exact_reply",
                path=path.value,
                intent_type=context.intent_type,
            )
            return True, "Exact reply request passed deterministic validation"

        if os.getenv("AGENTX_SMOKE_DISABLE_LLM_REVIEW", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }:
            logger.info(
                "master_review_skipped_smoke_env",
                path=path.value,
                intent_type=context.intent_type,
            )
            return True, "Smoke LLM review disabled by test env"

        llm_result = await self._llm_review(query, final_result_text, context)
        if llm_result is None:
            # LLM 不可用，降级到结构化格式校验（已通过）
            logger.info(
                "master_review_degraded",
                reason="LLM 验收层不可用，降级到结构化格式校验",
            )
            return True, "结构化校验通过（LLM 验收层降级）"

        accepted, llm_reason = llm_result
        if accepted:
            return True, llm_reason or "LLM 验收通过"
        return False, llm_reason or "LLM 验收未通过"

    async def _llm_review(
        self,
        query: str,
        final_result_text: str,
        context: ContextPackage,
    ) -> tuple[bool, str] | None:
        """LLM 验收：对比 final_result_text 与原始 query 的 intent。

        返回 (accepted, reason) 或 None（LLM 不可用/解析失败）。
        """
        mg = self._get_model_gateway()
        if mg is None:
            return None
        try:
            company_id_int = self._context_company_id(context)
            llm = mg.get_llm(
                model_key=self._selected_model_key(context),
                company_id=company_id_int,
            )
        except Exception as e:
            logger.warning("review_llm_unavailable", error=str(e))
            return None

        # 截断避免 prompt 过长
        prompt = REVIEW_PROMPT.format(
            query=query[:1000],
            result=final_result_text[:2000],
        )
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            messages = [
                SystemMessage(content="你是 AgentX 质量审查员，仅输出 JSON。"),
                HumanMessage(content=prompt),
            ]
            resp = await llm.ainvoke(messages, company_id=company_id_int)
            content = resp.content if hasattr(resp, "content") else str(resp)

            data = self._extract_json(content)
            if not data:
                logger.warning("review_llm_parse_failed", content=content[:200])
                return None
            accepted = bool(data.get("accept", True))
            reason = str(data.get("reason", ""))
            logger.info(
                "master_review_llm",
                accepted=accepted,
                reason=reason[:100],
            )
            return accepted, reason
        except Exception as e:
            logger.warning("review_llm_failed", error=str(e))
            return None

    @staticmethod
    def _extract_exact_reply_request(query: str) -> str:
        """Return the requested exact reply text for trivial echo-style requests.

        This is intentionally narrow: it only matches short, single-line prompts
        that explicitly ask the assistant to reply/output a literal string. It
        prevents simple UI smoke checks and user pings from paying the full
        multi-agent + LLM-review cost.
        """
        text = (query or "").strip()
        if not text or "\n" in text:
            return ""
        patterns = (
            r"^(?:请)?只(?:回复|输出|返回)\s*[：: ]\s*(.+?)(?:，不要添加其他内容。?|。)?$",
            r"^(?:please\s+)?(?:only\s+)?(?:reply|output|return)\s*[：: ]?\s*(.+?)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            reply = match.group(1).strip().strip("\"'“”‘’")
            if 0 < len(reply) <= 120 and "\n" not in reply:
                return reply
        return ""

    @staticmethod
    def _extract_json(content: str) -> dict | None:
        """从 LLM 文本输出中提取首个 JSON 对象。"""
        if not content:
            return None
        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, TypeError):
            return None

    # ==================== 延迟依赖获取 ====================

    def _get_model_gateway(self):
        """延迟获取 ModelGateway 实例。"""
        if self._model_gateway is not None:
            return self._model_gateway
        try:
            from app.services.model_gateway import get_global_model_gateway

            self._model_gateway = get_global_model_gateway()
            return self._model_gateway
        except Exception as e:
            logger.warning("model_gateway_unavailable", error=str(e))
            return None

    def _get_agent_runtime(self):
        """延迟获取 AgentRuntime 实例。

        AgentRuntime 初始化需要加载工具和图，开销较大，延迟到首次使用。
        """
        if self._agent_runtime is not None:
            return self._agent_runtime
        try:
            from app.runtime.orchestrator import AgentRuntime

            self._agent_runtime = AgentRuntime()
            return self._agent_runtime
        except Exception as e:
            logger.warning("agent_runtime_unavailable", error=str(e))
            return None

    def _get_master_dispatcher(self):
        """延迟获取 MasterDispatcher 实例（T2.5 接入）。"""
        if self._master_dispatcher is not None:
            return self._master_dispatcher
        try:
            from app.communication.master_dispatcher import MasterDispatcher

            self._master_dispatcher = MasterDispatcher(
                model_gateway=self._get_model_gateway(),
                agent_runtime=self._get_agent_runtime(),
            )
            return self._master_dispatcher
        except Exception as e:
            logger.warning("master_dispatcher_unavailable", error=str(e))
            return None

    def _get_tool_loader(self):
        """延迟获取 master 专属工具集加载器。"""
        if self._tool_loader is not None:
            return self._tool_loader
        try:
            self._tool_loader = MasterToolLoader()
            return self._tool_loader
        except Exception as e:
            logger.warning("tool_loader_init_failed", error=str(e))
            self._tool_loader = None
            return None


__all__ = ["MasterAgentRouter"]
