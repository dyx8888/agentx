# ==========================================
# Agent 管理 API
# ==========================================
# 这个文件就像是"人事部"
# 负责管理数据库中 Agent 的配置信息（名字、描述、会什么工具）
# 注意：这里只是管理"档案"，不负责让 Agent 真正工作
# 真正让 Agent 工作的是 app/agent.py
"""
Agents router for AgentX Stage 4
Manages digital employee (Agent) instances
"""

# JSON 工具：Agent 的工具列表需要转成 JSON 字符串才能存到数据库
import json

# FastAPI 核心工具
# APIRouter: 创建路由，注册 API 接口
# Depends: 依赖注入，自动验证用户登录状态
# HTTPException: 抛出 HTTP 错误（如 404 没找到、403 没权限）
# status: HTTP 状态码常量（方便写代码时不用记数字）
from fastapi import APIRouter, Depends, HTTPException, status

# Pydantic：定义数据格式，自动验证输入是否正确
# field_validator: 在数据进入业务逻辑前就检查合法性（比如防止恶意输入）
from pydantic import BaseModel, field_validator

from app.agents import get_active_agents, get_agent_definition

# 认证功能：确保只有已登录用户才能访问这些接口
from app.auth import get_current_active_user

# 数据库相关：
# Agent: 数据库中的 Agent 数据模型（定义了数据库表结构）
# User: 用户数据模型
# db: 数据库操作对象（提供增删改查方法）
from app.database import Agent, User, db

# 输入过滤器：防止恶意输入（如 SQL 注入、XSS 攻击）
from app.middleware.input_filter import InputFilter

# 创建路由对象，所有 API 接口都注册到这个对象上
router = APIRouter()


def _serialize_created_at(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _agent_to_response(agent) -> "AgentResponse":
    return AgentResponse(
        id=agent.id,
        company_id=agent.company_id,
        name=agent.name,
        description=agent.description,
        tools_json=agent.tools_json,
        created_at=_serialize_created_at(getattr(agent, "created_at", None)),
    )


def _catalog_agent_id(index: int) -> int:
    return -(index + 1)


def _catalog_agent_key(agent_id: int) -> str | None:
    if agent_id >= 0:
        return None
    active_keys = list(get_active_agents().keys())
    index = abs(agent_id) - 1
    if 0 <= index < len(active_keys):
        return active_keys[index]
    return None


def _catalog_tools_json(agent_key: str) -> str:
    definition = get_agent_definition(agent_key) or {}
    tools = definition.get("default_tools") or []
    if not isinstance(tools, list):
        tools = []
    return json.dumps(tools, ensure_ascii=False)


def _catalog_agent_response(
    agent_key: str,
    info: dict,
    company_id: int,
    index: int,
) -> "AgentResponse":
    role = info.get("role", "agent")
    display_name = info.get("name_display") or agent_key
    description = (
        f"Built-in AgentX catalog agent '{agent_key}' ({role}). "
        "This is configured system capability, not a user-created database record."
    )
    return AgentResponse(
        id=_catalog_agent_id(index),
        company_id=company_id,
        name=display_name,
        description=description,
        tools_json=_catalog_tools_json(agent_key),
        created_at=None,
    )


def _catalog_agent_responses(company_id: int) -> list["AgentResponse"]:
    return [
        _catalog_agent_response(agent_key, info, company_id, index)
        for index, (agent_key, info) in enumerate(get_active_agents().items())
    ]

# ==========================================
# 数据格式定义
# ==========================================


# 创建 Agent 的请求格式
# 前端要创建一个新 Agent，需要发送这些信息
class AgentCreate(BaseModel):
    name: str  # Agent 名称（如 "数据分析专家"）
    description: str  # Agent 描述（如 "擅长销售数据分析"）
    tools: list[str]  # Agent 会使用的工具名称列表（如 ["database_query", "chart"]）


# 更新 Agent 的请求格式
# 所有字段都是可选的（可以只更新名称，不更新描述）
class AgentUpdate(BaseModel):
    name: str | None = None  # 可选：新名称
    description: str | None = None  # 可选：新描述
    tools: list[str] | None = None  # 可选：新工具列表


# 返回 Agent 信息的格式
# 告诉前端一个 Agent 的详细信息
class AgentResponse(BaseModel):
    id: int  # Agent 的唯一 ID（数据库自动生成）
    company_id: int  # 所属公司 ID（多租户隔离：防止不同公司互相访问）
    name: str  # Agent 名称
    description: str  # Agent 描述
    tools_json: str  # 工具列表（JSON 字符串格式，前端需要自己解析）
    created_at: str | None = None  # 创建时间


# ==========================================
# API 接口：创建 Agent
# ==========================================
# POST /api/agents
# 用户在前端点击"创建Agent"时调用这个接口
# 只是在数据库里创建一条记录，不会让 Agent 真正工作
@router.post("/", response_model=AgentResponse)
async def create_agent(
    agent_data: AgentCreate,  # 前端发来的创建信息
    current_user: User = Depends(get_current_active_user),  # 自动验证用户是否已登录
):
    """Create a new agent instance (company access required)"""

    # --------------------------
    # 第一步：验证用户是否有公司
    # --------------------------
    # 用户必须先加入一个公司，才能创建 Agent
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,  # 400 = 请求错误
            detail="User must be associated with a company to create agents",
        )

    # --------------------------
    # 第二步：准备数据
    # --------------------------
    # 把工具列表转成 JSON 字符串（数据库只能存字符串）
    tools_json = json.dumps(agent_data.tools, ensure_ascii=False)

    # 创建 Agent 数据对象（准备写入数据库）
    new_agent = Agent(
        company_id=current_user.company_id,  # 自动绑定到用户所在公司
        name=agent_data.name,
        description=agent_data.description,
        tools_json=tools_json,
    )

    # --------------------------
    # 第三步：写入数据库
    # --------------------------
    # 在数据库中创建这条记录，返回新生成的 ID
    agent_id = db.create_agent(new_agent)
    # 创建后重新查询，获取数据库生成的完整信息（比如 ID、创建时间）
    created_agent = db.get_agent(agent_id)

    # 如果创建失败，返回错误
    if not created_agent:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,  # 500 = 服务器错误
            detail="Failed to create agent",
        )

    # --------------------------
    # 第四步：返回结果
    # --------------------------
    return _agent_to_response(created_agent)


