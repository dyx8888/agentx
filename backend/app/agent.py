"""
Agent 核心引擎
支持 MCP 协议 + Skill 机制 + 三大范式 (ReAct / Plan-and-Solve / Reflection)
"""

# ---- 异步支持：create_agent 为 async 函数，asyncio 是其基础依赖 ----
import asyncio

# ---- 文件系统操作：用于计算 backend 根目录路径 ----
import os

# 确保 backend 目录在 sys.path 中
# ---- sys 操作紧跟在 os 之后，因为路径注入必须在项目内部 import 之前完成 ----
import sys

# ---- Enum 而非普通 str 常量：保证模式值类型安全，IDE 可以自动补全 ----
from enum import StrEnum

# ---- Annotated：LangGraph 要求 State 中的 messages 字段附加 add_messages reducer ----
from typing import Annotated

# ---- SystemMessage 保留导入，虽然本文件未直接使用，但上层调用方通过此模块间接引用 ----
from langchain_core.messages import SystemMessage

# ---- @tool 装饰器将普通函数转为 LangChain 工具，LLM 才能识别并调用 ----
from langchain_core.tools import tool

# ---- StateGraph：构建有状态 Agent 图的核心类；END/START 是图入口出口常量 ----
from langgraph.graph import END, START, StateGraph

# ---- add_messages：合并消息列表的 reducer，避免 State 更新时覆盖历史消息 ----
from langgraph.graph.message import add_messages

# ---- ToolNode 自动处理 tool_calls 并执行对应工具；create_react_agent 一键创建 ReAct 图 ----
from langgraph.prebuilt import ToolNode, create_react_agent

# ---- TypedDict 用于定义 State 的类型结构，LangGraph 依赖类型注解推断图 schema ----
from typing_extensions import TypedDict

# ---- 向上两级（backend/app -> backend）得到 backend 根目录，用于项目内部模块导入 ----
backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# ---- 条件插入避免重复添加；insert(0) 而非 append，保证本项目的模块优先于系统同名模块被加载 ----
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# ---- 以下导入必须在 sys.path 注入之后，因为 app 包位于 backend 目录下 ----
from app.core.agent_robustness import enrich_system_prompt  # 注入反注入/防越狱等鲁棒性增强
from app.core.instruction_boundary import (
    wrap_system_instructions,  # 用分隔标记包裹指令，防止 prompt 注入
)
from app.core.logging import get_logger  # 结构化日志，便于生产环境排查
from app.skills.registry import skill_registry  # 全局 Skill 注册中心，统一管理可复用工作流
from app.tools.registry import registry  # 全局工具注册中心，按名称获取工具实例

# ---- 使用 __name__ 而非硬编码字符串，确保日志来源精确到当前模块 ----
logger = get_logger(__name__)

# ---- 与 backend_path 逻辑相同，提供模块级别的根目录常量，方便其他函数引用 ----
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class AgentMode(StrEnum):
    # ---- 继承 str + Enum：既能做字符串比较（if mode == "react"），又有类型安全 ----
    REACT = "react"  # 默认模式，思考-行动-观察循环，适合大多数简单任务
    PLAN_AND_SOLVE = "plan_solve"  # 先规划再执行，适合需要多步推理的复杂任务
    REFLECTION = "reflection"  # 先执行后自我审查再修正，适合需要高质量输出的创作类任务


class State(TypedDict):
    # ---- add_messages reducer 保证新消息追加而非覆盖，这是 LangGraph 消息累积的核心机制 ----
    messages: Annotated[list, add_messages]
    # ---- dict 而非强类型：不同公司上下文字段差异大，用 dict 保持灵活性 ----
    company_context: dict


@tool
def get_current_time() -> str:
    """Get current time in ISO format."""
    # ---- 延迟导入 datetime：此工具可能被序列化到 worker 进程，延迟导入减少启动依赖 ----
    from datetime import datetime

    # ---- utcnow().isoformat() 返回 UTC 时间字符串，统一时区避免分布式系统中时间不一致 ----
    return datetime.utcnow().isoformat()


