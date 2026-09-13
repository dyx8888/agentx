"""
A2A Protocol API for AgentX Stage 22
Provides standardized Agent-to-Agent communication endpoints following Google A2A protocol
"""

import logging  # 使用标准库 logging 而非 app.core.logging，因为 A2A 作为独立协议层保持轻量
from datetime import (  # datetime/timezone：A2A 协议时间戳生成，使用 timezone-aware 的 UTC 时间（Python 3.12+ 中 utcnow() 已废弃）
    UTC,
    datetime,
)
from typing import Any  # Any 类型：A2A 协议的 payload 可以是任意 JSON 可序列化的结构

from fastapi import APIRouter, Depends, HTTPException  # FastAPI 核心组件：路由、依赖注入、HTTP 异常
from pydantic import BaseModel  # Pydantic 基类：为 A2A 协议消息提供类型安全的序列化/反序列化

from app.auth import (
    get_current_active_user,  # A2A 操作需要认证：Agent 发现和任务委派都应受身份验证保护
)
from app.communication.a2a_adapter import (
    get_a2a_adapter,  # A2A 适配器单例：封装 Agent 发现和任务委派的底层逻辑
)
from app.core.logging import get_logger
from app.database import User  # 用户模型：用于依赖注入获取当前用户信息

logger = get_logger(__name__)


A2A_PUBLIC_PREFIX = "/api/a2a"
A2A_ENDPOINTS = {
    "discovery": f"{A2A_PUBLIC_PREFIX}/agents",
    "well_known": f"{A2A_PUBLIC_PREFIX}/.well-known/agent.json",
    "delegate": f"{A2A_PUBLIC_PREFIX}/delegate",
    "delegate_task": f"{A2A_PUBLIC_PREFIX}/delegate",
    "a2a_delegate": f"{A2A_PUBLIC_PREFIX}/delegate",
    "health": f"{A2A_PUBLIC_PREFIX}/health",
}


router = APIRouter(prefix="/a2a", tags=["a2a"])  # 前缀 /a2a 区分 A2A 协议端点


# Pydantic models for A2A protocol — 定义 A2A 协议的标准消息格式
class AgentCard(BaseModel):  # 遵循 Google A2A 协议的 Agent Card 规范
    """Agent card model following A2A protocol"""

    name: str  # Agent 的显示名称
    description: str  # Agent 的功能描述，用于服务发现时展示
    capabilities: list[str]  # Agent 能力列表（如 kol_search、script_generation），用于动态匹配任务
    company_id: int  # 所属公司 ID，实现多租户下的 Agent 隔离
    status: str  # Agent 状态：active / inactive / error
    registered_at: str  # ISO 8601 注册时间，用于排序和新鲜度判断
    version: str  # Agent 版本号，便于协议升级时的兼容性处理
    protocol: str  # 协议标识（固定为 "a2a"），用于区分不同的通信协议


class TaskRequest(BaseModel):  # A2A 任务委派请求
    """Task request model for A2A protocol"""

    target_agent_name: str | None = None  # 目标 Agent 名称（而非 ID），便于人类可读的发现和路由
    target_agent: str | None = None  # 常见别名，便于普通调用方使用
    agent: str | None = None  # 简写别名
    task: str | None = None  # 自然语言任务描述，由目标 Agent 自行解析和执行
    task_description: str | None = None  # 常见别名
    message: str | None = None  # 常见别名
    task_type: str = "general"  # 任务类型标签，用于路由策略和优先级分配
    payload: dict[str, Any] | None = None  # 可选的结构化附加数据（如 JSON），传递上下文或参数


class TaskResponse(BaseModel):  # A2A 任务委派响应
    """Task response model for A2A protocol"""

    success: bool  # 任务是否成功，即使失败也返回 200 状态码保持 HTTP 层稳定
    task_id: str | None = None  # 任务追踪 ID，用于后续查询任务状态
    target_agent: str | None = None  # 实际处理任务的 Agent 名称
    message: str  # 人类可读的结果或错误描述
    timestamp: str  # ISO 8601 时间戳，用于日志关联和时序分析
    error: str | None = None  # 详细的错误信息，success=False 时提供


def _first_non_empty_text(*values) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _normalize_task_request(request: TaskRequest) -> tuple[str, str]:
    target_agent_name = _first_non_empty_text(
        request.target_agent_name,
        request.target_agent,
        request.agent,
    )
    task_message = _first_non_empty_text(
        request.task,
        request.task_description,
        request.message,
    )
    if not target_agent_name or not task_message:
        raise HTTPException(
            status_code=400,
            detail=(
                "A2A delegate requires target_agent/target_agent_name and "
                "task/task_description/message"
            ),
        )
    return target_agent_name, task_message


