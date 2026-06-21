"""
AgentRuntime - 核心编排器
实现 Plan-Execute-Reflect 三层架构：
1. Planner: 分析任务，生成结构化执行计划
2. Executor: 按计划逐步执行，内部用 ReAct 循环
3. Reflector: 审查执行结果，不满足则回到 Executor

使用 MCP 协议动态加载工具，Skill 机制注入专业知识

文档依据: 3.docx - AI Agent 核心概念
  - Agent Loop 安全兜底: 最大10轮迭代, Token消耗阈值
  - Agent vs Workflow 选择: 固定流程用Workflow, 开放任务用Agent Loop
  - Master Orchestrator 的 Agent Loop 设计:
    初始化 → 循环迭代 → 安全兜底(max 10轮, Token阈值)
"""
# 仅导入必需的类型提示，避免运行时引入不必要的依赖
from typing import Any, Optional

# HumanMessage 用于包装用户输入为 LangChain 标准消息格式，使得后续 LLM 调用与消息处理链路统一
from langchain_core.messages import HumanMessage
# END 和 START 是 LangGraph 的特殊节点标记，前者表示图的终止，后者表示入口——不导入无法构建状态图
from langgraph.graph import END, START, StateGraph

# Import Agent
# State 是所有 RuntimeState 的基类，定义了 messages 等最基础的共享字段，子类叠加扩展字段
from app.agent import State
# 通过全局单例获取模型网关，避免在每个 Runtime 实例中重复创建网关连接
from app.services.model_gateway import get_global_model_gateway
# Redis 持久化的 checkpoint，保证服务重启后 LangGraph 状态图能从断点恢复
from app.core.checkpoint import get_redis_saver
# 使用结构化日志替代 print，日志可被采集、检索、告警
from app.core.logging import get_logger
# WorkingMemory 是跨节点的临时工作记忆，解耦了"当前在做什么"与持久化的长期记忆
from app.core.working_memory import WorkingMemory
# 三层的记忆管理器（感知/短期/长期），别名 MemoryManager 是为了编排器中书写简洁
from app.runtime.memory import ThreeLayerMemoryManager as MemoryManager
# 三个核心节点函数：加 _ 前缀表示它们是模块内部实现，编排器仅封装调用，不直接暴露
from app.runtime.nodes import executor_node as _executor_node
from app.runtime.nodes import planner_node as _planner_node
from app.runtime.nodes import reflector_node as _reflector_node
# 动态校验器在运行时根据 skill 定义的规则校验执行结果，不通过则触发 reflector 重审
from app.runtime.validator import DynamicValidator
# skill_registry 是全局单例，存储所有已注册的 Skill 模板，运行时按需匹配
from app.skills.registry import skill_registry
# ToolLoader 统一管理 MCP 工具加载，ToolLoadContext 封装了加载所需的租户、Agent 等上下文
from app.tools.loader import ToolLoader, ToolLoadContext
# traced/trace_span 提供分布式追踪能力，generate_trace_id 为每次执行生成唯一链路 ID
from app.tracking.tracer import generate_trace_id, init_tracer, traced, trace_span

# 通过模块名区分不同组件的日志来源，方便按组件过滤
logger = get_logger(__name__)

# 模块加载时初始化 tracer（幂等）—— 提前 init 是为了确保 tracing SDK 在首次调用前已完成初始化，
# 避免高并发场景下首次调用时的竞态竞争或延迟；幂等设计保证重复调用不会产生副作用
init_tracer("agentx")

# ============ Agent Loop 安全常量 ============
# 文档依据: 3.docx - Agent Loop 安全兜底
MAX_AGENT_LOOP_ITERATIONS = 10  # 最大迭代轮次，防止死循环
MAX_AGENT_TOKEN_THRESHOLD = 100000  # Token消耗阈值，超过则强制终止
TOKEN_THRESHOLD_WARNING_RATIO = 0.7  # 70%时发出警告


