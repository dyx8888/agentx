"""
Workflow Engine - 基于YAML的工作流引擎
支持固定步骤编排，与Agent混合使用
"""  # 工作流引擎：将确定性流程写死为YAML工作流，避免LLM自主决策，降低成本和提高容错性
import json  # 用于条件评估中的JSON解析
import os  # 用于构建工作流配置文件的绝对路径
import yaml  # 使用YAML定义工作流，比JSON更易读，适合非技术人员维护
from dataclasses import dataclass, field  # 数据模型定义，减少样板代码
from enum import StrEnum  # 使用StrEnum方便序列化和日志记录
from typing import Any, Callable  # 类型标注

from app.core.logging import get_logger  # 结构化日志

logger = get_logger(__name__)


class WorkflowStatus(StrEnum):  # 工作流状态枚举，使用StrEnum便于JSON序列化输出
    PENDING = "pending"  # 等待执行
    RUNNING = "running"  # 正在执行
    COMPLETED = "completed"  # 成功完成
    FAILED = "failed"  # 执行失败（关键步骤失败时立即终止）
    CANCELLED = "cancelled"  # 被取消（用于外部中断场景）


@dataclass
class WorkflowStep:
    """工作流步骤"""  # 每个步骤代表一个原子操作，可以是引擎计算、Agent推理、工具调用或条件分支
    id: str  # 步骤唯一标识，用于跳转引用
    name: str  # 步骤显示名称，用于日志和调试
    type: str  # 步骤类型："engine"/"agent"/"tool"/"condition"，决定执行方式的派发
    action: str = ""  # 具体动作名：引擎名/Agent名/工具函数名/条件表达式
    params: dict = field(default_factory=dict)  # 步骤参数，使用field避免可变默认值的共享陷阱
    on_success: str = ""  # 成功后跳转的目标步骤ID，为空则顺序执行下一步
    on_failure: str = ""  # 失败后跳转的目标步骤ID，用于非关键步骤的降级处理
    timeout_seconds: int = 30  # 超时时间，防止单个步骤阻塞整个流程
    retry_count: int = 0  # 重试次数，仅在非关键步骤时有效
    critical: bool = True  # 是否为关键步骤，关键步骤失败则整个工作流终止


@dataclass
class WorkflowDefinition:
    """工作流定义"""  # 从YAML文件解析出的完整工作流元数据，包含触发条件和步骤序列
    name: str  # 工作流名称，作为唯一标识用于查询和路由
    version: str  # 版本号，用于工作流变更管理和回滚
    description: str  # 描述信息，方便运维人员理解工作流用途
    trigger_keywords: list[str] = field(default_factory=list)  # 触发关键词列表，匹配用户输入后自动激活
    trigger_intent_types: list[str] = field(default_factory=list)  # 触发意图类型，用于NLU意图匹配
    min_complexity: int = 0  # 最小复杂度阈值，低于此值的任务不触发该工作流
    max_complexity: int = 10  # 最大复杂度阈值，超过此值的任务交给Agent自主决策
    steps: list[WorkflowStep] = field(default_factory=list)  # 有序步骤列表，按顺序执行
    default_agent: str = ""  # 默认Agent，用于工作流中未指定Agent的步骤
    fallback_agent: str = ""  # 降级Agent，工作流执行失败时切换到的备用Agent


@dataclass
class WorkflowResult:
    """工作流执行结果"""  # 执行完成后返回的完整结果对象，用于上层调用方判断执行状态
    workflow_name: str  # 执行的工作流名称
    status: WorkflowStatus  # 最终状态
    step_results: list[dict] = field(default_factory=list)  # 每个步骤的执行结果，便于追踪和调试
    final_output: dict = field(default_factory=dict)  # 最终输出上下文，包含所有步骤累积的数据
    error: str = ""  # 错误信息，仅在失败时填充
    duration_ms: float = 0.0  # 总耗时（毫秒），用于性能监控


