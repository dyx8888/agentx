# ==========================================
# 流式聊天 API
# ==========================================
# 这个文件是用户和 Agent 聊天的核心接口
# 支持实时流式响应（边想边说），就像是和真人对话一样
# 主要功能：
# 1. 接收用户消息
# 2. 通过感知管道处理（过滤→改写→意图识别→RAG检索）
# 3. 调用 Agent 运行时执行任务
# 4. 实时推送执行过程和结果
"""
Streaming Chat API for AgentX Platform
Provides SSE-based streaming chat interface with real-time tool execution display
Multi-turn conversation via Redis session store (with in-memory fallback)
Supports MCP protocol + Skill mechanism + Three paradigms (ReAct/Plan-and-Solve/Reflection)
"""

# JSON 工具：用于序列化 SSE 事件数据
import json

# FastAPI 核心工具
# APIRouter: 创建路由
# Request: 获取请求对象（用于获取应用状态）
from fastapi import APIRouter, Request
# StreamingResponse: 流式响应，实现实时推送
from fastapi.responses import StreamingResponse
# Pydantic：定义数据格式
from pydantic import BaseModel, field_validator

# 日志工具：记录运行日志
from app.core.logging import get_logger
# 输入过滤器：防止恶意输入
from app.middleware.input_filter import InputFilter
# 感知管道：统一处理用户消息（过滤→改写→意图识别→RAG检索）
from app.perception.pipeline import PerceptionPipeline

# 创建日志对象
logger = get_logger(__name__)

# 创建路由对象，tags=["chat"] 用于 API 文档分组
router = APIRouter(tags=["chat"])

# 感知管道单例（只初始化一次，避免每次请求都重新创建）
_perception_pipeline: PerceptionPipeline | None = None


# 获取感知管道（懒加载：第一次使用时才创建）
def _get_perception_pipeline() -> PerceptionPipeline:
    global _perception_pipeline
    if _perception_pipeline is None:
        _perception_pipeline = PerceptionPipeline()
    return _perception_pipeline


# ==========================================
# 辅助函数：注入 RAG 上下文
# ==========================================
# RAG = Retrieval-Augmented Generation（检索增强生成）
# 简单说：在用户消息中加入知识库中的相关信息，让 Agent 回答更准确
def _inject_rag_context(message: str, company_id: str, agent_name: str) -> tuple[str, list[dict]]:
    """注入 RAG 检索上下文到用户消息中，返回 (augmented_message, references)"""

    # 如果没有公司 ID，跳过 RAG（没有知识库可查）
    if not company_id:
        return message, []

    try:
        # 延迟导入：避免模块加载时的循环依赖
        from app.rag.agentic_rag import get_agentic_rag
        # 获取公司的 RAG 实例
        rag = get_agentic_rag(company_id)

        # 根据用户消息和 Agent 名称检索相关知识
        rag_context = rag.retrieve(query=message, agent_name=agent_name)

        if rag_context:
            # 记录日志
            logger.info("rag_context_injected", agent=agent_name, company_id=company_id,
                        context_length=len(rag_context))

            # 获取结构化的引用信息（供前端显示来源）
            structured = rag.retrieve_structured(query=message, agent_name=agent_name)
            refs = [
                {
                    "source_file": r.get("source_file", ""),  # 来源文件
                    "source_page": r.get("source_page", 0),   # 来源页码
                    "score": r.get("score", 0),               # 相关性分数
                    "content": r.get("content", "")[:200],    # 内容摘要（截断到 200 字符）
                }
                for r in structured.get("knowledge_results", [])
            ]

            # 将 RAG 上下文放在消息前面，让 LLM 优先参考
            return rag_context + "\n\n---\n\n" + message, refs

    except Exception as e:
        # RAG 失败不影响主流程，记录日志后继续
        logger.warning("rag_injection_failed", error=str(e), agent=agent_name, company_id=company_id)

    # 返回原始消息和空引用
    return message, []


