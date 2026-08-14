# ==========================================
# Agent 间通信 API
# ==========================================
# 这个文件就像是一个"Agent 电话系统"
# 主要功能：
# 1. 任务委派：A Agent 把任务交给 B Agent 处理
# 2. 同事查询：一个 Agent 查看同公司有哪些同事
# 通俗地说：让 Agent 之间可以互相协作，而不是各自为政
"""
Agent Communication API for AgentX Stage 5
Handles inter-agent task delegation and communication
"""

# 导入 JSON 工具，用于解析 Agent 的工具配置
# Agent 的工具列表在数据库中是以 JSON 字符串形式存储的
import json

# FastAPI 核心工具
# APIRouter: 创建路由，注册 API 接口
# Depends: 依赖注入，自动执行前置检查（如验证登录）
# HTTPException: 抛出 HTTP 错误
# status: HTTP 状态码常量（如 404=未找到，403=禁止访问）
from fastapi import APIRouter, Depends, HTTPException, status

# LangChain 的消息类型
# HumanMessage: 用户发来的消息
# SystemMessage: 系统提示词（告诉 AI 它是什么角色）
from langchain_core.messages import HumanMessage, SystemMessage

# Pydantic 基类，定义请求和响应的数据格式
from pydantic import BaseModel

# 导入 Agent 核心功能
# build_reaction_graph: 构建 ReAct 图（AI 思考→行动→观察的循环）
# build_system_message: 构建系统提示词
# State: Agent 的状态类型
from app.agent import build_reaction_graph, build_system_message, State

# 导入认证功能，确保只有登录用户才能调用这些接口
from app.auth import get_current_active_user
from app.core.logging import get_logger

# 导入用户模型和数据库操作对象
from app.database import User, db

# 导入模型网关，统一管理 AI 模型调用
from app.services.model_gateway import get_global_model_gateway

# 导入工具注册表，根据名称获取工具
from app.tools.registry import registry

# 创建路由对象，tags=["agent_communication"] 用于 API 文档分组
router = APIRouter(tags=["agent_communication"])
logger = get_logger(__name__)

# ==========================================
# 请求和响应的数据格式定义
# ==========================================

# 任务委派的请求格式
# 当一个 Agent 要把任务交给另一个 Agent 时，需要发送这些信息
class DelegateRequest(BaseModel):
    """Request model for task delegation"""
    task: str  # 要委派的任务内容（比如 "帮我分析下上周的销售数据"）
    target_agent_id: int  # 目标 Agent 的 ID（要交给谁处理）

# 任务委派的响应格式
# 告诉调用方委派结果
class DelegateResponse(BaseModel):
    """Response model for delegation results"""
    success: bool  # 是否成功（True=成功，False=失败）
    result: str | None = None  # 成功时的执行结果
    error: str | None = None  # 失败时的错误信息

