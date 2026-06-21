# 模块文档：eval_trigger 是进化系统的"评测驱动"入口——当评测流水线发现 Agent 指标不达标时，自动生成修复建议
# 这是 v8.7 新增的功能，将"被动等待人工反馈"扩展为"主动根据评测指标触发"
"""
Evolution Suggester Upgrade - 8.7
基于评测结果自动触发优化建议
扩展原有的 suggest_generation 能力，增加 eval-driven 进化触发
"""
import json
from dataclasses import dataclass


@dataclass
class EvalDrivenSuggestion:
    """评测驱动的优化建议"""
    agent_name: str
    # trigger_type 区分三种触发场景，因为不同场景需要不同的处理策略（知识补充 vs 工具替换 vs 根因修复）
    trigger_type: str  # "low_score", "regression", "root_cause"
    affected_metrics: dict  # 用 dict 而非固定字段，因为不同触发类型影响的指标不同，保持灵活性
    suggested_changes: str  # 纯文本建议，方便直接展示给管理员或写入 evolution_log
    root_cause_pattern: str
    # priority 分级是为了让调度器优先处理高优先级建议，避免关键问题被淹没
    priority: str  # "high", "medium", "low"
    # confidence 是 LLM 分析结果的可信度，让管理员知道这个建议有多"靠谱"
    confidence: float


def generate_from_eval_results(
    agent_name: str,
    completion_rate: float,
    tool_accuracy: float,
    root_cause_patterns: list[dict] = None,
    # 阈值使用默认值而非硬编码，是为了让不同 Agent 可以配置不同的敏感度
    threshold_completion: float = 0.80,
    threshold_accuracy: float = 0.70,
) -> list[EvalDrivenSuggestion]:
    """
    基于评测结果自动生成优化建议。
    供 EvolutionSuggester 和 CLI 调用。

    Args:
        agent_name: Agent名称
        completion_rate: 完成率
        tool_accuracy: 工具准确率
        root_cause_patterns: 根因分析结果
        threshold_completion: 完成率阈值
        threshold_accuracy: 工具准确率阈值

    Returns:
        优化建议列表
    """
    suggestions = []

    # 触发1: 低完成率
    # 完成率是最直观的指标，低于阈值意味着 Agent 可能无法完成任务，需要最高优先级处理
    if completion_rate < threshold_completion:
        suggestions.append(EvalDrivenSuggestion(
            agent_name=agent_name,
            trigger_type="low_score",
            affected_metrics={"completion_rate": completion_rate},
            suggested_changes=_get_low_completion_suggestion(completion_rate),
            root_cause_pattern="completion_failure",
            priority="high",  # 高优先级：完成率低直接影响用户体验
            confidence=0.85,  # 0.85 的置信度是基于规则判断的，不是 LLM 猜测，所以较高
        ))

    # 触发2: 低工具准确率
    # 工具准确率低意味着 Agent 选错了工具，虽然不直接导致失败，但会浪费大量 token 和用户时间
    if tool_accuracy < threshold_accuracy:
        suggestions.append(EvalDrivenSuggestion(
            agent_name=agent_name,
            trigger_type="low_score",
            affected_metrics={"tool_accuracy": tool_accuracy},
            suggested_changes=_get_low_accuracy_suggestion(tool_accuracy),
            root_cause_pattern="tool_misuse",
            priority="high",
            confidence=0.80,  # 比完成率低 0.05，因为工具准确率可能受多种因素影响，不确定性稍高
        ))

    # 触发3: 根因分析驱动
    # 根因分析提供了更细粒度的洞察，需要至少 3 个案例才触发，避免基于偶然事件做决策
    if root_cause_patterns:
        for pattern in root_cause_patterns:
            pattern_mode = pattern.get("mode", "")
            pattern_count = pattern.get("affected_count", 0)
            if pattern_count >= 3:
                suggestions.append(EvalDrivenSuggestion(
                    agent_name=agent_name,
                    trigger_type="root_cause",
                    affected_metrics={"affected_cases": pattern_count},
                    suggested_changes=pattern.get("suggestion", ""),
                    root_cause_pattern=pattern_mode,
                    # 根据影响面动态调整优先级：>=5 个案例说明是系统性问题的概率更高
                    priority="medium" if pattern_count < 5 else "high",
                    confidence=0.75,  # 根因分析置信度低于规则判断，因为涉及模式识别
                ))

    return suggestions


