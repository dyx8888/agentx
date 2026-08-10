"""
Planner Node - 任务规划节点
分析用户请求，结合记忆上下文和 Skill 知识生成结构化执行计划
"""
# json 模块用于解析 LLM 返回的 JSON 格式执行计划，而非手写正则，因为 LLM 输出格式不完全受控但通常包含合法 JSON 片段
import json
# Any 类型声明用于明确函数返回值为灵活字典结构，方便下游节点读取时做类型推断
from typing import Any

# HumanMessage 标记用户输入、SystemMessage 标记系统指令，LangChain 内部依赖此区分做不同的 token 处理
from langchain_core.messages import HumanMessage, SystemMessage

# State 是全局状态字典的 TypedDict 定义，保证各节点读写字段时类型一致
from app.agent import State
# enrich_system_prompt 注入鲁棒性增强指令（防注入、防护栏），在所有 prompt 进入 LLM 前统一包裹
from app.core.agent_robustness import enrich_system_prompt
# wrap_system_instructions/wrap_user_input 添加指令边界标记，防止用户输入越权污染系统指令区域
from app.core.instruction_boundary import wrap_system_instructions, wrap_user_input
# 结构化日志记录器，使用结构化字段而非字符串拼接，便于日志检索和告警规则匹配
from app.core.logging import get_logger

# 模块级日志实例，__name__ 确保日志前缀为此文件路径，方便定位日志来源
logger = get_logger(__name__)


def planner_node(state: State, llm, skill_registry, memory_manager, mcp_tools) -> dict[str, Any]:
    # 从状态中取出消息列表，messages 是 LangGraph 节点间传递的核心载体
    messages = state["messages"]
    # 取最后一条消息作为当前用户输入，因为 LangGraph 的消息列表是追加式的，最新的一条就是当前轮次的用户请求
    user_message = messages[-1].content if messages else ""

    # 从嵌套的公司上下文中提取 agent_name，用于后续技能匹配和记忆检索的过滤条件
    agent_name = state.get("company_context", {}).get("agent_name", "")
    # company_id 默认 "default" 防止 None 值导致记忆构建时 key 无效
    company_id = state.get("company_context", {}).get("company_id", "default")

    # 反射反馈是反射节点产出后回传给规划节点的闭环数据，若存在说明上一轮执行结果不满意，需要重新规划
    reflection_feedback = state.get("reflection_feedback", [])
    if reflection_feedback:
        # 记录收到的反馈条数，方便运维排查"反思-重规划"循环的执行链路
        logger.info("planner_receiving_reflection_feedback", feedback_count=len(reflection_feedback))

    # 技能匹配：基于用户消息和 agent 名称从注册中心查找最匹配的专业工作流程模板
    matched_skill = None
    if agent_name:
        # 只有当前 agent 有名称时才匹配技能，因为无名称的通用 agent 不需要专业领域流程
        matched_skill = skill_registry.match_skill(user_message, agent_name)

    # 构建全量上下文：将任务描述、公司信息、技能名打包，由 memory_manager 统一检索相关记忆和历史
    full_context = memory_manager.build_context(
        task_description=user_message,
        agent_name=agent_name,
        company_id=company_id,
        # 技能名用于过滤该技能专属的历史执行记录，提高记忆检索的相关性
        skill_name=matched_skill.name if matched_skill else None
    )

    # 初始化为空字符串，确保技能内容缺失时 prompt 拼接不会报错
    skill_content = ""
    if matched_skill:
        # 从注册中心加载该技能的完整工作流程文本（Markdown/YAML 格式），注入到 prompt 中指导 LLM 规划
        skill_content = skill_registry.load_skill_content(matched_skill.name)
        logger.info("planner_skill_matched", skill=matched_skill.name)

    # 构建包含记忆上下文、技能知识、反思反馈的完整系统提示词
    system_prompt = _build_planner_prompt_with_memory(skill_content, full_context, reflection_feedback)

    # 消息列表按照 System → Human 顺序构造，LangChain 的多轮对话模型要求 SystemMessage 在最前面
    messages_with_system = [
        # 系统指令先经过边界包裹防止注入，再经过鲁棒性增强注入防护栏规则
        SystemMessage(content=wrap_system_instructions(enrich_system_prompt(system_prompt))),
        # 用户输入同样包裹边界标记，避免用户恶意输入穿透到系统指令区域
        HumanMessage(content=wrap_user_input(user_message))
    ]
    # 同步调用 LLM，规划节点只生成计划不调用工具，所以不需要 bind_tools
    response = llm.invoke(messages_with_system)

    # 解析 LLM 返回的原始文本，提取其中的 JSON 结构作为执行计划
    plan = _parse_plan(response.content)

    # 对解析后的计划做质量验证：工具是否存在、步骤是否明确、需求是否覆盖
    validation_errors = _validate_plan(plan, user_message, mcp_tools)
    if validation_errors:
        # 验证错误用 warning 级别而非 error，因为这属于"可纠正的问题"而非"系统故障"
        logger.warning("planner_validation_errors", errors=validation_errors)

    # plan_history 记录历史计划，供审计和回溯分析使用
    plan_history = state.get("plan_history", [])
    plan_history.append(plan)

    return {
        # 解析后的结构化执行计划，下游 executor_node 依赖此字段按步执行
        "plan": plan,
        # 匹配到的技能完整内容，传递给 executor 用于指导工具选择
        "skill_content": skill_content,
        # 可用工具列表透传给 executor，避免 executor 再次查询
        "available_tools": mcp_tools,
        # step_results 初始化为空列表，executor 每完成一步追加一条
        "step_results": [],
        # current_step 从 0 开始，executor 每次递增并以此索引 plan.steps
        "current_step": 0,
        # plan_completed 标记整个计划是否执行完毕，路由节点据此决定流向
        "plan_completed": False,
        # 匹配到的技能名（可能为 None），供 reflector 做 Skill 规则校验
        "matched_skill": matched_skill.name if matched_skill else None,
        # 验证错误列表传给路由节点，若存在严重错误可直接跳到错误处理
        "validation_errors": validation_errors,
        # 历史计划快照，新增当前计划后的完整列表
        "plan_history": plan_history,
    }