# ==========================================
# API 接口：获取公司所有 Agent
# ==========================================
# GET /api/agents
# 用户在前端查看"我的Agent列表"时调用这个接口
@router.get("/", response_model=list[AgentResponse])
async def get_agents(current_user: User = Depends(get_current_active_user)):
    """Get all agents for the current user's company"""

    # 验证用户是否有公司
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must be associated with a company to view agents",
        )

    # 从数据库查询公司的所有 Agent
    # 按公司 ID 过滤，确保只能看到自己公司的 Agent（多租户隔离）
    agents = db.get_agents_by_company(current_user.company_id)

    if not agents:
        return _catalog_agent_responses(current_user.company_id)

    # 返回 Agent 列表
    return [_agent_to_response(agent) for agent in agents]


# ==========================================
# API 接口：获取单个 Agent 详情
# ==========================================
# GET /api/agents/{agent_id}
# 用户点击某个 Agent 查看详情时调用这个接口
@router.get("/{agent_id:int}", response_model=AgentResponse)
async def get_agent_info(
    agent_id: int,  # 要查询的 Agent ID
    current_user: User = Depends(get_current_active_user),
):
    """Get agent information by ID"""

    # 第一步：从数据库查询 Agent
    agent = db.get_agent(agent_id)

    if not agent:
        catalog_key = _catalog_agent_key(agent_id)
        if catalog_key is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

        active_agents = get_active_agents()
        catalog_items = list(active_agents.items())
        catalog_index = next(
            index for index, (key, _info) in enumerate(catalog_items) if key == catalog_key
        )
        return _catalog_agent_response(
            catalog_key,
            active_agents[catalog_key],
            current_user.company_id,
            catalog_index,
        )

    # 第二步：验证权限（多租户隔离）
    # 用户只能查看自己公司的 Agent
    if not current_user.company_id or agent.company_id != current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this agent"
        )

    # 返回 Agent 详情
    return _agent_to_response(agent)


# ==========================================
# API 接口：更新 Agent
# ==========================================
# PUT /api/agents/{agent_id}
# 用户编辑 Agent 信息时调用这个接口
@router.put("/{agent_id:int}", response_model=AgentResponse)
async def update_agent(
    agent_id: int,  # 要更新的 Agent ID
    agent_data: AgentUpdate,  # 更新的信息
    current_user: User = Depends(get_current_active_user),
):
    """Update agent information"""

    # 第一步：查询要更新的 Agent
    existing_agent = db.get_agent(agent_id)

    if not existing_agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    # 第二步：验证权限（多租户隔离）
    if not current_user.company_id or existing_agent.company_id != current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this agent"
        )

    # 第三步：更新字段（只更新前端传过来的字段）
    if agent_data.name:
        existing_agent.name = agent_data.name
    if agent_data.description:
        existing_agent.description = agent_data.description
    if agent_data.tools is not None:
        existing_agent.tools_json = json.dumps(agent_data.tools, ensure_ascii=False)

    # 第四步：保存到数据库
    success = db.update_agent(agent_id, existing_agent)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update agent"
        )

    # 更新后重新查询，确保返回最新数据
    updated_agent = db.get_agent(agent_id)

    return _agent_to_response(updated_agent)