@router.get(
    "/.well-known/agent.json"
)  # A2A 标准发现端点，其他 Agent 可通过此端点获取当前服务的 Agent Card
async def get_agent_card(current_user: User = Depends(get_current_active_user)):
    """
    Get current service's Agent card in A2A format
    Returns agent information for discovery
    """
    try:
        # For now, return a generic agent card for the current service
        # In a full implementation, this would return the specific agent's card
        agent_card = {
            "name": "AgentX Service",  # 服务名称：用于在 Agent 市场中标识自己
            "description": "Multi-agent collaboration platform with A2A protocol support",
            "capabilities": [  # 服务能力清单：其他 Agent 据此判断是否能委托任务
                "kol_search",
                "script_generation",
                "performance_analysis",
                "outreach_generation",
                "delivery_tracking",
                "task_delegation",
                "a2a_communication",
            ],
            "company_id": current_user.company_id,  # 认证用户的公司 ID（get_current_active_user 已确保 current_user 非 None，无认证时 FastAPI 自动返回 401）
            "status": "active",  # 固定为 active，表示服务在线可用
            "registered_at": datetime.now(UTC).isoformat()
            + "Z",  # UTC 时间后缀 Z，符合 ISO 8601 / A2A 协议规范
            "version": "1.0.0",  # 语义化版本控制
            "protocol": "a2a",
            "endpoints": dict(A2A_ENDPOINTS),
        }

        return agent_card  # 直接返回 dict，由 FastAPI 自动序列化为 JSON

    except Exception:
        logging.exception("generate_agent_card_failed")  # 使用标准库 logging 而非 app logger
        logger.exception("operation_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/agents")  # Agent 发现端点：返回当前公司下所有可用的 Agent 卡片
async def discover_agents(current_user: User = Depends(get_current_active_user)):
    """
    Discover all agents for the current user's company
    Returns list of agent cards in A2A format
    """
    try:
        adapter = get_a2a_adapter()  # 获取 A2A 适配器单例
        agent_cards = adapter.discover_agents(
            current_user.company_id
        )  # 按公司发现 Agent（认证用户的公司 ID，无认证时 FastAPI 自动返回 401）

        return {
            "success": True,
            "count": len(agent_cards),  # 返回 Agent 数量便于前端分页判断
            "agents": agent_cards,
            "protocol": "a2a",  # 协议标识
            "endpoints": dict(A2A_ENDPOINTS),
            "timestamp": datetime.now(UTC).isoformat() + "Z",  # 返回时间戳便于缓存策略
        }

    except Exception as e:
        logging.error(f"Error discovering agents: {e}")
        logger.exception("operation_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/delegate", response_model=TaskResponse)  # A2A 任务委派端点
async def a2a_delegate_task(
    request: TaskRequest, current_user: User = Depends(get_current_active_user)
):
    """
    Delegate task to another agent using A2A protocol
    """
    try:
        target_agent_name, task_message = _normalize_task_request(request)
        adapter = get_a2a_adapter()  # 获取 A2A 适配器
        result = adapter.send_task(  # 通过适配器向目标 Agent 发送任务
            target_agent_name=target_agent_name,
            task_message=task_message,
            task_type=request.task_type,
            payload=request.payload,  # 透传结构化负载
            company_id=current_user.company_id,
        )

        return TaskResponse(
            success=result["success"],
            task_id=result.get("task_id"),  # 使用 .get() 安全获取可能不存在的字段
            target_agent=target_agent_name,
            message=result.get("message", "Task delegation completed"),
            timestamp=result.get("timestamp"),
            error=result.get("error"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error in A2A task delegation: {e}")
        return TaskResponse(  # 即使失败也返回 200，通过 success 字段区分：保持 HTTP 连接不被中断
            success=False,
            message=f"A2A delegation failed: {str(e)}",
            timestamp=datetime.now(UTC).isoformat() + "Z",  # 记录失败时间
            error=str(e),
        )


@router.get("/health")  # 健康检查端点：供负载均衡器和监控系统使用
async def a2a_health_check():
    """Health check endpoint for A2A service"""
    return {
        "status": "healthy",  # 固定返回 healthy，表示服务运行正常
        "service": "a2a",  # 服务标识
        "protocol": "google-a2a",  # 遵循 Google A2A 协议
        "version": "1.0.0",
    }