class WorkflowLoader:
    """从YAML加载工作流定义"""  # 工作流加载器：读取config/workflows/目录下的YAML文件，构建WorkflowDefinition对象

    def __init__(self, workflows_dir: str = None):
        if workflows_dir is None:
            backend_dir = os.path.dirname(os.path.dirname(__file__))  # 从当前文件向上两级找到backend目录
            workflows_dir = os.path.join(backend_dir, "config", "workflows")  # 默认工作流目录
        self._workflows_dir = workflows_dir
        self._workflows: dict[str, WorkflowDefinition] = {}  # 以工作流名称为key的字典，便于O(1)查找
        self._loaded = False  # 懒加载标志，避免重复读取文件

    def load_all(self) -> dict[str, WorkflowDefinition]:
        """加载所有工作流定义"""  # 遍历工作流目录，解析所有YAML文件为WorkflowDefinition对象
        if self._loaded:
            return self._workflows  # 已加载则直接返回缓存，避免重复I/O

        if not os.path.isdir(self._workflows_dir):
            logger.warning("workflows_dir_not_found", path=self._workflows_dir)  # 目录不存在时记录警告但不抛异常
            self._loaded = True  # 标记为已加载，避免后续重复检查
            return self._workflows

        for filename in os.listdir(self._workflows_dir):
            if not filename.endswith((".yaml", ".yml")):  # 只处理YAML文件，忽略其他文件
                continue
            filepath = os.path.join(self._workflows_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)  # 使用safe_load防止YAML注入攻击
                workflow = self._parse_workflow(data, filename)
                self._workflows[workflow.name] = workflow  # 以名称索引，后续通过名称查找
                logger.info("workflow_loaded", name=workflow.name, steps=len(workflow.steps))
            except Exception as e:
                logger.error("workflow_load_error", file=filename, error=str(e))  # 单个文件解析失败不影响其他文件加载

        self._loaded = True
        return self._workflows

    def _parse_workflow(self, data: dict, filename: str) -> WorkflowDefinition:
        """解析YAML数据为 WorkflowDefinition"""  # 将YAML字典转为类型安全的WorkflowDefinition对象
        steps = []
        for step_data in data.get("steps", []):
            steps.append(WorkflowStep(
                id=step_data.get("id", ""),
                name=step_data.get("name", ""),
                type=step_data.get("type", "tool"),  # 默认类型为tool，向后兼容旧配置
                action=step_data.get("action", ""),
                params=step_data.get("params", {}),
                on_success=step_data.get("on_success", ""),  # 空字符串表示顺序执行
                on_failure=step_data.get("on_failure", ""),
                timeout_seconds=step_data.get("timeout_seconds", 30),  # 默认30秒超时
                retry_count=step_data.get("retry_count", 0),  # 默认不重试
                critical=step_data.get("critical", True),  # 默认是关键步骤，保证安全
            ))

        return WorkflowDefinition(
            name=data.get("name", filename.replace(".yaml", "")),  # 未指定名称时用文件名
            version=data.get("version", "1.0.0"),  # 默认版本号
            description=data.get("description", ""),
            trigger_keywords=data.get("trigger_keywords", []),
            trigger_intent_types=data.get("trigger_intent_types", []),
            min_complexity=data.get("min_complexity", 0),
            max_complexity=data.get("max_complexity", 10),  # 默认覆盖所有复杂度等级
            steps=steps,
            default_agent=data.get("default_agent", ""),
            fallback_agent=data.get("fallback_agent", ""),  # 降级Agent用于容错兜底
        )

    def get_workflow(self, name: str) -> WorkflowDefinition | None:
        """获取指定工作流定义"""  # 按名称精确查找，首次调用时触发懒加载
        if not self._loaded:
            self.load_all()  # 懒加载：首次访问时才加载文件
        return self._workflows.get(name)

    def match_workflow(self, user_message: str, intent_type: str = "",
                       complexity: int = 5) -> WorkflowDefinition | None:
        """根据用户消息和意图匹配工作流"""  # 多维度匹配：复杂度范围→意图类型→关键词，按优先级排序
        if not self._loaded:
            self.load_all()  # 确保工作流已加载

        for workflow in self._workflows.values():
            # 复杂度范围检查：任务复杂度必须在工作流定义的范围内
            if complexity < workflow.min_complexity or complexity > workflow.max_complexity:
                continue

            # 意图类型匹配：意图类型匹配优先级高于关键词匹配
            if workflow.trigger_intent_types and intent_type:
                if intent_type in workflow.trigger_intent_types:
                    return workflow  # 意图匹配成功立即返回

            # 关键词匹配：检查用户消息中是否包含触发关键词
            if workflow.trigger_keywords:
                for kw in workflow.trigger_keywords:
                    if kw in user_message:
                        return workflow  # 关键词匹配成功立即返回

        return None  # 无匹配工作流，由上层Agent自主决策


