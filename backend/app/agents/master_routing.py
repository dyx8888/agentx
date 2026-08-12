"""
MasterAgentRouter 路由规则

变更② T2.3：master Agent 的智能路由决策逻辑。

四种执行路径：
  WORKFLOW            — 匹配预定义 SOP 模板（品牌商务/客服等流程化任务）
  REACT               — 简单单步任务（查询/解释/简单问答，master 自己调工具）
  PLAN_EXECUTE_REFLECT — 复杂多步任务（跨 Agent 协作/深度分析）
  ENGINE              — 确定性计算（ROI/利润/价格/物流时效/选品评分，零 LLM）

文档依据: 02-主Agent编排重构.md 第 4.3 节
"""

import re
from enum import StrEnum

from app.core.logging import get_logger
from app.perception.context_package import ContextPackage

logger = get_logger(__name__)


class ExecutionPath(StrEnum):
    """master Agent 的四种执行路径。

    用 StrEnum 而非 Enum：路由路径需要直接序列化为 SSE 事件字符串，
    StrEnum 的 .value 即字符串，无需额外转换。
    """

    WORKFLOW = "workflow"  # 匹配预定义 SOP 模板
    REACT = "react"  # 简单单步任务
    PLAN_EXECUTE_REFLECT = "plan_execute_reflect"  # 复杂多步任务
    ENGINE = "engine"  # 确定性计算


# ── 路由规则配置 ──────────────────────────────────────────────

# 意图/Agent → workflow 模板文件映射
# key 可以是 intent_type 或 entities中的 target_agent
# value 是 config/workflows/ 下的文件名
WORKFLOW_MAP: dict[str, str] = {
    "brand_bd": "brand_bd_workflow.json",
    "customer_service": "customer_service.yaml",
    "approval": "approval.yaml",
    "data_export": "data_export.yaml",
}

# 触发 ENGINE 路径的确定性计算关键词
# 命中任一关键词 → 走 ENGINE 路径（零 LLM，纯计算）
ENGINE_KEYWORDS: list[str] = [
    "roi",
    "ROI",
    "投资回报",
    "利润",
    "利润率",
    "毛利",
    "净利",
    "价格比较",
    "比价",
    "价格对比",
    "物流时效",
    "发货时间",
    "到货时间",
    "运费计算",
    "选品评分",
    "商品评分",
    "产品评分",
    "库存周转",
    "周转率",
    "转化率",
    "点击率",
    "ctr",
    "cvr",
    "投放成本",
    "cpm",
    "cpc",
    "cpa",
]

# 适合 REACT 路径的简单意图类型
# 这些意图通常单步可完成，无需复杂规划
SIMPLE_INTENT_TYPES: set[str] = {
    "chat",  # 明确的短聊天/回声类请求
    "search",  # 搜索/查询信息
    "knowledge",  # 知识库问答
    "general",  # 一般对话/闲聊
    "monitor",  # 短状态/健康检查类问题走轻量路径；复杂监控由实体字段拦截
}

# REACT 路径的查询长度上限：超过此长度 likely 需要多步推理
REACT_MAX_QUERY_LENGTH = 200

# ENGINE 路径的意图类型限制：只有 analyze/generate 意图才可能走 ENGINE
ENGINE_INTENT_TYPES: set[str] = {"analyze", "generate"}


def select_path(context: ContextPackage) -> ExecutionPath:
    """根据 ContextPackage 智能选择执行路径。

    路由优先级（从高到低）：
    1. WORKFLOW  — 意图匹配预定义 workflow 模板
    2. ENGINE    — 确定性计算（ROI/利润/价格等）
    3. REACT     — 简单单步任务
    4. PLAN_EXECUTE_REFLECT — 其余所有（默认兜底）

    Args:
        context: 感知层产出的综合上下文包

    Returns:
        ExecutionPath 枚举值
    """
    query = context.rewritten_query or context.raw_input
    intent_type = context.intent_type
    entities = context.intent_entities

    # === Rule 1: WORKFLOW — 意图匹配预定义模板 ===
    workflow_match = _match_workflow(intent_type, entities, context.matched_skills)
    if workflow_match:
        logger.info(
            "master_route_workflow",
            intent_type=intent_type,
            workflow=workflow_match,
        )
        return ExecutionPath.WORKFLOW

    # === Rule 2: ENGINE — 确定性计算 ===
    if _is_engine_task(query, intent_type):
        logger.info(
            "master_route_engine",
            intent_type=intent_type,
            query_length=len(query),
        )
        return ExecutionPath.ENGINE

    # === Rule 2.5: REACT — 精确回复/探活类短请求 ===
    # 这类请求不需要多 Agent 规划，也不需要加载 MCP 工具；否则 UI smoke、
    # 探活和用户简单确认会被误判成 generate 并走重路径。
    if _is_exact_reply_task(context.raw_input or query):
        logger.info(
            "master_route_react_exact_reply",
            intent_type=intent_type,
            query_length=len(query),
        )
        return ExecutionPath.REACT

    # === Rule 3: REACT — 简单单步任务 ===
    if _is_react_task(query, intent_type, entities):
        logger.info(
            "master_route_react",
            intent_type=intent_type,
            query_length=len(query),
        )
        return ExecutionPath.REACT

    # === Rule 4: PLAN_EXECUTE_REFLECT — 默认兜底 ===
    logger.info(
        "master_route_plan_execute_reflect",
        intent_type=intent_type,
        query_length=len(query),
    )
    return ExecutionPath.PLAN_EXECUTE_REFLECT