def _get_low_completion_suggestion(rate: float) -> str:
    # 根据完成率分段给出不同紧急程度的建议，避免一刀切
    if rate < 0.5:
        # <50% 是严重级别，建议从根本原因（Skill匹配、工具注册、Prompt设计）检查
        return (
            "严重：任务完成率极低。建议:\n"
            "1. 检查Agent是否正确匹配了Skill\n"
            "2. 验证工具是否已正确注册和配置\n"
            "3. 考虑简化任务或增加更多few-shot示例\n"
            "4. 检查System Prompt是否清晰描述了可用工具和流程"
        )
    elif rate < 0.8:
        # 50%-80% 是警告级别，建议从优化角度（模式分析、Plan-and-Solve、验收标准）入手
        return (
            "警告：任务完成率低于阈值。建议:\n"
            "1. 分析失败案例的共性模式\n"
            "2. 检查Plan-and-Solve模式是否启用\n"
            "3. 增加任务验收标准的具体性\n"
            "4. 考虑启用Reflector节点进行结果审查"
        )
    return "完成率接近阈值，建议持续监控并优化边界场景。"


def _get_low_accuracy_suggestion(rate: float) -> str:
    if rate < 0.5:
        # <50% 工具准确率说明工具描述或选择机制有严重问题，需要从基础层面排查
        return (
            "严重：工具选择准确率极低。建议:\n"
            "1. 检查工具描述是否清晰准确（五原则评分）\n"
            "2. 验证是否有工具名称与功能不匹配\n"
            "3. 考虑启用LLM增强工具描述\n"
            "4. 在System Prompt中明确各工具的使用场景"
        )
    elif rate < 0.7:
        # 50%-70% 是优化区间，聚焦于工具描述和示例的改进
        return (
            "警告：工具选择准确率低于阈值。建议:\n"
            "1. 对误选频次高的工具增加更多使用示例\n"
            "2. 考虑在System Prompt中添加工具选择指南\n"
            "3. 分析根因报告确认是规划问题还是工具描述问题"
        )
    return "工具准确率接近阈值，建议持续优化工具描述。"


def auto_trigger_evolution_on_eval(
    agent_name: str,
    eval_metrics: dict,
    suggester=None,
) -> dict:
    """
    评测后自动触发进化建议生成。
    供评测流水线和 EvolutionScheduler 调用。

    Args:
        agent_name: Agent名称
        eval_metrics: 评测指标 (completion_rate, tool_accuracy, root_causes)
        suggester: EvolutionSuggester 实例（可选）

    Returns:
        {"triggered": bool, "suggestions": [...], "applied": bool}
    """
    # 从评测指标中解构，默认值 1.0 表示"完美"——如果评测系统没提供某个指标，不触发该维度的建议
    completion_rate = eval_metrics.get("completion_rate", 1.0)
    tool_accuracy = eval_metrics.get("tool_accuracy", 1.0)
    root_causes = eval_metrics.get("root_causes", [])

    suggestions = generate_from_eval_results(
        agent_name=agent_name,
        completion_rate=completion_rate,
        tool_accuracy=tool_accuracy,
        root_cause_patterns=root_causes,
    )

    # 没有建议时不触发，返回空结果，让调用方知道"一切正常"
    if not suggestions:
        return {"triggered": False, "suggestions": [], "applied": False}

    # 如果有 suggester 实例，尝试应用建议
    # 使用 try/except 包裹 saving 逻辑，因为保存失败不应阻塞评测结果返回
    applied = False
    if suggester:
        try:
            for s in suggestions:
                if s.priority == "high":
                    # 只自动保存高优先级建议，中低优先级的留给管理员手动确认，避免产生过多噪音
                    suggester.save_suggestion_to_log(
                        agent_id=0,  # agent_id=0 表示需要从配置获取，这里留了 TODO
                        tool_name=agent_name,
                        suggestion=s.suggested_changes,
                    )
            applied = True
        except Exception:
            # 静默吞掉保存异常，不影响评测结果的返回
            pass

    # 返回结构化的结果，包含每条建议的简化信息，便于前端直接渲染
    return {
        "triggered": True,
        "suggestions": [
            {
                "trigger_type": s.trigger_type,
                "priority": s.priority,
                "suggested_changes": s.suggested_changes,
                "confidence": s.confidence,
            }
            for s in suggestions
        ],
        "applied": applied,
    }