@tool
def schedule_task(target_agent_name: str, task: str) -> str:
    """Schedule a task for asynchronous execution by another agent."""
    try:
        # ---- 延迟导入 db：避免循环导入；agent.py 被多处引用，延迟导入打破依赖环 ----
        from app.database import db

        # ---- 先查目标 Agent 是否存在：防止向不存在的 Agent 派发任务导致孤立任务记录 ----
        target_agent = db.get_agent_by_name(target_agent_name)
        if not target_agent:
            return f"Agent '{target_agent_name}' not found."
        # ---- source_agent_id=None：调度型任务没有明确的源 Agent，由系统触发 ----
        task_id = db.create_task(
            company_id=target_agent.company_id,
            source_agent_id=None,
            target_agent_name=target_agent_name,
            task_description=task,
        )
        return f"Task scheduled for {target_agent_name}. Task ID: {task_id}"
    except Exception as e:
        # ---- 捕获所有异常并返回友好消息：工具函数抛出未捕获异常会导致 LangGraph 图执行中断 ----
        return f"Error scheduling task: {str(e)}"


@tool
def a2a_delegate_task(target_agent_name: str, task: str, task_type: str = "general") -> str:
    """Delegate task to another agent using Google A2A protocol"""
    try:
        # ---- 延迟导入 a2a_adapter：A2A 协议非核心路径，延迟导入避免模块未安装时崩溃 ----
        from app.communication.a2a_adapter import get_a2a_adapter

        # ---- 每次调用获取 adapter 实例：adapter 可能持有连接状态，按需创建避免连接泄漏 ----
        adapter = get_a2a_adapter()
        result = adapter.send_task(target_agent_name, task, task_type)
        if result["success"]:
            return f"Task sent to {target_agent_name} via A2A. Task ID: {result['task_id']}"
        else:
            # ---- 区分协议失败和代码异常：协议层错误返回 error 字段，代码异常走 except ----
            return f"A2A delegation failed: {result['error']}"
    except Exception as e:
        return f"Error using A2A protocol: {str(e)}"


def get_core_tools() -> list:
    """返回所有 Agent 共享的核心内置工具列表（供 ToolLoader 使用）"""
    # 为副作用工具添加幂等保护标记
    # ---- 安全获取现有 metadata，不存在则初始化为空 dict：保护 schedule_task 已有的 metadata 不被覆盖 ----
    schedule_task.metadata = getattr(schedule_task, "metadata", {}) or {}
    # ---- side_effect=True 标记：ToolLoader 据此决定是否需要幂等保护（如重试前确认、去重检查等） ----
    schedule_task.metadata["side_effect"] = True
    a2a_delegate_task.metadata = getattr(a2a_delegate_task, "metadata", {}) or {}
    a2a_delegate_task.metadata["side_effect"] = True
    # ---- get_current_time 不放首位：它是纯查询工具无副作用，放中间不特殊，调用频率最高的 schedule_task 在索引 1 ----
    return [get_current_time, schedule_task, a2a_delegate_task]


def build_reaction_graph(agent_node, tools: list, model_gateway):
    """
    构建标准的 ReAct Agent 图。
    替代 agent.py 中 3 处重复的 StateGraph 构建代码。

    Args:
        agent_node: Agent 节点可调用函数
        tools: 工具列表
        model_gateway: ModelGateway 实例

    Returns:
        (compiled_graph, model_gateway): 编译后的图，和传入的 model_gateway
    """
    # ---- 使用统一的 State 类型：保证所有图的状态结构一致，避免跨图调用时 schema 不匹配 ----
    workflow = StateGraph(State)
    workflow.add_node("agent", agent_node)  # agent 节点负责 LLM 推理和工具调用决策
    # ---- ToolNode 用 tools 列表初始化：ToolNode 内部会根据 tool_calls 匹配并执行对应工具 ----
    workflow.add_node("tools", ToolNode(tools))
    # ---- 图入口直接连 agent：用户消息首先经过 agent 节点处理，而非 tools ----
    workflow.add_edge(START, "agent")
    # ---- 条件边基于最后一条消息是否有 tool_calls：有则进入 tools 执行，无则结束对话 ----
    workflow.add_conditional_edges(
        "agent",
        # ---- 用 lambda 而非命名函数：逻辑极简（一行判断），命名函数反而增加代码量 ----
        lambda state: "tools" if state["messages"][-1].tool_calls else END,
        {"tools": "tools", END: END},
    )
    # ---- tools 执行完毕后回到 agent：形成 ReAct 循环（思考→行动→观察→思考...） ----
    workflow.add_edge("tools", "agent")
    # ---- compile() 将图定义转为可执行运行时；返回 model_gateway 保持调用方接口统一 ----
    return workflow.compile(), model_gateway


