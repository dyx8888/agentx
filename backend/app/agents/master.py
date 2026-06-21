"""
Master Orchestrator Agent - 主协调器
负责意图识别、任务拆解、子Agent路由、结果汇总

设计理念：
- Master 是用户交互的单一入口，隐藏多 Agent 的复杂性
- 基于关键词规则进行意图识别，快速路由到合适的子 Agent
- 复杂任务自动拆解为多个子任务，按依赖顺序执行
- 收集子 Agent 的执行结果，格式化输出给用户
"""

import re
from typing import Any

PROMPT_VERSION = "1.0.0"
PROMPT_UPDATED = "2026-06-20"

MASTER_SYSTEM_PROMPT = """你是 AgentX 平台的 Master Orchestrator（主协调器），负责理解用户意图、调度专业子 Agent 完成任务。

## 你的角色定位
你是用户与 AgentX 平台之间的智能调度中心。你不直接执行具体业务，而是：
1. 识别用户意图，匹配最合适的子 Agent
2. 将复杂任务拆解为多个子任务
3. 协调子 Agent 按顺序执行
4. 汇总子 Agent 的结果，整合后呈现给用户

## 可调度的子 Agent
| Agent 名称 | 负责领域 | 触发关键词 |
|-----------|---------|-----------|
| kol_search | 达人搜索与推荐 | 达人、找达人、KOL、达人推荐、搜索达人、博主、网红 |
| data_analysis | 数据分析与洞察 | 数据分析、分析数据、ROI、报表、竞品、指标、趋势 |
| content_operation | 内容策划与脚本 | 脚本、文案、策划、种草、内容、短视频、直播 |
| warehouse_logistics | 仓储物流管理 | 物流、快递、发货、样品、仓储、库存 |

## 路由规则
1. 如果用户消息只匹配一个子 Agent，直接路由到该 Agent
2. 如果匹配多个子 Agent，将任务拆解为多个子任务，按依赖顺序执行
3. 如果无法匹配任何子 Agent，回复说明自己能处理的范围，引导用户提供更具体的信息

## 任务拆解原则
1. 有依赖关系的子任务必须按顺序执行（如：先分析数据，再基于数据策划脚本）
2. 无依赖关系的子任务可以并行执行
3. 每个子任务需要明确的任务描述

## 结果汇总规范
1. 按子任务执行顺序组织输出
2. 每个子 Agent 的结果独立呈现，标注来源
3. 如果某个子任务失败，说明原因但不影响其他子任务结果展示
4. 最终给出总结和建议

## 输出格式
当处理复杂任务时，按以下格式输出：

**任务概览**
- 简要说明整体任务的目标

**子任务执行结果**
1. [子Agent名称]：[执行结果]
2. [子Agent名称]：[执行结果]

**总结与建议**
- 综合各子任务的结果，给出整体建议

## 注意事项
- 始终使用中文回复
- 保持专业、友好的语气
- 如果用户的问题不清晰，主动询问澄清
- 不要编造不存在的数据或功能
"""


# ============================================================
# 意图识别规则
# ============================================================

# 关键词 → Agent 映射表
INTENT_KEYWORD_MAP: dict[str, list[str]] = {
    "kol_search": ["达人", "找达人", "kol", "达人推荐", "搜索达人", "博主", "网红", "KOL"],
    "data_analysis": ["数据分析", "分析数据", "roi", "报表", "竞品", "指标", "趋势", "数据"],
    "content_operation": ["脚本", "文案", "策划", "种草", "内容", "短视频", "直播"],
    "warehouse_logistics": ["物流", "快递", "发货", "样品", "仓储", "库存"],
}


def recognize_intent(message: str) -> list[str] | str:
    """
    从用户消息中识别意图，匹配目标 Agent
    
    Args:
        message: 用户输入消息
        
    Returns:
        如果匹配单个 Agent，返回 Agent 名称字符串
        如果匹配多个 Agent，返回 Agent 名称列表
        如果无匹配，返回 "master"（由 Master 自己处理）
    """
    message_lower = message.lower()
    matched_agents: list[str] = []

    for agent_name, keywords in INTENT_KEYWORD_MAP.items():
        for keyword in keywords:
            if keyword.lower() in message_lower:
                if agent_name not in matched_agents:
                    matched_agents.append(agent_name)
                break  # 匹配到一个关键词即加入，跳出内层循环

    if len(matched_agents) == 0:
        return "master"
    elif len(matched_agents) == 1:
        return matched_agents[0]
    else:
        return matched_agents


# ============================================================
# 任务拆解
# ============================================================