# ==========================================
# 辅助函数：从数据库构建公司上下文
# ==========================================
# 获取公司的基本信息（名称、品牌、分类、平台等）
def _build_company_context_from_db(company_id: str) -> dict:
    if not company_id:
        return {}  # 无公司 ID 时返回空字典

    conn = None
    try:
        from app.database import db
        conn = db.get_connection()
        cursor = conn.cursor()

        # 查询公司信息（参数化查询防止 SQL 注入）
        cursor.execute(
            "SELECT name, brand_name, category, platforms_json FROM companies WHERE id = %s",
            (int(company_id),),
        )
        row = cursor.fetchone()

        if row:
            return {
                "company_name": row[0],
                "brand_name": row[1],
                "category": row[2],
                "platforms": json.loads(row[3]) if row[3] else [],  # JSON 字符串转列表
            }

    except Exception as e:
        logger.warning("build_company_context_error", error=str(e), company_id=company_id)
    finally:
        if conn:
            conn.close()  # 确保数据库连接被释放

    return {}


# ==========================================
# 辅助函数：查找公司默认 Agent
# ==========================================
# 如果用户没有指定具体的 Agent，就用公司的默认 Agent
def _find_company_default_agent(company_id: str):
    if not company_id:
        return None

    conn = None
    try:
        from app.database import db
        conn = db.get_connection()
        cursor = conn.cursor()

        # 查询公司的第一个 Agent（按 ID 排序，取第一个）
        cursor.execute(
            "SELECT id, name, tools_json FROM agents WHERE company_id = %s ORDER BY id LIMIT 1",
            (int(company_id),),
        )
        row = cursor.fetchone()

        if row:
            return {"id": str(row[0]), "name": row[1], "tools_json": row[2]}

    except Exception as e:
        logger.warning("find_company_default_agent_error", error=str(e), company_id=company_id)
    finally:
        if conn:
            conn.close()

    return None


# ==========================================
# 数据格式定义：聊天请求
# ==========================================
class ChatRequest(BaseModel):
    message: str           # 用户发送的消息（必填）
    company_context: dict = {}  # 公司上下文（可选，默认空字典）
    agent_id: str = None   # Agent ID（可选，通过 ID 指定 Agent）
    agent_name: str = None # Agent 名称（可选，通过名称指定 Agent）
    session_id: str = None # 会话 ID（可选，用于多轮对话上下文追踪）
    company_id: str = None # 公司 ID（可选，租户隔离标识）
    conversation_id: int = None  # 对话 ID（可选，用于多轮对话持久化）
    mode: str = None       # 工作模式（可选：ReAct / Plan-and-Solve / Reflection）

    # 消息过滤：在数据进入业务逻辑前就检查合法性，防止恶意输入
    @field_validator('message')
    @classmethod
    def filter_message(cls, v: str) -> str:
        return InputFilter.validate_message(v)