def _select_agent_mode(message: str) -> AgentMode:
    """根据用户消息自动选择 Agent 工作模式"""
    # ---- 关键词匹配而非 LLM 判断：轻量高效，零延迟，不需要额外 API 调用 ----
    plan_keywords = ["计划", "步骤", "流程", "方案", "怎么", "如何做", "策划", "制定"]
    reflection_keywords = ["优化", "改进", "修改", "润色", "高质量", "专业", "重新"]

    # ---- Reflection 优先于 Plan：反思类关键词（如"改进方案"）更具体，不应被泛化的"方案"抢先匹配 ----
    for kw in reflection_keywords:
        if kw in message:
            return AgentMode.REFLECTION
    for kw in plan_keywords:
        if kw in message:
            return AgentMode.PLAN_AND_SOLVE
    # ---- 默认 ReAct：它是通用模式，即使误判也不会有严重后果 ----
    return AgentMode.REACT


def _build_system_prompt(
    base_prompt: str,
    mode: AgentMode,
    skill_content: str = None,  # 可选参数：不是所有 Agent 都启用了 Skill
) -> str:
    """构建完整的 System Prompt = 基础提示词 + Skill内容 + 范式指令"""
    # ---- truthy 检查而非 if base_prompt is not None：空字符串也视为无效，需回退到默认提示词 ----
    prompt = (
        base_prompt
        if base_prompt
        else (
            "You are a professional KOL marketing assistant with access to specialized tools. "
            "Use the appropriate tool for the user's request. "
            "You can chain tools (e.g., search KOLs then generate outreach). "
            "Be proactive and helpful."
        )
    )

    if skill_content:
        # ---- Skill 内容插入在范式指令之前：让 LLM 先理解业务流程，再用范式控制执行方式 ----
        prompt += f"\n\n## 当前任务的工作流程\n{skill_content}\n请严格按照以上流程逐步执行。"

    if mode == AgentMode.PLAN_AND_SOLVE:
        prompt += """

## 工作模式：Plan-and-Solve（让我们一步步思考）

在回答之前，先显式地输出你的分析过程：

### 阶段1：分析拆解
1. 理解用户的核心需求是什么？
2. 这个问题可以拆解为几个子问题？
3. 每个子问题需要用到什么工具或信息？

输出格式：
```
【分析】用户的核心需求是...，可以拆解为 N 步：
  步骤1: [具体要做的事] → 预期产出: [什么结果]
  步骤2: ...
```

### 阶段2：逐步执行
按顺序执行每个步骤，每步完成后报告中间结果。

### 阶段3：汇总输出
汇总所有步骤的结果，形成完整回答。"""

    elif mode == AgentMode.REFLECTION:
        # ---- elif 而非 if：三种模式互斥，同时一个 Agent 只能处于一种工作模式 ----
        prompt += """

## 工作模式：Reflection（先做后检再改）

按三段式输出：

### 【初步结果】
先正常执行任务，生成初稿。此时不用追求完美，重点是完整性。

### 【自我审查】
以审阅者身份检查你的初稿，逐项对照：
- 是否覆盖了用户的所有需求？
- 是否有事实性错误或遗漏？
- 格式是否符合输出规范？
- 是否有更优的表达方式？

列出发现的问题（如有）。

### 【最终版本】
基于审查意见修正后的最终输出。如果无需修改，在此说明"初稿审查通过，无需修改"并重新输出初稿。"""

    # ---- 调用链：enrich_system_prompt（鲁棒性增强）→ wrap_system_instructions（指令边界包裹），顺序不可颠倒 ----
    return wrap_system_instructions(enrich_system_prompt(prompt))