def _build_planner_prompt_with_memory(skill_content: str, full_context, reflection_feedback: list = None) -> str:
    # 基础 prompt 模板：用中文指导 LLM 生成结构化 JSON 计划，限制步骤数防止计划过于复杂导致执行失控
    prompt = """
你是一位专业的任务规划专家。请根据用户的请求，生成一份详细的执行计划。

执行计划必须是 JSON 格式，包含以下字段：
{
  "steps": [
    {
      "id": 步骤编号,
      "description": "步骤描述",
      "tool": "推荐使用的工具名称（可选）",
      "expected_output": "预期输出描述"
    }
  ],
  "acceptance_criteria": [
    "验收标准1",
    "验收标准2"
  ],
  "task_summary": "任务概述"
}

要求：
1. 步骤数量应在 2-5 步之间，不宜过多
2. 每个步骤要有明确的目标和预期输出
3. 验收标准要具体、可验证
4. 如果需要使用工具，请在 tool 字段中指定工具名称

输出格式要求：
- 仅输出 JSON，不包含其他文字
- 确保 JSON 格式正确，可被 Python json.loads() 解析
"""

    # 记忆上下文注入：将记忆管理器返回的上下文文本直接附加到 prompt 末尾
    if full_context and isinstance(full_context, str) and full_context.strip():
        prompt += f"\n\n【记忆上下文】\n{full_context}"

    # 技能内容注入：将匹配到的专业工作流程模板完整贴入 prompt，让 LLM 按照该领域的最佳实践来规划步骤
    if skill_content:
        prompt += f"\n\n【专业工作流程】\n{skill_content}"

    # 反思反馈注入：若上一轮执行被 reflector 判定为不通过，将这些反馈作为"改进指令"传给 LLM
    if reflection_feedback:
        feedback_lines = []
        for fb in reflection_feedback:
            # 提取反馈类型（issue/suggestion/approval）和具体消息，拼接成结构化的反馈文本
            fb_type = fb.get("type", "")
            fb_msg = fb.get("message", "")
            feedback_lines.append(f"  [{fb_type}] {fb_msg}")
        if feedback_lines:
            # 用【审查反馈】标记明确区分于其他上下文，让 LLM 优先关注这些改进建议
            prompt += f"\n\n【审查反馈 - 请据此改进计划】\n" + "\n".join(feedback_lines)

    return prompt