# ==========================================
# API 接口：流式聊天（核心接口）
# ==========================================
# POST /api/chat
# 用户和 Agent 聊天的主入口，支持实时流式响应（边想边说）
@router.post("/")
async def chat_stream(request: ChatRequest, req: Request):
    # 异步生成器：逐条推送 SSE 事件（实现实时聊天效果）
    async def generate_events():
        try:
            # --------------------------
            # 第一步：准备公司上下文
            # --------------------------
            # 如果有公司 ID 但没有上下文，自动从数据库获取
            if request.company_id and not request.company_context:
                request.company_context = _build_company_context_from_db(request.company_id)

            # --------------------------
            # 第二步：确定要使用的 Agent
            # --------------------------
            # 优先级：agent_name > agent_id > 默认 Agent
            effective_agent_name = request.agent_name

            # 如果没有指定名称，但有 ID，通过 ID 查找名称
            if not effective_agent_name and request.agent_id:
                try:
                    from app.database import db
                    agent_record = db.get_agent(int(request.agent_id))
                    if agent_record:
                        effective_agent_name = agent_record.name
                except Exception:
                    pass  # 失败不影响主流程

            # 如果还没找到，查找公司的默认 Agent
            if not effective_agent_name:
                default_agent = _find_company_default_agent(request.company_id)
                if default_agent:
                    effective_agent_name = default_agent["name"]

            # --------------------------
            # 第三步：获取 Agent 运行时
            # --------------------------
            runtime = getattr(req.app.state, 'runtime', None)
            if not runtime:
                yield f"data: {json.dumps({'type': 'error', 'content': 'AgentRuntime not initialized'})}\n\n"
                return
            if not effective_agent_name:
                effective_agent_name = "master"  # 兜底使用 master agent

            try:
                # 记录日志
                logger.info("agent_runtime_streaming", agent_name=effective_agent_name)

                # --------------------------
                # 第三步半：对话消息持久化 — 创建/复用对话并保存用户消息
                # --------------------------
                conversation_id = None
                assistant_response_parts: list[str] = []
                try:
                    from app.database import db as db_proxy
                    from app.services.message_persistence import (
                        get_or_create_conversation,
                        save_user_message,
                        save_assistant_message,
                        update_conversation_stats,
                    )

                    with db_proxy.get_session() as persist_session:
                        conv = get_or_create_conversation(
                            session=persist_session,
                            user_id=1,  # 使用默认用户；实际生产环境从 JWT 获取
                            company_id=int(request.company_id) if request.company_id else 0,
                            conversation_id=request.conversation_id,
                            title=request.message,
                        )
                        conversation_id = conv.id

                        save_user_message(
                            session=persist_session,
                            conversation_id=conversation_id,
                            user_id=1,
                            content=request.message,
                            metadata={
                                "intent_type": None,  # 将在感知管道后更新
                                "agent_name": effective_agent_name,
                            },
                            sequence_num=conv.message_count + 1,
                        )
                        logger.info("chat_message_persistence_user_saved",
                                    conversation_id=conversation_id)
                except Exception as persist_err:
                    # 持久化失败不影响主流程
                    logger.warning("chat_message_persistence_init_failed",
                                   error=str(persist_err))

                # 发送"思考中"状态（让前端显示加载动画）
                yield f"data: {json.dumps({'type': 'thinking', 'content': 'AI is planning...'})}\n\n"

                # --------------------------
                # 第四步：运行感知管道
                # --------------------------
                # 感知管道：过滤 → 改写 → 意图识别 → RAG 检索
                pipeline = _get_perception_pipeline()
                perception_ctx = pipeline.run(
                    raw_input=request.message,
                    company_id=request.company_id or "",
                    agent_name=effective_agent_name,
                )

                # 获取增强后的消息（加入了 RAG 上下文）
                augmented_message = perception_ctx.augmented_message or request.message
                rag_refs = perception_ctx.rag_results.references

                # 发送意图识别结果给前端（用于展示和统计）
                yield f"data: {json.dumps({'type': 'intent', 'intent_type': perception_ctx.intent.intent_type.value, 'confidence': perception_ctx.intent.confidence})}\n\n"

                # 如果有 RAG 引用，发送给前端（显示知识来源，增强可信度）
                if rag_refs:
                    yield f"data: {json.dumps({'type': 'sources', 'references': rag_refs})}\n\n"

                # --------------------------
                # 第五步：运行 Agent 并实时推送事件
                # --------------------------
                async for event in runtime.run_stream(
                    message=augmented_message,
                    agent_name=effective_agent_name,
                    company_id=request.company_id
                ):
                    # 根据事件类型，发送不同的消息给前端
                    if event["type"] == "plan":
                        # 计划阶段：显示执行计划，让用户了解 Agent 的思考路径
                        plan_data = event["data"]
                        assistant_response_parts.append(
                            f"[Plan] {plan_data.get('task_summary', '')}"
                        )
                        yield f"data: {json.dumps({'type': 'plan', 'content': plan_data.get('task_summary', ''), 'steps': plan_data.get('steps', [])})}\n\n"

                    elif event["type"] == "step_executed":
                        # 步骤执行完成：显示工具执行结果，增强透明度
                        assistant_response_parts.append(
                            f"[Step] {event.get('tool_used', 'unknown')}: {event.get('result', '')}"
                        )
                        yield f"data: {json.dumps({'type': 'tool_result', 'tool': event.get('tool_used', 'unknown'), 'result': event.get('result', '')})}\n\n"

                    elif event["type"] == "reflection":
                        # 反思阶段：显示质量检查结果
                        ref_data = event["data"]
                        assistant_response_parts.append(
                            f"[Reflection] passed={ref_data.get('passed', False)}"
                        )
                        yield f"data: {json.dumps({'type': 'reflection', 'passed': ref_data.get('passed', False), 'issues': ref_data.get('issues', [])})}\n\n"

                    elif event["type"] == "retry":
                        # 重试阶段：显示重试次数，让用户知道 Agent 正在自我修正
                        yield f"data: {json.dumps({'type': 'retry', 'count': event.get('count', 0)})}\n\n"

                    elif event["type"] == "done":
                        # 完成阶段：发送完成信号，前端据此关闭加载状态
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"

                # --------------------------
                # 第六步：保存助手回复并更新对话统计
                # --------------------------
                if conversation_id:
                    try:
                        assistant_content = "\n".join(assistant_response_parts) if assistant_response_parts else "任务已完成"
                        with db_proxy.get_session() as persist_session:
                            save_assistant_message(
                                session=persist_session,
                                conversation_id=conversation_id,
                                content=assistant_content,
                                metadata={
                                    "agent_name": effective_agent_name,
                                    "intent_type": perception_ctx.intent.intent_type.value,
                                    "rag_refs": rag_refs,
                                },
                                references=rag_refs if rag_refs else None,
                                sequence_num=conv.message_count + 2,
                            )
                            update_conversation_stats(
                                session=persist_session,
                                conversation_id=conversation_id,
                                last_message=assistant_content,
                            )
                            logger.info("chat_message_persistence_assistant_saved",
                                        conversation_id=conversation_id)
                    except Exception as persist_err:
                        logger.warning("chat_message_persistence_save_failed",
                                       error=str(persist_err))

            except Exception as runtime_error:
                # Agent 运行时错误也通过 SSE 返回，保持连接不断开
                logger.error("agent_runtime_streaming_error", error=str(runtime_error))
                yield f"data: {json.dumps({'type': 'error', 'content': f'Agent runtime error: {str(runtime_error)}'})}\n\n"

        except Exception as e:
            # 最外层错误兜底：确保即使发生未预期的异常，前端也能收到错误提示
            yield f"data: {json.dumps({'type': 'error', 'content': f'Stream error: {str(e)}'})}\n\n"

    # 返回流式响应（SSE：Server-Sent Events）
    return StreamingResponse(
        generate_events(),
        media_type="text/plain",  # 使用 text/plain 避免某些代理缓冲
        headers={
            "Cache-Control": "no-cache",  # 禁止缓存，确保每次请求都是新的实时数据
            "Connection": "keep-alive",   # 保持长连接，支持 SSE
            "Access-Control-Allow-Origin": "*",  # 开发阶段允许所有来源跨域
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        }
    )


# ==========================================
# API 接口：健康检查
# ==========================================
# GET /api/chat/health
# 检查聊天服务是否正常运行（用于监控告警）
@router.get("/health")
async def health_check(req: Request):
    try:
        # 检查 Agent 运行时是否已初始化
        agent_app = getattr(req.app.state, 'agent_app', None)
        return {"status": "healthy", "agent_initialized": agent_app is not None}
    except Exception as e:
        # 即使出错也返回 200（避免健康检查本身触发告警）
        return {"status": "unhealthy", "error": str(e), "agent_initialized": False}