def build_system_message(company_context: dict = None, agent_prompt: str = None):
    """原有的系统消息构建函数，保持向后兼容"""
    # ---- 优先使用用户自定义 prompt：agent_prompt 非空时直接使用，否则回退到通用营销助手提示词 ----
    if agent_prompt:
        msg = agent_prompt
    else:
        msg = (
            "You are a professional KOL marketing assistant with access to specialized tools. "
            "Use the appropriate tool for the user's request. "
            "You can chain tools (e.g., search KOLs then generate outreach). "
            "Be proactive and helpful."
        )

    if company_context:
        # ---- 使用 get() 带默认值：company_context 是 dict 且字段可能缺失，避免 KeyError ----
        company_info = "\n\nCurrent Company Context:\n"
        company_info += f"- Company: {company_context.get('company_name', 'Unknown')}\n"
        company_info += f"- Brand: {company_context.get('brand_name', 'Unknown')}\n"
        company_info += f"- Category: {company_context.get('category', 'General')}\n"
        # ---- platforms 使用 get([]) 配合 join：空列表 join 后为空字符串，不会产生错误输出 ----
        platforms = ", ".join(company_context.get("platforms", []))
        company_info += f"- Active Platforms: {platforms}\n"
        msg += company_info
    # ---- 旧函数只用 enrich_system_prompt，不包裹边界指令：保持与原调用方的行为一致 ----
    return enrich_system_prompt(msg)


def get_agent_by_name(name: str):
    """原有的按名称获取 Agent 函数，保持向后兼容"""
    # ---- name 为空时直接返回默认：避免后续 __import__ 尝试加载空模块名导致 ImportError ----
    if not name:
        return build_system_message(), []
    try:
        # ---- 用 f-string 拼接模块路径：遵循项目约定，每个 Agent 在 app.agents 下独立模块 ----
        module_name = f"app.agents.{name}"
        # ---- __import__ 而非 importlib：兼容 Python 3.7+，且 fromlist=[''] 保证返回最顶层包 ----
        module = __import__(module_name, fromlist=[""])
        # ---- 所有 agent 模块统一使用 get_system_prompt / get_default_tools 命名 ----
        system_prompt = module.get_system_prompt()
        default_tools = module.get_default_tools()
        return system_prompt, default_tools
    except (ImportError, AttributeError) as e:
        # ---- 同时捕获 ImportError 和 AttributeError：模块不存在或函数命名不规范都能被兜底 ----
        logger.warning("agent_load_failed", agent_name=name, error=str(e))
        return build_system_message(), []


def get_agent_for_tools(agent_name: str):
    """根据 agent 名称构建编译后的图实例和模型网关。

    Returns:
        (compiled_app, model_gateway)
    """
    from app.services.model_gateway import get_global_model_gateway

    system_prompt, default_tools = get_agent_by_name(agent_name)
    model_gateway = get_global_model_gateway()
    llm = model_gateway.get_llm()
    tools = registry.get_tools_by_names(default_tools)
    llm_with_tools = llm.bind_tools(tools)

    def agent_node(state: State):
        messages = state["messages"]
        company_context = state.get("company_context", {})
        system_message = build_system_message(company_context, system_prompt)
        messages_with_system = [SystemMessage(content=system_message)] + messages
        response = llm_with_tools.invoke(messages_with_system)
        return {"messages": [response]}

    compiled_app, _ = build_reaction_graph(agent_node, tools, model_gateway)
    return compiled_app, model_gateway