def _match_workflow(
    intent_type: str,
    entities: dict,
    matched_skills: list,
) -> str | None:
    """检查是否匹配预定义 workflow 模板。

    匹配策略：
    1. entities 中 target_agent 在 WORKFLOW_MAP 中 → 匹配
    2. matched_skills 中 skill.agent_name 在 WORKFLOW_MAP 中 → 匹配
    3. intent_type == "delegate" 且 entities 含 workflow 字段 → 匹配
    """
    # 策略 1: target_agent 在 WORKFLOW_MAP
    target_agent = entities.get("target_agent", "")
    if target_agent and target_agent in WORKFLOW_MAP:
        return WORKFLOW_MAP[target_agent]

    # 策略 2: matched_skills 的 agent_name 在 WORKFLOW_MAP
    for skill in matched_skills:
        skill_agent = getattr(skill, "agent_name", "")
        if skill_agent and skill_agent in WORKFLOW_MAP:
            return WORKFLOW_MAP[skill_agent]

    # 策略 3: entities 直接指定 workflow
    workflow_name = entities.get("workflow", "")
    if workflow_name and workflow_name in WORKFLOW_MAP:
        return WORKFLOW_MAP[workflow_name]

    return None


def _is_engine_task(query: str, intent_type: str) -> bool:
    """判断是否为确定性计算任务。

    判定条件：
    1. 意图类型是 analyze 或 generate（计算类意图）
    2. 查询中包含 ENGINE_KEYWORDS 中的关键词
    """
    if intent_type not in ENGINE_INTENT_TYPES:
        return False

    query_lower = query.lower()
    return any(keyword in query or keyword.lower() in query_lower for keyword in ENGINE_KEYWORDS)


def _is_react_task(query: str, intent_type: str, entities: dict) -> bool:
    """判断是否为简单单步任务（适合 ReAct 模式）。

    判定条件（全部满足）：
    1. 意图类型在 SIMPLE_INTENT_TYPES 中
    2. 查询长度不超过 REACT_MAX_QUERY_LENGTH
    3. entities 中无复杂字段（如 target_agent/multi_step）
    4. 无 matched_skills（有 skill 说明需要特定流程）
    """
    # 条件 1: 简单意图
    if intent_type not in SIMPLE_INTENT_TYPES:
        return False

    # 条件 2: 查询长度
    if len(query) > REACT_MAX_QUERY_LENGTH:
        return False

    # 条件 3: 无复杂实体
    return not (entities.get("target_agent") or entities.get("multi_step"))


def _is_exact_reply_task(query: str) -> bool:
    """Return True for short prompts that ask for a literal reply.

    Keep this intentionally narrow so business copywriting/generation requests
    still use normal routing, while smoke checks and simple pings avoid the
    heavy plan/execute/reflect path.
    """
    text = (query or "").strip()
    if not text or "\n" in text or len(text) > REACT_MAX_QUERY_LENGTH:
        return False
    patterns = (
        r"^(?:请)?只(?:回复|输出|返回)\s*[：: ]\s*(.+?)(?:，不要添加其他内容。?|。)?$",
        r"^(?:please\s+)?(?:only\s+)?(?:reply|output|return)\s*[：: ]?\s*(.+?)$",
    )
    return any(re.match(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


__all__ = [
    "ExecutionPath",
    "WORKFLOW_MAP",
    "ENGINE_KEYWORDS",
    "SIMPLE_INTENT_TYPES",
    "select_path",
]