def _parse_plan(content: str) -> dict:
    try:
        # 用 find/rfind 定位第一个 { 和最后一个 } 来提取 JSON 片段，因为 LLM 可能在 JSON 前后包裹 markdown 代码块标记
        start = content.find("{")
        end = content.rfind("}") + 1
        if start != -1 and end != -1:
            json_str = content[start:end]
            # 解析为 Python dict，若 JSON 格式不合法会抛出异常进入 fallback 逻辑
            return json.loads(json_str)
    except Exception:
        # 静默吞掉异常，不打断上游流程：解析失败时返回一个兜底的默认计划，确保系统不会因一次 LLM 输出格式错误而崩溃
        pass

    # 兜底计划：当 LLM 返回内容无法解析时，生成一个最小可行计划，至少保证 executor 有步骤可执行
    return {
        "steps": [{"id": 1, "description": "分析用户请求", "expected_output": "任务分析报告"}],
        "acceptance_criteria": ["任务已完成", "结果符合预期"],
        # 截取前 100 个字符作为任务摘要，避免过长内容撑爆后续 prompt
        "task_summary": content[:100]
    }


def _validate_plan(plan: dict, user_message: str, available_tools: list) -> list[str]:
    """验证规划质量：工具可用性、步骤明确性、需求覆盖度

    Args:
        plan: 解析后的执行计划
        user_message: 用户原始消息
        available_tools: 可用工具列表（LangChain StructuredTool）

    Returns:
        验证错误列表，空列表表示通过验证
    """
    errors = []
    steps = plan.get("steps", [])

    # 空步骤列表是最严重的规划失败，直接返回，后续检查无意义
    if not steps:
        errors.append("计划中没有包含任何执行步骤")
        return errors

    # 1. 工具可用性检查
    # 用 set 收集工具名，因为后续需要 O(1) 的成员检测
    available_tool_names = set()
    for t in available_tools:
        # hasattr 防御性检查：不是所有工具都一定有 name 属性（如自定义工具）
        if hasattr(t, 'name'):
            available_tool_names.add(t.name)

    for step in steps:
        tool = step.get("tool", "")
        # 只有当步骤指定了工具名且工具名不在可用集合中时才报错，空工具名允许（表示 LLM 没指定工具）
        if tool and tool not in available_tool_names:
            errors.append(f"步骤 {step.get('id', '?')} 指定的工具 '{tool}' 不在可用工具列表中")

    # 2. 步骤明确性检查
    # 描述过短（<5 字符）说明 LLM 没有给出有意义的步骤说明，这会导致 executor 无法理解要做什么
    for step in steps:
        desc = step.get("description", "")
        if not desc or len(desc.strip()) < 5:
            errors.append(f"步骤 {step.get('id', '?')} 的描述不够明确: '{desc}'")

    # 3. 需求覆盖度检查
    # 用中文逗号分割用户消息，模拟用户需求的粒度（中文用户习惯用逗号分隔多个需求点）
    user_requirements = set(user_message.strip().split("，"))
    if not user_requirements:
        # 如果分割后为空（可能用户只说了简短的一句话），则取整句作为唯一需求
        user_requirements = {user_message.strip()}

    # 将所有步骤描述拼接成一个字符串，用子串匹配判断需求是否被覆盖
    step_descriptions = " ".join(s.get("description", "") for s in steps)
    uncovered = []
    for req in user_requirements:
        # 过滤掉太短的需求片段（<3 字符），太短的片段几乎总是匹配成功，属于噪音
        if len(req) > 3 and req not in step_descriptions:
            uncovered.append(req)

    # 如果所有需求都未被覆盖且步骤只有 1 步，说明 LLM 可能根本没理解用户意图，报严重警告
    if len(uncovered) == len(user_requirements) and len(steps) <= 1:
        errors.append(f"计划可能未充分覆盖用户需求: 用户消息 '{user_message[:80]}' 未在步骤描述中体现")
    # 如果超过 50% 的需求未被覆盖，说明覆盖度严重不足，需要提醒
    elif len(uncovered) > len(user_requirements) * 0.5:
        errors.append(f"部分用户需求可能未被覆盖: {uncovered}")

    # 4. 验收标准检查
    # 验收标准为空意味着 reflector 没有可对照的检查项，无法判断执行是否成功
    acceptance_criteria = plan.get("acceptance_criteria", [])
    if not acceptance_criteria:
        errors.append("计划缺少验收标准 (acceptance_criteria)")

    return errors