async def create_agent(
    llm,
    system_prompt: str,
    tools: list = None,  # 直接传入工具列表，优先于 enabled_tools
    enabled_tools: list[str] = None,  # 按名称从 registry 获取工具，适合配置驱动场景
    mode: AgentMode = AgentMode.REACT,  # 默认 ReAct：最简单稳定，适合大多数场景
    skill_content: str = None,  # Skill 工作流内容，非必传
    company_api_key: str = None,  # 预留参数：未来可按公司限制 API 配额
):
    """统一的 Agent 工厂（新的异步版本）"""
    # ---- tools 优先于 enabled_tools：直接传入的工具列表信任度更高，跳过 registry 查找 ----
    if tools is None:
        # ---- enabled_tools or [] 兜底：None 时传空列表，get_tools_by_names 内部处理空列表 ----
        tools = registry.get_tools_by_names(enabled_tools or [])

    # ---- 统一使用 _build_system_prompt：保证新 Agent 都走完整的 prompt 构建流程 ----
    full_prompt = _build_system_prompt(system_prompt, mode, skill_content)

    # ---- 核心工具始终附加：get_current_time、schedule_task、a2a_delegate_task 是所有 Agent 的基础能力 ----
    core_tools = [get_current_time, schedule_task, a2a_delegate_task]
    # ---- 业务工具在前、核心工具在后：LLM 看到工具列表时，业务相关工具先出现更符合直觉 ----
    all_tools = tools + core_tools

    # ---- 使用 langgraph 预构建的 create_react_agent：一行代码完成 StateGraph + ToolNode 的组合 ----
    agent = create_react_agent(model=llm, tools=all_tools, state_modifier=full_prompt)

    # ---- 字典映射而非 if/elif：新增模式只需加键值对，符合开闭原则 ----
    mode_names = {
        AgentMode.REACT: "ReAct",
        AgentMode.PLAN_AND_SOLVE: "Plan-and-Solve",
        AgentMode.REFLECTION: "Reflection",
    }
    mode_label = mode_names[mode]
    # ---- 结构化日志记录关键参数：便于生产环境按模式/工具数量筛选和监控 ----
    logger.info(
        "agent_created", mode=mode_label, tool_count=len(all_tools), has_skill=bool(skill_content)
    )
    return agent


def create_agent_sync(
    llm,
    system_prompt: str,
    tools: list = None,
    enabled_tools: list[str] = None,
    mode: AgentMode = AgentMode.REACT,
    skill_content: str = None,
    company_api_key: str = None,
):
    """同步版本的 Agent 工厂"""
    try:
        # ---- 尝试获取当前事件循环：如果正在 async 上下文中调用此函数，get_running_loop() 会成功 ----
        asyncio.get_running_loop()
    except RuntimeError:
        # ---- RuntimeError 表示没有运行中的事件循环：说明在纯同步上下文中，可以安全用 asyncio.run() ----
        if tools is None:
            tools = registry.get_tools_by_names(enabled_tools or [])
        # ---- asyncio.run() 创建新事件循环并执行 async 函数：将异步逻辑适配为同步接口 ----
        return asyncio.run(
            create_agent(
                llm=llm,
                system_prompt=system_prompt,
                tools=tools,
                mode=mode,
                skill_content=skill_content,
                company_api_key=company_api_key,
            )
        )
    # ---- 检测到 async 上下文：防止嵌套事件循环导致死锁或未定义行为，直接抛错引导调用方使用 async 版本 ----
    raise RuntimeError(
        "create_agent_sync cannot be called from within an async context. Use create_agent instead."
    )


async def get_agent_with_skill(
    llm,
    system_prompt: str,
    skill_name: str = None,  # Skill 名称，可选，不传则等同于普通 Agent
    tools: list = None,
    enabled_tools: list[str] = None,
    company_api_key: str = None,
):
    """带 Skill 的 Agent 工厂（异步版本）"""
    # ---- 通过 skill_registry 查找 Skill 内容：注册中心统一管理，避免硬编码 Skill 路径 ----
    skill_content = skill_registry.get_skill_prompt(skill_name) if skill_name else None
    # ---- 带 Skill 的 Agent 固定使用 ReAct 模式：Skill 本身已定义工作流程，叠加范式反而冲突 ----
    return await create_agent(
        llm=llm,
        system_prompt=system_prompt,
        tools=tools,
        enabled_tools=enabled_tools,
        mode=AgentMode.REACT,
        skill_content=skill_content,
        company_api_key=company_api_key,
    )