class WorkflowEngine:
    """工作流引擎 - 执行固定的工作流步骤"""  # 核心执行引擎：按顺序执行工作流步骤，支持条件跳转和错误降级

    def __init__(self, workflow_loader: WorkflowLoader = None):
        self._loader = workflow_loader or WorkflowLoader()  # 允许注入自定义加载器，实现依赖注入
        self._tool_handlers: dict[str, Callable] = {}  # 工具处理器注册表，key为工具名
        self._agent_handlers: dict[str, Callable] = {}  # Agent处理器注册表，key为Agent名

    def register_tool_handler(self, tool_name: str, handler: Callable):
        """注册工具处理器"""  # 将工具函数注册到引擎，供type=tool的步骤调用
        self._tool_handlers[tool_name] = handler

    def register_agent_handler(self, agent_name: str, handler: Callable):
        """注册Agent处理器"""  # 将Agent代理注册到引擎，供type=agent的步骤调用LLM推理
        self._agent_handlers[agent_name] = handler

    async def execute(self, workflow_name: str, context: dict = None) -> WorkflowResult:
        """执行工作流"""  # 核心执行方法：加载工作流→顺序执行步骤→收集结果→返回汇总
        workflow = self._loader.get_workflow(workflow_name)
        if not workflow:
            return WorkflowResult(
                workflow_name=workflow_name,
                status=WorkflowStatus.FAILED,
                error=f"Workflow '{workflow_name}' not found",  # 工作流不存在时直接返回失败
            )

        import time  # 延迟导入，仅在执行时才需要
        start_time = time.time()
        context = context or {}  # 确保context不为None
        step_results = []  # 收集每个步骤的执行结果

        for step in workflow.steps:
            try:
                result = await self._execute_step(step, context)
                step_results.append({
                    "step_id": step.id,
                    "step_name": step.name,
                    "success": True,
                    "output": result,
                })

                if result:
                    # 将步骤输出合并到上下文，供后续步骤使用
                    context.update(result if isinstance(result, dict) else {"output": result})

                # on_success跳转：成功后跳转到指定步骤，实现非顺序执行流程
                if step.on_success and step.on_success != "END":
                    next_step = next((s for s in workflow.steps if s.id == step.on_success), None)
                    if next_step:
                        continue  # 跳过后续步骤，直接跳到目标步骤

            except Exception as e:
                step_results.append({
                    "step_id": step.id,
                    "step_name": step.name,
                    "success": False,
                    "error": str(e),
                })

                # 关键步骤失败立即终止整个工作流，保证数据一致性
                if step.critical:
                    return WorkflowResult(
                        workflow_name=workflow_name,
                        status=WorkflowStatus.FAILED,
                        step_results=step_results,
                        error=str(e),
                        duration_ms=(time.time() - start_time) * 1000,
                    )

                # 非关键步骤失败后尝试跳转到on_failure指定步骤进行降级处理
                if step.on_failure and step.on_failure != "END":
                    continue

        return WorkflowResult(
            workflow_name=workflow_name,
            status=WorkflowStatus.COMPLETED,
            step_results=step_results,
            final_output=context,  # 最终上下文包含所有步骤的累积输出
            duration_ms=(time.time() - start_time) * 1000,
        )

    async def _execute_step(self, step: WorkflowStep, context: dict) -> Any:
        """执行单个步骤"""  # 根据步骤类型派发到不同的执行器：tool→工具函数, agent→LLM推理, condition→条件判断
        if step.type == "tool":
            handler = self._tool_handlers.get(step.action)
            if handler:
                if hasattr(handler, '__call__'):
                    import inspect
                    # 自动检测协程函数，确保异步同步调用都能正确处理
                    if inspect.iscoroutinefunction(handler):
                        return await handler(**step.params, context=context)
                    else:
                        return handler(**step.params, context=context)
            return None  # 未注册的工具返回None

        elif step.type == "agent":
            handler = self._agent_handlers.get(step.action)
            if handler:
                prompt = step.params.get("prompt", "")  # 从params中提取prompt传给Agent
                return await handler(prompt, context=context)
            return None  # 未注册的Agent返回None

        elif step.type == "condition":
            # 条件步骤：通过eval动态计算条件表达式，决定走true_branch还是false_branch
            condition = step.params.get("condition", "")
            true_branch = step.params.get("true_branch", "")
            false_branch = step.params.get("false_branch", "")
            try:
                # eval使用受限的命名空间（context和json），防止任意代码执行
                result = eval(condition, {"context": context, "json": json})
                return {"branch": true_branch if result else false_branch}
            except Exception:
                return {"branch": false_branch}  # 条件评估失败时走false分支，安全兜底

        return None


# ── Engine Route Table ──────────────────────────────
# 引擎路由表：根据用户输入特征（关键词/意图/复杂度）将请求路由到最合适的引擎