class AgentRuntime:
    """核心编排器 - 统一的 Agent 执行引擎"""
    # 设计为单个类而非多个子类，是为了保持 Plan-Execute-Reflect 三层之间的状态传递简单直接，
    # 避免多态带来的调试复杂度和类型推断困难

    def __init__(self):
        # __init__ 不执行任何 async 初始化，所有资源延迟到 initialize() 中按需创建——
        # 这样做的原因：(1) 支持无网络环境下的单元测试，构造不会失败；
        # (2) 允许在 initialize() 中根据 ctx 动态决定加载策略（如按租户选择不同模型）
        self.llm = None  # LLM 实例延迟注入，initialize 时按全局配置创建
        self.mcp_tools = []  # 工具列表初始为空，initialize 时通过 ToolLoader 动态加载
        self.tool_loader = ToolLoader()  # 提前创建但不加载，让 ctx 在 initialize 时传入
        self.skill_registry = skill_registry  # 直接引用全局单例，避免重复注册 skill
        self.graph = None  # LangGraph StateGraph 在 initialize 末端构建，保证 tool 和 llm 已就绪
        self._initialized = False  # 标记位：防止未初始化的 Runtime 被直接调用 run()
        self.memory_manager = None  # 三层记忆在 initialize 中创建，因为可能依赖 LLM 做语义理解
        self.validator = None  # 校验器同样需要 LLM，所以延迟到 initialize 中实例化
        self._ctx: ToolLoadContext = None  # 缓存最后一次初始化上下文，方便调试和恢复时回看
        # Token消耗追踪 - 文档依据: 3.docx
        self._total_tokens_consumed = 0  # 累计Token消耗
        self._loop_iterations = 0  # 当前循环迭代次数

    async def initialize(self, ctx: ToolLoadContext = None):
        """启动时初始化：通过 ToolLoader 加载工具、构建 StateGraph
        
        Args:
            ctx: 工具加载上下文（company_id, agent_name, trace_id, capabilities）
        """
        # 缓存 ctx 到实例变量，方便后续排查问题时回溯初始化参数
        self._ctx = ctx

        # 1. 获取 LLM
        # 通过全局网关获取 LLM 而非直接创建，是为了复用连接池和配置——网关统一管理 API key、重试策略和负载均衡
        model_gateway = get_global_model_gateway()
        self.llm = model_gateway.get_llm()
        default_model = model_gateway.get_default_model()
        logger.info("agent_runtime_model_selected", model=default_model)

        # 2. 初始化 MemoryManager
        # 三层记忆管理器在此创建而非 __init__，因为其内部可能需要 LLM 做嵌入向量化，必须等 LLM 就绪
        self.memory_manager = MemoryManager()

        # 3. 初始化 DynamicValidator
        # 校验器依赖 skill_registry 获取规则模板、依赖 LLM 做语义判断——所以放在 LLM 和 skill_registry 之后
        self.validator = DynamicValidator(self.skill_registry, self.llm)

        # 4. 使用 ToolLoader 加载工具（统一入口，替代分散的加载逻辑）
        if ctx:
            try:
                # ToolLoader.load() 内部会根据 ctx.capabilities 过滤和配置工具，实现按租户/Agent 的差异化工具集
                self.mcp_tools = await self.tool_loader.load(ctx)
                logger.info("agent_runtime_tool_loader_complete",
                            tool_count=len(self.mcp_tools),
                            capabilities=ctx.capabilities)
            except Exception as e:
                logger.warning("agent_runtime_tool_loader_failed", error=str(e))
                # 降级到 Registry —— 这是关键的容错机制：
                # 当 MCP 服务不可用时，不能因为工具加载失败就让整个 Runtime 不可用，
                # 所以回退到本地注册表，至少保证基础工具可用
                from app.tools.registry import registry  # 延迟导入：只有降级时才引入，正常路径不加载此模块
                tool_names = registry.list_registered_tools()
                self.mcp_tools = registry.get_tools_by_names(tool_names)
                logger.info("agent_runtime_registry_fallback", tool_count=len(self.mcp_tools))
        else:
            # ctx 为 None 时也走 registry 降级——适用于不需要租户隔离的简单场景
            logger.warning("agent_runtime_no_context_fallback_to_registry")
            from app.tools.registry import registry
            tool_names = registry.list_registered_tools()
            self.mcp_tools = registry.get_tools_by_names(tool_names)

        # 5. 构建 LangGraph
        # _build_graph 必须在工具、LLM、校验器全部就绪之后调用，因为图的 wrapper 函数闭包引用了 self.llm 等
        self._build_graph()

        # 标记已初始化，后续 run() 以此判断是否需要先调 initialize()
        self._initialized = True
        logger.info("agent_runtime_init_complete")

    def _build_graph(self):
        # 文档依据: 3.docx - Agent Loop 安全兜底
        # 最大重试次数改为 MAX_AGENT_LOOP_ITERATIONS (10轮)，防止无限循环
        # 同时加入 Token 消耗阈值检查，超过阈值时强制终止
        MAX_RETRIES = MAX_AGENT_LOOP_ITERATIONS

        # RuntimeState 定义在 _build_graph 内部而不是模块顶层，是因为它引用的字段含义
        # 与 AgentRuntime 的上下文紧密绑定——放在内部暗示"这个 State 只服务于当前流程图"
        class RuntimeState(State):
            plan: dict = {}  # Planner 产出的结构计划，包含 goal、steps 等
            step_results: list[dict] = []  # 每步执行的结果记录，reflector 据此判断是否通过
            reflection: dict = {}  # Reflector 的审查结论，passed 字段决定是否结束
            skill_content: str = ""  # 当命中 skill 时注入的专业知识内容，供各节点引用
            available_tools: list = []  # 当前可用的工具集，节点据此选择调用
            current_step: int = 0  # 当前执行到第几步，executor 据此决定下一步做什么
            plan_completed: bool = False  # 标志计划是否已完成，用于流式推送的终止判断
            matched_skill: str | None = None  # 命中的 skill 名称，None 表示未命中
            retry_count: int = 0  # 已重试次数，与 MAX_RETRIES 比较决定是否终止
            fingerprint_window: list = []  # 滑动窗口记录最近的行为指纹，用于检测循环/重复
            working_memory: dict = {}  # 序列化的 WorkingMemory，跨节点传递临时工作状态
            plan_history: list[dict] = []  # 保存每次 re-plan 的历史，防止重复规划同样的内容
            reflection_feedback: list[dict] = []  # 累积多次反射的反馈，供 planner 在 re-plan 时参考
            validation_errors: list[str] = []  # 校验失败的错误列表，供后续修正参考
            replan_count: int = 0  # 重规划次数，与 MAX_DYNAMIC_REPLAN 比较防止无限重规划
            # Token消耗追踪 - 文档依据: 3.docx
            total_tokens_consumed: int = 0  # 累计Token消耗量
            token_threshold_warning: bool = False  # 是否触发Token阈值警告

        workflow = StateGraph(RuntimeState)

        # 三个 wrapper 函数存在的原因是：
        # 1. 注入 trace_span，让每个节点执行都在 tracing 系统中可见
        # 2. 将 self 上的依赖（llm、tools、validator）通过闭包传递给底层节点函数，
        #    避免底层节点函数直接依赖 AgentRuntime 实例，保持节点函数的纯函数特性
        def planner_wrapper(state: RuntimeState):
            with trace_span("planner"):
                return _planner_node(state, self.llm, self.skill_registry, self.memory_manager, self.mcp_tools)

        async def executor_wrapper(state: RuntimeState):
            # 从 state 中读取 current_step 并 +1，因为 executor 每次执行的是"下一步"而非"当前步"
            step = state.get("current_step", 0) + 1
            # 每个步骤单独一个 trace span，方便在追踪系统中按步骤粒度分析耗时
            with trace_span(f"executor.step{step}"):
                return await _executor_node(state, self.llm, self.mcp_tools)

        def reflector_wrapper(state: RuntimeState):
            with trace_span("reflector"):
                return _reflector_node(state, self.llm, self.validator, self.skill_registry)

        # should_retry 是条件路由函数：
        # - 反射通过 → 直接结束，避免不必要的重试
        # - 已达最大重试 → 强制结束，防止无限循环
        # - Token消耗超过阈值 → 强制结束，防止成本失控 (文档依据: 3.docx)
        # - 否则 → 回到 executor，让 Agent 根据反馈重新执行
        def should_retry(state: RuntimeState):
            retry_count = state.get("retry_count", 0)
            reflection = state.get("reflection", {})
            total_tokens = state.get("total_tokens_consumed", 0)

            if reflection.get("passed", False):
                return END  # 通过了就不再重试，避免浪费资源
            if retry_count >= MAX_RETRIES:
                logger.warning("agent_runtime_max_retries", retry_count=retry_count)
                return END  # 达到上限强制终止，宁可返回不完美结果也不能无限跑
            # Token消耗阈值检查 - 文档依据: 3.docx
            if total_tokens >= MAX_AGENT_TOKEN_THRESHOLD:
                logger.warning("agent_runtime_token_threshold_exceeded",
                               total_tokens=total_tokens,
                               threshold=MAX_AGENT_TOKEN_THRESHOLD)
                return END  # 超过Token阈值强制终止，防止成本失控
            if total_tokens >= MAX_AGENT_TOKEN_THRESHOLD * TOKEN_THRESHOLD_WARNING_RATIO:
                logger.warning("agent_runtime_token_threshold_warning",
                               total_tokens=total_tokens,
                               ratio=TOKEN_THRESHOLD_WARNING_RATIO)
            return "executor"  # 还有机会，回到 executor 重做

        # increment_retry 作为独立的中间节点而非嵌入 executor，是为了保持状态变更的单一职责：
        # executor 只负责执行，不负责计数——重试计数是编排层面的逻辑
        def increment_retry(state: RuntimeState):
            return {
                "retry_count": state.get("retry_count", 0) + 1,
                "current_step": 0,  # 重置步骤，让 executor 从头开始
                "step_results": []  # 清空旧结果，避免与新尝试的结果混淆
            }

        workflow.add_node("planner", planner_wrapper)
        workflow.add_node("executor", executor_wrapper)
        workflow.add_node("reflector", reflector_wrapper)
        workflow.add_node("increment_retry", increment_retry)

        # 图结构: START → planner → executor → reflector → [passed? → END | retry? → END | else → increment_retry → executor]
        # 这个线性结构保证了 Plan → Execute → Reflect 的严格顺序，符合三层架构的设计意图
        workflow.add_edge(START, "planner")
        workflow.add_edge("planner", "executor")
        workflow.add_edge("executor", "reflector")
        workflow.add_conditional_edges(
            "reflector",
            should_retry,  # 条件函数决定下一步走哪个分支
            {"executor": "increment_retry", END: END}  # 注意：走 executor 前必须先经过 increment_retry
        )
        workflow.add_edge("increment_retry", "executor")  # 计数后必然回到 executor

        # compile 时注入 Redis checkpointer：即使进程崩溃重启，也能从 Redis 中的 checkpoint 恢复
        self.graph = workflow.compile(checkpointer=get_redis_saver())
        logger.info("agent_runtime_state_graph_built", max_retries=MAX_RETRIES)

    def _build_initial_state(self, message: str, agent_name: str,
                              company_id: str, trace_id: str) -> dict:
        """构建初始状态，包含 WorkingMemory"""
        # 每次 run() 都创建新的 WorkingMemory 实例，保证不同请求之间记忆隔离
        wm = WorkingMemory()
        return {
            # 用 HumanMessage 包装原始字符串，使得 LangChain 消息链各节点能统一处理
            "messages": [HumanMessage(content=message)],
            # company_context 独立成一个 dict 而非与 business 字段混合，是为了
            # 保持租户/身份信息与业务数据分离——各节点通过 key 直接访问而不需要深层解析
            "company_context": {
                "agent_name": agent_name,
                "company_id": company_id,
                "trace_id": trace_id,
            },
            "plan": {},  # 空 dict 而非 None，因为节点内部多用 .get() 取值
            "step_results": [],
            "reflection": {},
            "skill_content": "",  # 空字符串而非 None，避免下游做 None 类型判断
            "available_tools": self.mcp_tools,  # 从实例复制工具列表，后续可以按需过滤
            "current_step": 0,  # 从 0 开始，executor 会 +1 变为第一步
            "plan_completed": False,
            "retry_count": 0,
            "working_memory": wm.to_dict(),  # 序列化为 dict 存入 state，因为 LangGraph 的 checkpoint 只能存储可序列化数据
            "plan_history": [],
            "reflection_feedback": [],
            "validation_errors": [],
            "replan_count": 0,
            # Token消耗追踪 - 文档依据: 3.docx
            "total_tokens_consumed": 0,
            "token_threshold_warning": False,
        }

    def _extract_working_memory(self, state: dict) -> WorkingMemory:
        """从状态中提取或重建 WorkingMemory，同步分散字段"""
        wm_data = state.get("working_memory", {})
        # 优先从序列化数据恢复，反序列化失败则创建空白实例——保证下游代码不会拿到 None
        wm = WorkingMemory.from_dict(wm_data) if wm_data else WorkingMemory()

        # 同步：从分散字段填充 working_memory
        # 这里做"反向同步"的原因：WorkingMemory 是在 _build_initial_state 中设置的，
        # 但 state 中的 plan 可能在 Reflection 后被 _dynamic_replan 更新过，
        # 所以需要从最新的 plan 字段回填到 WorkingMemory，保持二者一致
        plan = state.get("plan", {})
        if plan and not wm.goal:
            # goal 字段优先取 goal，没有则用 description 兜底——兼容不同 planner 输出格式
            wm.goal = plan.get("goal", plan.get("description", ""))
            steps = plan.get("steps", [])
            if not wm.pending_actions and steps:
                # 将 plan 中的 steps 转换为 pending_actions，提取描述信息供记忆持久化
                wm.pending_actions = [
                    s.get("description", str(s)) for s in steps
                ]

        # current_step 转为字符串存储，因为 WorkingMemory 内部统一用字符串表示步骤索引
        wm.current_step = str(state.get("current_step", wm.current_step))
        # temporary_variables 是短期记忆的临时字段，存放执行过程中的中间数据
        wm.temporary_variables["step_results"] = state.get("step_results", [])
        wm.temporary_variables["retry_count"] = state.get("retry_count", 0)
        return wm

    def _dynamic_replan(self, state: dict, user_message: str) -> dict:
        """动态重规划：当步骤部分失败时，重新规划剩余步骤

        Args:
            state: 当前运行时状态
            user_message: 用户原始消息

        Returns:
            更新后的状态字段字典
        """
        # 最大重规划次数设为 2：与 MAX_RETRIES=3 配合，总共最多 3 次尝试（1 原始 + 2 重规划）
        MAX_DYNAMIC_REPLAN = 2
        replan_count = state.get("replan_count", 0)

        # 达到上限后不再重规划，直接标记完成并放弃——避免无限重规划消耗资源
        if replan_count >= MAX_DYNAMIC_REPLAN:
            logger.warning(
                "dynamic_replan_max_reached",
                replan_count=replan_count,
                max=MAX_DYNAMIC_REPLAN
            )
            return {
                "plan_completed": True,  # 即使没完全成功也标记完成，让流程终止
                "replan_count": replan_count,  # 不递增，保持当前值供日志记录
            }

        plan = state.get("plan", {})
        step_results = state.get("step_results", [])
        # 用集合推导式提取已成功步骤的 ID，O(1) 查找效率优于列表
        completed_step_ids = {r.get("step") for r in step_results if r.get("success", False)}
        all_steps = plan.get("steps", [])

        # 过滤出未完成的步骤：用 id 字段匹配，而非按顺序假设
        remaining_steps = [s for s in all_steps if s.get("id") not in completed_step_ids]
        if not remaining_steps:
            # 所有步骤都已完成，没必要重规划——直接结束
            logger.info("dynamic_replan_no_remaining_steps")
            return {"plan_completed": True, "replan_count": replan_count}

        reflection_feedback = state.get("reflection_feedback", [])
        if reflection_feedback:
            # 有反馈时才记录，无反馈的重规划可能是步骤级故障而非质量审查触发
            logger.info("dynamic_replan_with_feedback", feedback_count=len(reflection_feedback))

        # 用 dict(plan) 浅拷贝而非直接修改原 plan，避免 LangGraph 状态追踪中的引用副作用
        updated_plan = dict(plan)
        updated_plan["steps"] = remaining_steps  # 只保留未完成的步骤

        # 将旧 plan 追加到历史中，方便后续分析和避免重复规划同一内容
        plan_history = state.get("plan_history", [])
        plan_history.append(updated_plan)

        logger.info(
            "dynamic_replan_executed",
            replan_count=replan_count + 1,
            remaining_steps=len(remaining_steps),
            completed_steps=len(completed_step_ids),
        )

        return {
            "plan": updated_plan,
            "step_results": [],  # 清空旧结果，让 executor 在新 plan 下重新执行
            "current_step": 0,  # 重置步骤游标，从第一步重新开始
            "plan_completed": False,  # 新 plan 尚未执行，标记为未完成
            "replan_count": replan_count + 1,  # 递增计数器
            "plan_history": plan_history,
        }

    def _select_agent_mode_by_llm(self, user_message: str) -> str:
        """使用 LLM 分类用户意图以选择 Agent 模式

        模式类型：
        - workflow: 明确的业务流程（如生成报告、审批流程）
        - agent: 需要自主决策的开放任务
        - engine_first: 优先使用检索引擎获取信息
        - hybrid: 混合模式，需要多种能力

        Args:
            user_message: 用户消息

        Returns:
            模式字符串: 'workflow', 'agent', 'engine_first', 'hybrid'
        """
        try:
            # LLM 未初始化时直接走关键词降级——此时不能用 LLM 分类，降级是最安全的选项
            if not self.llm:
                return self._select_agent_mode_fallback(user_message)

            # 用中文 prompt 而非英文：因为用户消息是中文，LLM 在中文上下文中分类更准确
            prompt = f"""你是一个任务分类专家。请根据用户消息，将其分类为以下模式之一：

- workflow: 明确的业务流程，有固定的步骤（如生成报告、审批流程、数据导出）
- agent: 需要自主决策的开放式任务（如分析问题、制定策略、复杂推理）
- engine_first: 优先需要检索或查询信息（如搜索、查找、查询数据）
- hybrid: 混合模式，需要多种能力组合

仅输出模式名称（workflow、agent、engine_first 或 hybrid），不要输出其他内容。

用户消息: {user_message}

模式:"""

            # 延迟导入 HumanMessage, SystemMessage：这两个只在 LLM 分类路径中使用，
            # 如果走 fallback 路径则不需要加载，减少不必要的模块导入
            from langchain_core.messages import HumanMessage, SystemMessage
            # SystemMessage 用于设定角色约束，限制 LLM 输出范围为单个词，防止输出多余解释
            response = self.llm.invoke([
                SystemMessage(content="你是一个任务分类专家。仅输出一个词作为分类结果。"),
                HumanMessage(content=prompt)
            ])

            # 用 hasattr 防御性检查 content 属性：不同 LLM 实现的 response 对象结构可能不同
            content = response.content.strip().lower() if hasattr(response, 'content') else ""
            # 用集合做白名单校验：即使 LLM 输出了奇怪的内容，也能拦截并走降级
            valid_modes = {"workflow", "agent", "engine_first", "hybrid"}
            if content in valid_modes:
                logger.info("agent_mode_selected_by_llm", mode=content)
                return content

            # LLM 返回了不在白名单中的内容——记录后走关键词降级，保证始终返回有效模式
            logger.info("agent_mode_fallback_invalid_llm_output", output=content)
            return self._select_agent_mode_fallback(user_message)

        except Exception as e:
            # LLM 调用异常（如超时、限流）时走降级——模式选择不能因为 LLM 故障就阻塞整个任务
            logger.warning("agent_mode_llm_classification_failed", error=str(e))
            return self._select_agent_mode_fallback(user_message)

    @staticmethod
    def _select_agent_mode_fallback(user_message: str) -> str:
        """关键词匹配的降级模式选择"""
        # 声明为 @staticmethod 而非普通方法：关键词匹配不依赖任何实例状态，
        # 这样做的好处是可以在 LLM 尚未初始化的路径中安全调用，不会因为 self 未就绪而出错
        workflow_keywords = ["流程", "步骤", "审批", "导出", "报告", "生成", "批量"]
        agent_keywords = ["分析", "怎么", "如何", "为什么", "建议", "策略", "优化"]
        engine_keywords = ["搜索", "查找", "查询", "检索", "找", "有哪些"]

        # engine_first 优先级最高：用户明确要搜索/查询时，应该先用引擎获取信息，
        # 这比盲目启动 Agent 自主推理更高效
        for kw in engine_keywords:
            if kw in user_message:
                return "engine_first"
        # workflow 次之：如果用户提到了明确的业务流程关键词，按固定步骤执行更可控
        for kw in workflow_keywords:
            if kw in user_message:
                return "workflow"
        # agent 再次之：分析/推理类关键词触发自主决策模式
        for kw in agent_keywords:
            if kw in user_message:
                return "agent"

        # 无匹配时默认 hybrid：这是最灵活的模式，能应对各种未知类型的问题
        return "hybrid"

    async def run(self, message: str, agent_name: str = "", company_id: str = "") -> dict[str, Any]:
        # 用 company_id + agent_name 组合生成 trace_id，保证同租户同 Agent 的请求可追踪到同一链路
        trace_id = generate_trace_id(company_id, agent_name)
        # 惰性初始化：首次 run() 时自动初始化，让调用方无需关心初始化时机
        if not self._initialized:
            ctx = ToolLoadContext(
                company_id=company_id,
                agent_name=agent_name,
                trace_id=trace_id,
            )
            await self.initialize(ctx)

        # 将整个执行包裹在 trace_span 中，使得 tracing 系统能按 agent_runtime 维度聚合
        with trace_span("agent_runtime", {"trace_id": trace_id}):
            initial_state = self._build_initial_state(
                message, agent_name, company_id, trace_id
            )

            # ainvoke 是异步的图执行方法：内部会按图的拓扑结构依次（或必要时并行）调用各节点
            # thread_id 作为 checkpoint 的隔离键：同 trace_id 的多次调用共享状态，不同 trace_id 完全隔离
            result = await self.graph.ainvoke(initial_state, {
                "configurable": {"thread_id": trace_id}
            })

        # 从结果中解包各字段：用 .get() 而非 [] 取值，防止节点异常时 KeyError
        final_messages = result.get("messages", [])
        step_results = result.get("step_results", [])
        reflection = result.get("reflection", {})
        plan = result.get("plan", {})
        working_memory = self._extract_working_memory(result)

        return {
            # 取最后一条消息作为最终回复：LangGraph 的 messages 列表末尾是最新状态
            "response": final_messages[-1].content if final_messages else "",
            "plan": plan,
            "step_results": step_results,
            "reflection": reflection,
            # reflection.get("passed", True) 的默认值是 True：如果反射节点未产出结果，
            # 乐观地认为执行成功，避免因 missing key 导致整体失败
            "success": reflection.get("passed", True),
            "working_memory": working_memory.to_dict(),
        }

    async def run_stream(self, message: str, agent_name: str = "", company_id: str = ""):
        # 流式执行的 trace_id 和懒初始化逻辑与 run() 相同
        trace_id = generate_trace_id(company_id, agent_name)
        if not self._initialized:
            ctx = ToolLoadContext(
                company_id=company_id,
                agent_name=agent_name,
                trace_id=trace_id,
            )
            await self.initialize(ctx)

        with trace_span("agent_runtime_stream", {"trace_id": trace_id}):
            initial_state = self._build_initial_state(
                message, agent_name, company_id, trace_id
            )

        # astream 是异步生成器，每走完一个节点就 yield 一次中间状态——
        # 这样前端可以实时看到 planner 产出的计划、executor 每步的结果，而不是等到全部完成后一次性返回
        async for event in self.graph.astream(initial_state, {
            "configurable": {"thread_id": trace_id}
        }):
            # LangGraph astream 的事件格式是 {node_name: node_output}，取第一个 key 作为节点名
            node_name = list(event.keys())[0]
            node_output = event[node_name]

            # 按节点类型分发不同格式的事件，前端根据 type 字段渲染不同的 UI 组件
            if node_name == "planner":
                plan = node_output.get("plan", {})
                yield {"type": "plan", "data": plan}

            elif node_name == "executor":
                step_results = node_output.get("step_results", [])
                if step_results:
                    # 只推送最新的那一步结果，避免重复推送历史步骤
                    latest = step_results[-1]
                    yield {
                        "type": "step_executed",
                        "step": latest.get("step"),
                        "description": latest.get("description"),
                        "tool_used": latest.get("tool_used"),
                        "result": latest.get("result")
                    }

            elif node_name == "reflector":
                reflection = node_output.get("reflection", {})
                yield {"type": "reflection", "data": reflection}

            elif node_name == "increment_retry":
                # 重试事件让前端知道 Agent 正在重新尝试，显示加载状态
                yield {"type": "retry", "count": node_output.get("retry_count")}

        # done 事件作为流结束标记，前端据此关闭 loading 动画或展示最终结果
        yield {"type": "done"}

    @property
    def initialized(self) -> bool:
        # 用 @property 装饰而非直接公开 _initialized：一是 Python 惯例，二是未来可以在此加入额外检查逻辑
        return self._initialized

    def _check_token_safety(self) -> dict:
        """检查Token消耗安全性 - 文档依据: 3.docx

        Returns:
            {
                "safe": bool,
                "total_tokens": int,
                "threshold": int,
                "warning": bool,
                "usage_ratio": float,
            }
        """
        ratio = self._total_tokens_consumed / MAX_AGENT_TOKEN_THRESHOLD if MAX_AGENT_TOKEN_THRESHOLD > 0 else 0
        return {
            "safe": self._total_tokens_consumed < MAX_AGENT_TOKEN_THRESHOLD,
            "total_tokens": self._total_tokens_consumed,
            "threshold": MAX_AGENT_TOKEN_THRESHOLD,
            "warning": self._total_tokens_consumed >= MAX_AGENT_TOKEN_THRESHOLD * TOKEN_THRESHOLD_WARNING_RATIO,
            "usage_ratio": round(ratio, 3),
            "max_iterations": MAX_AGENT_LOOP_ITERATIONS,
            "current_iterations": self._loop_iterations,
        }

    async def recover(self, thread_id: str) -> Optional[dict[str, Any]]:
        """从 checkpoint 恢复中断的任务
        
        Args:
            thread_id: 任务的 thread_id (trace_id)
            
        Returns:
            恢复后的执行结果，如果 checkpoint 不存在则返回 None
        """
        # recover 也需要 Runtime 已初始化，因为 graph 必须已编译好
        if not self._initialized:
            await self.initialize()

        # config 的格式必须与 run() 中 ainvoke 传入的完全一致，否则 LangGraph 找不到对应的 checkpoint
        config = {"configurable": {"thread_id": thread_id}}
        
        # 检查 checkpoint 是否存在 —— 先查后调，避免 LangGraph 内部报出难以理解的错误
        saver = get_redis_saver()
        state = saver.get_tuple(config)
        if state is None:
            # checkpoint 已过期或被清理，返回 None 让调用方决定如何处理
            logger.warning("checkpoint_not_found", thread_id=thread_id)
            return None

        logger.info("agent_runtime_recovering", thread_id=thread_id)
        
        with trace_span("agent_runtime_recover", {"thread_id": thread_id}):
            # 传递 None 作为初始状态，让 LangGraph 从 checkpoint 恢复——
            # 这是 LangGraph 的标准恢复方式：ainvoke(None, config) 会从 thread_id 对应的
            # checkpoint 中读取上次中断时的状态并继续执行，而不是从头开始
            result = await self.graph.ainvoke(None, config)
        
        final_messages = result.get("messages", [])
        step_results = result.get("step_results", [])
        reflection = result.get("reflection", {})
        
        return {
            "response": final_messages[-1].content if final_messages else "",
            "step_results": step_results,
            "reflection": reflection,
            "success": reflection.get("passed", True),
            # recovered 标记为 True，让调用方区分"首次执行"与"恢复执行"两种场景
            "recovered": True,
        }
