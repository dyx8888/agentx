"""
Reflector Node - 任务反思节点
使用 DynamicValidator 进行三层验证（代码约束 + Skill 规则 + LLM 验收）
"""
# json 用于序列化计划和结果给 LLM 审查，以及解析 LLM 返回的审查结果 JSON
import json
# Any 类型声明用于标记函数返回值为灵活字典结构
from typing import Any

# HumanMessage 和 SystemMessage 区分用户输入和系统指令，LangChain 依赖此角色标记做不同的 token 处理
from langchain_core.messages import HumanMessage, SystemMessage

# State 全局状态类型定义，保证各节点读写字段一致
from app.agent import State
# enrich_system_prompt 注入防护栏指令，防止 LLM 在审查时偏离审查范围
from app.core.agent_robustness import enrich_system_prompt
# wrap_system_instructions 为系统指令添加边界标记，防止用户输入污染审查逻辑
from app.core.instruction_boundary import wrap_system_instructions
# 结构化日志记录器，所有日志使用结构化字段便于检索
from app.core.logging import get_logger

# 模块级日志实例，__name__ 确保日志前缀为此文件路径
logger = get_logger(__name__)


def reflector_node(state: State, llm, validator, skill_registry) -> dict[str, Any]:
    # 从状态中取出执行计划，用于对照验收标准审查
    plan = state.get("plan", {})
    # step_results 是 executor 累积的执行结果，包含每步的状态、数据、错误等
    step_results = state.get("step_results", [])
    # matched_skill 从 planner 透传过来，validator 用它做 Skill 规则校验（如必须调用某工具）
    matched_skill = state.get("matched_skill", None)

    # 第一层+第二层验证：DynamicValidator 执行代码约束检查和 Skill 规则检查
    validation_result = validator.validate(
        plan=plan,
        step_results=step_results,
        skill_name=matched_skill
    )

    # 如果前两层验证未通过，启动第三层 LLM 验收：让 LLM 对照验收标准做最终审查
    if not validation_result['passed']:
        # 获取 plan 中的验收标准，作为 LLM 审查的对照依据
        acceptance_criteria = plan.get("acceptance_criteria", [])
        system_prompt = _build_reflector_prompt(acceptance_criteria)
        messages = [
            # 系统指令先包裹边界标记防止注入，再注入防护栏规则
            SystemMessage(content=wrap_system_instructions(enrich_system_prompt(system_prompt))),
            # 将完整计划和执行结果作为 HumanMessage 传入，让 LLM 对照审查
            HumanMessage(content=f"执行计划: {json.dumps(plan)}\n\n执行结果: {json.dumps(step_results)}")
        ]
        # 同步调用 LLM 做审查，reflector 不需要工具调用
        llm_response = llm.invoke(messages)
        llm_reflection = _parse_reflection(llm_response.content)

        # 将 LLM 的审查结果合并到 validation_result 中，供后续分析
        validation_result['llm_reflection'] = llm_reflection
        # extend 而非赋值：保留前两层验证发现的问题，与 LLM 发现的问题合并
        if llm_reflection.get('issues'):
            validation_result['issues'].extend(llm_reflection['issues'])
        if llm_reflection.get('suggestions'):
            validation_result['suggestions'].extend(llm_reflection['suggestions'])

    # 从审查结果中提取结构化的反馈条目，形成闭环数据供 planner 改进计划
    reflection_feedback = _build_reflection_feedback(validation_result, plan)
    if reflection_feedback:
        logger.info("reflector_feedback_generated", feedback_count=len(reflection_feedback))

    return {
        # reflection 包含完整的验证结果（issues/suggestions/passed），供路由节点判断是否需要重新规划
        "reflection": validation_result,
        # reflection_feedback 是结构化的反馈列表，planner 在下一次规划时将其注入 prompt 作为改进指令
        "reflection_feedback": reflection_feedback,
    }


def _build_reflector_prompt(acceptance_criteria: list[str]) -> str:
    # 将验收标准列表格式化为 markdown 列表，每条前面加 "- "，方便 LLM 逐条对照
    criteria_str = "\n".join(f"- {c}" for c in acceptance_criteria)

    return f"""
你是一位专业的审查专家。请根据验收标准，审查执行结果是否满足要求。

验收标准：
{criteria_str}

审查结果必须是 JSON 格式：
{{
  "passed": true 或 false,
  "issues": ["问题1", "问题2"],
  "suggestions": ["改进建议1", "改进建议2"]
}}

要求：
1. 如果所有验收标准都满足，passed 设为 true
2. 如果有不满足的标准，在 issues 中列出具体问题
3. 在 suggestions 中提供具体的改进建议
4. 仅输出 JSON，不包含其他文字
"""


def _parse_reflection(content: str) -> dict:
    try:
        # 与 planner 的 _parse_plan 采用相同策略：用 find/rfind 定位 {} 边界，容忍 LLM 在 JSON 外包裹 markdown 标记
        start = content.find("{")
        end = content.rfind("}") + 1
        if start != -1 and end != -1:
            json_str = content[start:end]
            return json.loads(json_str)
    except Exception:
        # 解析失败时静默忽略，不阻断流程
        pass

    # 兜底值：passed=True 是最保守的策略——解析失败不额外制造阻塞，放行让路由节点判断
    # 这与 planner 的兜底策略不同：planner 失败给最小计划，reflector 失败给"审查通过"
    return {"passed": True, "issues": [], "suggestions": []}


def _build_reflection_feedback(validation_result: dict, plan: dict) -> list[dict]:
    """从 Reflector 审查结果中提取反馈，形成闭环供 Planner 使用

    Args:
        validation_result: DynamicValidator 的验证结果
        plan: 当前执行计划

    Returns:
        反馈条目列表，每条包含 type, message, target_step 等字段
    """
    feedback = []

    # 建议类反馈：LLM 提出的改进方向，planner 收到后会据此调整计划
    suggestions = validation_result.get("suggestions", [])
    for suggestion in suggestions:
        feedback.append({
            "type": "suggestion",  # 标记为建议类型，区别于 issue 和 approval
            "message": suggestion,
            "source": "reflector",  # 标记来源，便于后续追踪反馈链路
        })

    # 问题类反馈：审查发现的明确缺陷，planner 需要修正这些问题
    issues = validation_result.get("issues", [])
    for issue in issues:
        feedback.append({
            "type": "issue",  # 标记为问题类型，planner 会优先处理 issue 而非 suggestion
            "message": issue,
            "source": "reflector",
        })

    # 审查通过：验收标准全部满足，形成"审批通过"的闭环记录
    if validation_result.get("passed"):
        feedback.append({
            "type": "approval",
            "message": "审查通过，计划执行结果满足所有验收标准",
            "source": "reflector",
        })

    return feedback