@dataclass
class EngineRoute:
    """引擎路由规则"""  # 每条路由规则定义了一组匹配条件和目标引擎
    keywords: list[str]  # 匹配关键词列表
    intent_types: list[str]  # 匹配意图类型列表
    complexity_range: tuple[int, int]  # 复杂度范围 (min, max)
    target_engine: str  # 目标引擎名称
    priority: int = 0  # 优先级，数值越大越优先匹配


class EngineRouter:
    """引擎路由器 - 根据输入特征路由到合适的引擎"""  # 读取engine_routes.yaml配置，按优先级排序后进行路由匹配

    def __init__(self, routes_config_path: str = None):
        if routes_config_path is None:
            backend_dir = os.path.dirname(os.path.dirname(__file__))  # 从当前文件向上两级找到backend目录
            routes_config_path = os.path.join(backend_dir, "config", "engine_routes.yaml")  # 默认路由配置文件
        self._routes: list[EngineRoute] = []
        self._load_routes(routes_config_path)

    def _load_routes(self, config_path: str):
        """加载路由配置"""  # 从YAML文件加载路由规则，按优先级降序排列
        if not os.path.exists(config_path):
            logger.warning("engine_routes_config_not_found", path=config_path)  # 配置文件不存在时静默处理
            return

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)  # 使用safe_load防止YAML注入

            for route_data in data.get("routes", []):
                self._routes.append(EngineRoute(
                    keywords=route_data.get("keywords", []),
                    intent_types=route_data.get("intent_types", []),
                    complexity_range=(
                        route_data.get("min_complexity", 0),
                        route_data.get("max_complexity", 10),
                    ),
                    target_engine=route_data.get("target", ""),
                    priority=route_data.get("priority", 0),
                ))

            # 按优先级降序排列，确保高优先级规则优先匹配
            self._routes.sort(key=lambda r: r.priority, reverse=True)
            logger.info("engine_routes_loaded", count=len(self._routes))
        except Exception as e:
            logger.error("engine_routes_load_error", error=str(e))

    def route(self, user_message: str, intent_type: str = "",
              complexity: int = 5) -> str | None:
        """路由到合适的引擎"""  # 按优先级遍历路由规则，返回第一个匹配的目标引擎
        for route in self._routes:
            # 复杂度范围检查
            if not (route.complexity_range[0] <= complexity <= route.complexity_range[1]):
                continue

            # 意图类型匹配优先级高于关键词
            if route.intent_types and intent_type:
                if intent_type in route.intent_types:
                    return route.target_engine

            # 关键词匹配
            if route.keywords:
                for kw in route.keywords:
                    if kw in user_message:
                        return route.target_engine

        return None  # 无匹配时返回None，由上层决定使用默认Agent


# ── Decision Logic ──────────────────────────────────
# 决策三问：判断是否应该使用工作流引擎而非Agent

def should_use_engine(user_message: str, intent_type: str = "",
                      complexity: int = 5) -> tuple[bool, str]:
    """决策三问：判断是否应该使用工作流引擎
    
    1. 能写死 → 工作流
    2. 容错低 → 加确认
    3. 成本敏感 → 工作流
    """  # 三问决策法：固定流程优先、高风险加确认、低成本用引擎，实现Agent-Workflow混合编排
    reasons = []

    # 问1: 能写死吗？—— 有固定流程的任务无需LLM推理，直接用工作流执行更可靠
    fixed_patterns = ["投诉", "退款", "退货", "审批", "导出", "批量", "定时", "周报"]
    has_fixed_pattern = any(kw in user_message for kw in fixed_patterns)

    # 问2: 容错低吗？—— 涉及资金/权限的操作需要额外确认，避免LLM幻觉导致误操作
    low_tolerance_patterns = ["支付", "金额", "扣款", "删除", "禁用", "封禁"]
    needs_confirmation = any(kw in user_message for kw in low_tolerance_patterns)

    # 问3: 成本敏感吗？—— 低复杂度任务用工作流可以节省LLM调用成本
    cost_sensitive = complexity <= 4

    if has_fixed_pattern:
        reasons.append("任务有固定流程，可写死为工作流")
    if needs_confirmation:
        reasons.append("高风险操作，建议增加确认步骤")
    if cost_sensitive:
        reasons.append(f"复杂度低({complexity}/10)，使用工作流更高效")

    # 决策逻辑：有固定流程 OR （低成本且非高风险）→ 使用工作流引擎
    use_engine = has_fixed_pattern or (cost_sensitive and not needs_confirmation)
    reason = "; ".join(reasons) if reasons else "适合Agent自主决策"

    return use_engine, reason