@router.post("/{agent_id:int}/delegate", response_model=DelegateResponse)
async def delegate_task_to_agent(
    agent_id: int,  # 源 Agent ID（发起委派的 Agent）
    request: DelegateRequest,
    current_user: User = Depends(get_current_active_user)
):
    """Delegate a task to a specific agent within the same company"""

    # Verify source agent exists and belongs to user's company
    source_agent = db.get_agent(agent_id)
    if not source_agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source agent not found"
        )

    if not current_user.company_id or source_agent.company_id != current_user.company_id:  # 源 Agent 必须属于当前用户公司
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Agent belongs to different company"
        )

    # Verify target agent exists and belongs to same company
    target_agent = db.get_agent(request.target_agent_id)
    if not target_agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target agent not found"
        )

    if target_agent.company_id != current_user.company_id:  # 目标 Agent 也必须属于同一公司
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delegate to agent from different company"
        )

    try:
        # --------------------------
        # 第三步：准备目标 Agent 的工具
        # --------------------------
        # Agent 的工具列表在数据库中是以 JSON 字符串存储的
        # 这里把它转换成 Python 列表，方便后续使用
        target_tools = json.loads(target_agent.tools_json)

        # --------------------------
        # 第四步：创建目标 Agent 的运行环境
        # --------------------------
        # 这就像是"为目标 Agent 准备好工作台"

        # 获取全局模型网关（统一管理 AI 模型的调用）
        mg = get_global_model_gateway()
        # 获取 AI 模型实例（比如 deepseek-chat）
        llm = mg.get_llm()
        # 根据目标 Agent 的配置，加载它需要的工具
        tools = registry.get_tools_by_names(target_tools)
        # 把工具"绑定"到 AI 模型上，这样模型在思考时就能调用这些工具
        llm_with_tools = llm.bind_tools(tools)

        # --------------------------
        # 第五步：定义目标 Agent 的思考逻辑
        # --------------------------
        # 这是一个内部函数，定义了 Agent 如何处理任务
        async def agent(state: State):
            messages = state["messages"]  # 获取消息历史（对话记录）
            company_context = state.get("company_context", {})  # 获取公司背景信息
            # 构建系统提示词，告诉 AI "你是谁、你要做什么"
            system_message = build_system_message(company_context)
            # 把系统提示词放在最前面，确保 AI 记住自己的角色
            messages_with_system = [SystemMessage(content=system_message)] + messages
            response = await llm_with_tools.ainvoke(messages_with_system)
            return {"messages": [response]}

        # 构建 ReAct 图
        # ReAct = Reason + Act（思考 + 行动）
        # 这是 Agent 的核心决策循环：
        # 1. 思考：分析任务，决定下一步做什么
        # 2. 行动：调用工具获取信息
        # 3. 观察：根据工具结果，继续思考或给出最终答案
        target_agent_app, _ = build_reaction_graph(agent, tools, mg)

        # --------------------------
        # 第六步：准备任务参数
        # --------------------------
        # 把委派的任务包装成 Agent 能理解的格式
        state = {
            "messages": [HumanMessage(content=request.task)],  # 把任务变成"用户消息"
            "company_context": {  # 传递上下文信息
                "company_name": "Current Company",  # 公司名称（可改进为真实数据）
                "delegated_from": source_agent.name,  # 标记任务来自哪个 Agent
                "original_agent": source_agent.name
            }
        }

        # --------------------------
        # 第七步：执行任务并收集结果
        # --------------------------
        result_text = ""  # 初始化结果字符串

        # 异步流式执行：实时获取 Agent 的每一步操作
        # 就像是"看直播"，实时看到 Agent 在做什么
        async for event in target_agent_app.astream_events(state, version="v1"):
            # 如果 AI 模型完成了最终回答
            if event["event"] == "on_chat_model_end":
                result_text = event["data"]["output"].content
                break  # 拿到最终答案，结束循环
            # 如果工具执行完成
            elif event["event"] == "on_tool_end":
                tool_data = event["data"]
                # 把工具执行结果追加到结果中
                result_text += f"\n[Tool Result: {tool_data.get('output', '')}]"

        # 返回成功结果
        return DelegateResponse(
            success=True,
            result=result_text
        )

    except Exception:
        logger.exception("delegate_task_failed")
        return DelegateResponse(
            success=False,
            error="Delegation failed"
        )

# ==========================================
# API 接口：获取同事 Agent 列表
# ==========================================
# GET /{agent_id}/colleagues
# 功能：让一个 Agent 查看同公司还有哪些其他 Agent
# 示例：品牌商务 Agent 想知道公司还有哪些 Agent 可以帮忙
@router.get("/{agent_id:int}/colleagues")
async def get_agent_colleagues(
    agent_id: int,  # 当前 Agent 的 ID
    current_user: User = Depends(get_current_active_user)  # 验证用户登录
):
    """Get list of colleague agents for the given agent"""

    # --------------------------
    # 第一步：验证当前 Agent
    # --------------------------
    # 查询 Agent 是否存在
    agent = db.get_agent(agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )

    # 验证 Agent 是否属于当前用户的公司
    if not current_user.company_id or agent.company_id != current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    # --------------------------
    # 第二步：获取同公司的其他 Agent
    # --------------------------
    # 查询公司内所有 Agent
    colleagues = db.get_agents_by_company(current_user.company_id)

    # 构建同事列表（排除自己）
    colleague_list = [
        {
            "id": colleague.id,
            "name": colleague.name,
            "description": colleague.description,
            "tools": json.loads(colleague.tools_json)  # 把工具列表从 JSON 转换成普通列表
        }
        for colleague in colleagues
        if colleague.id != agent_id  # 排除自己
    ]

    # 返回结果
    return {
        "agent_id": agent_id,
        "company_id": current_user.company_id,
        "colleagues": colleague_list
    }