# ==========================================
# API 接口：删除 Agent
# ==========================================
# DELETE /api/agents/{agent_id}
# 用户删除 Agent 时调用这个接口
@router.delete("/{agent_id:int}")
async def delete_agent(
    agent_id: int,  # 要删除的 Agent ID
    current_user: User = Depends(get_current_active_user),
):
    """Delete an agent"""

    # 第一步：查询要删除的 Agent
    existing_agent = db.get_agent(agent_id)

    if not existing_agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    # 第二步：验证权限（多租户隔离）
    if not current_user.company_id or existing_agent.company_id != current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this agent"
        )

    # 第三步：从数据库删除
    success = db.delete_agent(agent_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete agent"
        )

    # 删除成功，返回确认消息
    return {"message": "Agent deleted successfully"}


# ==========================================
# 聊天相关接口
# ==========================================


# 聊天请求格式
class AgentChatRequest(BaseModel):
    message: str  # 用户发送的消息

    # 消息过滤：防止恶意输入（如 SQL 注入、XSS 攻击）
    @field_validator("message")
    @classmethod
    def filter_message(cls, v: str) -> str:
        return InputFilter.validate_message(v)


# API 接口：与 Agent 聊天
# POST /api/agents/{agent_id}/chat
# 用户和 Agent 对话时调用这个接口
# 注意：该 Agent 直聊接口通过 ModelGateway 获取真实 LLM；主聊天编排逻辑在 chat.py 中。
@router.post("/{agent_id:int}/chat")
async def chat_with_agent(
    agent_id: int,  # 要聊天的 Agent ID
    request: AgentChatRequest,  # 用户的消息
    current_user: User = Depends(get_current_active_user),
):
    # 导入异步工具（放在函数内部，避免每次启动都加载）
    from fastapi.responses import StreamingResponse

    # 第一步：查询 Agent 信息
    agent = db.get_agent(agent_id)

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # 第二步：验证权限（多租户隔离）
    if current_user.company_id != agent.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # 第三步：通过 ModelGateway 获取 LLM 实例（按 chat 任务路由 + 企业 Key）
    # 初始化失败时返回 503——没有 LLM 就无法提供聊天服务
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.services.model_gateway import get_global_model_gateway

        gateway = get_global_model_gateway()
        llm = await gateway.get_llm_for_task(
            task_type="chat",
            company_id=current_user.company_id,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"LLM service unavailable: {e}",
        )

    # 第四步：流式响应（SSE）——先推送 thinking 提供即时反馈，再异步调用 LLM 推送真实回复
    # 流式响应的好处：用户不需要等完整回答，而是可以实时看到每一步
    async def generate():
        # 推送"正在思考"事件，让前端立即收到反馈（降低 TTFT 感知延迟）
        yield f"data: {json.dumps({'type': 'thinking', 'content': f'正在分析: {request.message[:50]}...'})}\n\n"

        # 调用 LLM 生成真实回复（异步 ainvoke）
        try:
            system_prompt = (
                f"你是 {agent.name}，{agent.description or 'AgentX 智能助手'}。"
                f"请用简体中文专业、友好地回答用户问题。"
            )
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=request.message),
            ]
            resp = await llm.ainvoke(messages)
            response_text = resp.content if hasattr(resp, "content") else str(resp)
            yield f"data: {json.dumps({'type': 'response', 'content': str(response_text)})}\n\n"
        except Exception as e:
            # LLM 调用失败时推送 error 事件，避免连接挂起；前端可据此展示错误提示
            yield f"data: {json.dumps({'type': 'error', 'content': f'AI 回复生成失败: {e}'})}\n\n"

        # 推送"完成"信号（告诉前端对话结束）
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    # 返回流式响应（SSE：Server-Sent Events，服务器推送事件）
    # 这是一种让服务器主动推送消息给前端的技术
    return StreamingResponse(generate(), media_type="text/event-stream")