# Agent 依赖顺序：某些 Agent 的结果需要作为其他 Agent 的输入
AGENT_DEPENDENCY_ORDER = [
    "data_analysis",      # 数据分析优先（为后续决策提供依据）
    "kol_search",         # 达人搜索
    "content_operation",  # 内容策划（可能依赖数据分析结果）
    "warehouse_logistics", # 物流跟踪
]


def decompose_task(message: str, agent_names: list[str]) -> list[dict[str, str]]:
    """
    将复杂任务拆解为多个子任务
    
    Args:
        message: 用户原始消息
        agent_names: 匹配到的 Agent 名称列表
        
    Returns:
        子任务列表，每个子任务包含 agent 和 description
    """
    if len(agent_names) == 1:
        return [{"agent": agent_names[0], "description": message}]

    # 按依赖顺序排序
    sorted_agents = sorted(
        agent_names,
        key=lambda a: AGENT_DEPENDENCY_ORDER.index(a) if a in AGENT_DEPENDENCY_ORDER else 999
    )

    # Agent 责任描述
    agent_descriptions = {
        "kol_search": "搜索和推荐相关领域的达人/KOL",
        "data_analysis": "分析相关数据指标和趋势",
        "content_operation": "策划内容脚本和文案",
        "warehouse_logistics": "跟踪物流状态和仓储信息",
    }

    subtasks = []
    for agent_name in sorted_agents:
        desc = agent_descriptions.get(agent_name, f"执行{agent_name}相关任务")
        subtasks.append({
            "agent": agent_name,
            "description": f"根据用户需求「{message}」{desc}",
        })

    return subtasks


# ============================================================
# 结果汇总
# ============================================================

def aggregate_results(original_query: str, results: list[dict[str, Any]]) -> str:
    """
    汇总子 Agent 的执行结果
    
    Args:
        original_query: 用户原始问题
        results: 子任务执行结果列表，每项包含 agent 和 result
        
    Returns:
        格式化后的汇总结果
    """
    if not results:
        return f"关于「{original_query}」，暂未获取到任何执行结果。请检查子 Agent 是否可用。"

    if len(results) == 1:
        return results[0].get("result", "执行完成，但未返回具体结果。")

    # 多结果汇总
    parts = [f"**任务概览**\n针对「{original_query}」，已完成以下子任务：\n"]

    for i, r in enumerate(results, 1):
        agent_name = r.get("agent", "未知Agent")
        agent_display = {
            "kol_search": "达人搜索",
            "data_analysis": "数据分析",
            "content_operation": "内容运营",
            "warehouse_logistics": "仓储物流",
        }.get(agent_name, agent_name)
        result_text = r.get("result", "无结果")
        parts.append(f"\n**{i}. {agent_display}**")
        parts.append(f"{result_text}")

    parts.append(f"\n\n**总结与建议**\n以上为各子任务的执行结果，请根据实际需求进一步调整。")

    return "\n".join(parts)


# ============================================================
# Agent 函数
# ============================================================

async def get_agent_function():
    """
    返回 Master Orchestrator 的可调用 agent 函数
    
    这个函数被 AgentRuntime 调用，接收用户消息，执行意图识别→任务拆解→结果汇总的完整流程
    """
    async def master_agent(message: str, **kwargs) -> str:
        """
        Master Orchestrator 主入口
        
        Args:
            message: 用户输入消息
            
        Returns:
            汇总后的响应文本
        """
        # 1. 意图识别
        intent = recognize_intent(message)

        # 2. 如果意图是 "master"（无匹配），直接返回引导信息
        if intent == "master":
            return (
                "您好！我是 AgentX 的智能助手，可以帮助您处理以下业务：\n"
                "- 达人搜索与推荐（如：帮我找美妆达人）\n"
                "- 数据分析与洞察（如：分析ROI数据）\n"
                "- 内容策划与脚本（如：策划种草文案）\n"
                "- 仓储物流管理（如：查询物流状态）\n\n"
                "请告诉我您需要什么帮助？"
            )

        # 3. 统一转为列表
        agent_names = intent if isinstance(intent, list) else [intent]

        # 4. 任务拆解
        subtasks = decompose_task(message, agent_names)

        # 5. 如果只有一个子任务，直接返回提示（实际路由由 AgentRuntime 处理）
        if len(subtasks) == 1:
            return f"已识别您的需求，正在为您{subtasks[0]['description']}..."

        # 6. 多子任务，返回任务拆解概览
        task_list = "\n".join([
            f"{i}. {st['agent']}: {st['description']}"
            for i, st in enumerate(subtasks, 1)
        ])
        return f"已识别您的复杂需求，将拆解为以下子任务：\n\n{task_list}\n\n正在逐一执行..."

    return master_agent
