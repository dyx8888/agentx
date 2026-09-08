"""
WebSocket Manager - Real-time Push Notifications
Supports: task status updates, alerts, review notifications, agent status changes
"""
# WebSocket 而非 SSE/轮询：实时推送延迟最低，且支持双向通信（客户端可发 ping/订阅消息）

import asyncio  # asyncio.Lock 保证并发修改连接字典时的线程安全，避免竞态条件导致连接泄漏或崩溃
import json  # 消息体用 JSON 而非二进制：与前端 JavaScript 原生兼容，且方便在代理/日志中直接阅读调试
from contextlib import suppress
from typing import Any  # 消息 dict 的键值类型灵活，用 Any 避免过于严格的类型约束

from fastapi import (  # WebSocketDisconnect 是 FastAPI 内置异常，精确捕获客户端断开事件
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
)

from app.auth import (
    decode_access_token,  # JWT 解码：复用 app/auth.py 的 token 验证逻辑，避免重复实现导致策略不一致
    decode_ws_ticket,
)
from app.core.logging import (
    get_logger,  # 结构化日志：支持按 company_id/user_id 过滤，便于排查某个租户的连接问题
)
from app.database import User, db  # User 类型注解 + db 单例：用于根据 token 中的 username 查询用户

logger = get_logger(__name__)  # 模块级 logger，线上排查 WebSocket 问题时可按模块 grep

router = (
    APIRouter()
)  # 独立路由模块：WebSocket 端点和 HTTP 端点可以共存于同一个 router 中，便于按功能分组

WS_PROTOCOL = "agentx.ws.v1"
WS_TICKET_PROTOCOL_PREFIX = "agentx-ticket."


class WebSocketManager:
    _instance = None  # 类级别单例引用：全局只有一个 Manager，避免多处创建导致连接状态分裂

    def __new__(cls):
        # 单例模式：无论多少次 WebSocketManager() 调用，始终返回同一个实例
        # 这样 ws_manager 和任何内部引用都共享同一套连接池
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False  # 标记未初始化，让 __init__ 只执行一次初始化逻辑
        return cls._instance

    def __init__(self):
        # _initialized 标志防止 __init__ 被重复调用：Python 的 __init__ 在每次 __new__ 返回已存在实例时仍会触发
        if not self._initialized:
            self._initialized = True
            self._connections: dict[
                int, list[WebSocket]
            ] = {}  # 按 company_id 分组：实现租户级广播隔离的最直接数据结构
            self._user_connections: dict[
                str, WebSocket
            ] = {}  # user_id → 单一连接：假设每个用户只维持一个 WebSocket，简化一对一推送
            self._lock = asyncio.Lock()  # 异步锁：所有读写连接字典的操作都必须串行化，防止并发 add/del 导致 KeyError 或数据丢失
            logger.info("websocket_manager_initialized")

    async def connect(
        self,
        websocket: WebSocket,
        company_id: int,
        user_id: str = None,
        subprotocol: str | None = None,
    ):
        await websocket.accept(
            subprotocol=subprotocol
        )  # 必须先 accept 才能收发消息，这是 WebSocket 协议握手的第一步
        async with self._lock:
            # 锁内操作：确保_connections和_user_connections的插入是原子性的，不会出现"只插入了一个"的中间状态
            if company_id not in self._connections:
                self._connections[
                    company_id
                ] = []  # 惰性创建列表：只在第一个用户连接时分配，节省无连接租户的内存
            self._connections[company_id].append(websocket)
            if user_id:
                self._user_connections[user_id] = (
                    websocket  # 不检查旧连接是否被覆盖：新连接覆盖旧连接，旧连接会自动失效
                )
        logger.info(
            "ws_connected",
            company_id=company_id,
            user_id=user_id,
            total_company_connections=len(self._connections.get(company_id, [])),
        )  # 记录连接数用于监控和容量规划

    async def disconnect(self, websocket: WebSocket, company_id: int, user_id: str = None):
        async with self._lock:
            if company_id in self._connections:
                self._connections[company_id] = [
                    conn for conn in self._connections[company_id] if conn != websocket
                ]  # 列表推导式过滤：O(n) 但在实际业务中单个公司的连接数通常不会超过几百，性能可接受
                if not self._connections[company_id]:
                    # 公司下无连接时立即删除键，避免 dict 膨胀，也方便 get_connection_count 统计准确
                    del self._connections[company_id]
            if user_id and user_id in self._user_connections:
                del self._user_connections[
                    user_id
                ]  # 只删除当前用户对应的连接，不检查是否与 websocket 参数匹配
        logger.info("ws_disconnected", company_id=company_id, user_id=user_id)

    async def broadcast_to_company(self, company_id: int, message: dict[str, Any]):
        async with self._lock:
            connections = self._connections.get(
                company_id, []
            )  # 锁内拷贝引用：尽量减少持锁时间，避免阻塞其他连接/断开操作
        disconnected = []
        for ws in connections:
            try:
                await ws.send_json(
                    message
                )  # send_json 自动序列化 dict 并添加 WebSocket 帧头，比手动 json.dumps + send_text 简洁
            except Exception as exc:
                logger.warning("ws_company_send_failed", company_id=company_id, error=str(exc))
                disconnected.append(
                    ws
                )  # 记录发送失败的连接，延迟清理而非立即操作，避免在遍历中修改原列表
        if disconnected:
            async with self._lock:
                if company_id in self._connections:
                    self._connections[company_id] = [
                        c for c in self._connections[company_id] if c not in disconnected
                    ]  # 批量清理断开的连接：不在发消息时逐个删，减少锁竞争次数

    async def send_to_user(self, user_id: str, message: dict[str, Any]):
        async with self._lock:
            ws = self._user_connections.get(
                user_id
            )  # 锁内读取：保证 user_id 对应的连接引用在读取时有效
        if ws:
            try:
                await ws.send_json(message)
            except Exception as exc:
                logger.warning("ws_user_send_failed", user_id=user_id, error=str(exc))
                async with self._lock:
                    self._user_connections.pop(
                        user_id, None
                    )  # 发送失败则移除，防止后续调用反复向已断开的连接发送

    async def broadcast_all(self, message: dict[str, Any]):
        async with self._lock:
            all_connections = [
                (company_id, list(conns)) for company_id, conns in self._connections.items()
            ]  # 锁内深拷贝：list(conns) 创建快照，避免持锁期间遍历大量连接导致其他操作饥饿
        for _company_id, conns in all_connections:
            for ws in conns:
                with suppress(Exception):
                    await ws.send_json(message)

    async def broadcast_task_status(
        self, company_id: int, task_id: int, status: str, agent_key: str = None, result: dict = None
    ):
        # 使用统一的消息结构：前端只需监听 type 字段即可路由到不同的 UI 更新逻辑，降低耦合
        await self.broadcast_to_company(
            company_id,
            {
                "type": "task_status",
                "taskId": task_id,
                "status": status,
                "agent": agent_key,
                "result": result,
            },
        )

    async def broadcast_alert(
        self,
        company_id: int,
        alert_id: int,
        alert_type: str,
        title: str,
        message: str,
        severity: str = "warning",
        related_agents: list[str] = None,
    ):
        await self.broadcast_to_company(
            company_id,
            {
                "type": "alert",
                "alertId": alert_id,
                "alertType": alert_type,
                "title": title,
                "message": message,
                "severity": severity,
                "relatedAgents": related_agents
                or [],  # 用 or [] 而非默认参数默认值：避免可变默认参数的经典陷阱
                "timestamp": None,  # 预留字段：前端可自行填充当前时间，避免服务端时区与客户端不一致的问题
            },
        )

    async def broadcast_review_notification(
        self, company_id: int, review_id: int, agent_key: str, level: str
    ):
        await self.broadcast_to_company(
            company_id,
            {
                "type": "review_notification",
                "reviewId": review_id,
                "agent": agent_key,
                "level": level,
            },
        )

    async def broadcast_agent_status(
        self, company_id: int, agent_key: str, status: str, task_count: int = 0
    ):
        await self.broadcast_to_company(
            company_id,
            {
                "type": "agent_status",
                "agent": agent_key,
                "status": status,
                "taskCount": task_count,
            },
        )

    async def broadcast_chain_progress(
        self,
        company_id: int,
        chain_name: str,
        completed_steps: int,
        total_steps: int,
        current_step: str = None,
    ):
        # 使用驼峰命名：与前端 JavaScript 约定一致，避免 snake_case/camelCase 转换
        await self.broadcast_to_company(
            company_id,
            {
                "type": "chain_progress",
                "chain": chain_name,
                "completedSteps": completed_steps,
                "totalSteps": total_steps,
                "currentStep": current_step,
            },
        )

    async def send_capture_completed(
        self,
        *,
        user_id: int,
        company_id: int,
        capture_job_id: int,
        conversation_id: int,
        status: str,
        classification: str,
    ):
        """Send a capture lifecycle update only to the owning user, not the whole tenant."""
        await self.send_to_user(
            str(user_id),
            {
                "type": "capture_completed",
                "captureJobId": capture_job_id,
                "conversationId": conversation_id,
                "companyId": company_id,
                "status": status,
                "classification": classification,
            },
        )

    def get_connection_count(self, company_id: int = None) -> int:
        # 同步方法不需要锁：Python GIL 保证 int 和简单 dict.get 的读取操作是原子性的
        if company_id is not None:
            return len(self._connections.get(company_id, []))
        return sum(
            len(conns) for conns in self._connections.values()
        )  # sum 遍历所有租户，用于全局监控大盘


ws_manager = (
    WebSocketManager()
)  # 模块级单例：所有业务代码统一通过此实例操作，避免连接状态跨实例不一致


def _invalid_ws_message_payload(reason: str = "invalid_json") -> dict[str, str]:
    return {
        "type": "error",
        "code": reason,
        "message": "Invalid WebSocket message",
    }


async def _reject_ws_unauthorized(websocket: WebSocket) -> None:
    await websocket.close(code=4001, reason="Unauthorized")


def _user_company_id(user: User) -> int | None:
    try:
        return int(user.company_id)
    except (TypeError, ValueError):
        return None


def _requested_ws_protocols(websocket: WebSocket) -> list[str]:
    headers = getattr(websocket, "headers", None)
    header = headers.get("sec-websocket-protocol", "") if headers is not None else ""
    return [part.strip() for part in header.split(",") if part.strip()]


def _extract_ws_ticket(websocket: WebSocket) -> str | None:
    for protocol in _requested_ws_protocols(websocket):
        if protocol.startswith(WS_TICKET_PROTOCOL_PREFIX):
            return protocol[len(WS_TICKET_PROTOCOL_PREFIX) :]
    return None


def _selected_ws_subprotocol(websocket: WebSocket) -> str | None:
    protocols = _requested_ws_protocols(websocket)
    if WS_PROTOCOL in protocols:
        return WS_PROTOCOL
    return None


def _user_from_auth_payload(payload: dict[str, Any]) -> User | None:
    username = payload.get("sub")
    if not username:
        return None

    user = db.get_user_by_username(username)
    if not user or user.disabled:
        return None

    current_token_version = int(getattr(user, "token_version", 0) or 0)
    payload_token_version = payload.get("token_version")
    if payload_token_version is None:
        return user if current_token_version == 0 else None
    try:
        if int(payload_token_version) != current_token_version:
            return None
    except (TypeError, ValueError):
        return None
    return user


def _authenticate_ws(websocket: WebSocket) -> User | None:
    """鉴权 WebSocket 连接：双兼容读取 JWT，返回认证用户或 None。

    Token 来源优先级：
      1. WebSocket subprotocol short-lived ticket（跨域直连 Render）
      2. query parameter `?token=`（保留兼容旧客户端）
      3. httpOnly cookie `access_token`（同源 WS 兜底）

    cookie 鉴权机制说明：
      前端切换到 httpOnly cookie 后，JS 无法读取 token，WebSocket URL 不再拼 ?token=。
      浏览器在 WebSocket 握手阶段会自动携带同源 cookie（与 fetch/XHR 同源带 cookie 一致），
      FastAPI/Starlette 通过 `websocket.cookies.get("access_token")` 即可读取，
      与 HTTP 接口的 cookie 鉴权保持一致，无需额外配置。

    验证逻辑复用 app/auth.py 的 decode_access_token，与 HTTP 接口校验保持一致。
    """
    ws_ticket = _extract_ws_ticket(websocket)
    if ws_ticket is not None:
        payload = decode_ws_ticket(ws_ticket)
        if not payload:
            return None
        return _user_from_auth_payload(payload)

    # 优先读 query param（兼容旧客户端 / 跨域直连 / 显式传 token 的场景）
    token = websocket.query_params.get("token")
    # query param 无 token 时回退到 cookie（httpOnly cookie 方案：握手时浏览器同源自动携带）
    if not token:
        token = websocket.cookies.get("access_token")
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    return _user_from_auth_payload(payload)


@router.websocket("/connect/{company_id}")
async def websocket_endpoint(websocket: WebSocket, company_id: int):
    # 安全修复：接受连接前验证 token，防止未认证用户连接 WebSocket 接收其他租户的推送
    user = _authenticate_ws(websocket)
    if user is None:
        # 验证失败：未携带 token / token 无效 / 用户不存在或已禁用
        # 在 accept 之前 close，Starlette 会以拒绝握手的方式终止连接
        await _reject_ws_unauthorized(websocket)
        return
    if _user_company_id(user) != company_id:
        await _reject_ws_unauthorized(websocket)
        return
    # user_id 从认证用户获取，忽略客户端 query parameter 中可被伪造的 user_id
    user_id = str(user.id)
    await ws_manager.connect(
        websocket,
        company_id,
        user_id,
        subprotocol=_selected_ws_subprotocol(websocket),
    )
    try:
        while True:
            data = (
                await websocket.receive_text()
            )  # receive_text 会阻塞当前协程直到收到消息，但不会阻塞事件循环
            try:
                message = json.loads(data)
                msg_type = message.get("type", "")
                if msg_type == "ping":
                    # 应用层心跳：浏览器 WebSocket 协议自身有心跳机制，但部分代理/防火墙会断开空闲连接
                    # 应用层 ping/pong 确保长连接在代理环境下保持活跃
                    await websocket.send_json({"type": "pong"})
                elif msg_type == "subscribe":
                    await websocket.send_json({"type": "subscribed", "scope": "company"})
            except json.JSONDecodeError:
                await websocket.send_json(_invalid_ws_message_payload())
    except WebSocketDisconnect:
        await ws_manager.disconnect(
            websocket, company_id, user_id
        )  # 正常断开：用户关闭页面或网络中断时触发
    except Exception as exc:
        # 兜底异常处理：任何未预期的异常都应触发断开，防止僵尸连接残留
        logger.warning("ws_company_connection_error", company_id=company_id, error=str(exc))
        await ws_manager.disconnect(websocket, company_id, user_id)


@router.get("/status")
async def ws_status():
    # HTTP 端点与 WebSocket 共存：运维监控可随时检查连接状态，不需要 WebSocket 客户端
    return {
        "total_connections": ws_manager.get_connection_count(),
        "active": True,
    }


# ==========================================
# 任务状态订阅 WebSocket
# ==========================================
# 按 task_id 分组的连接池：客户端连接 /ws/tasks/{task_id} 后，
# 任何对该 task 的状态变更（通过 /api/tasks/{id}/confirm 触发）都会被推送到所有订阅者
_task_connections: dict[int, list[WebSocket]] = {}


async def broadcast_task_status_update(task_id: int, status: str, message: str | None = None):
    """向所有订阅了指定 task_id 的 WebSocket 客户端推送状态更新。

    被 tasks API 的 confirm 端点调用，实现"HTTP 触发 → WebSocket 实时推送"的联动。
    """
    connections = _task_connections.get(task_id, [])
    if not connections:
        return
    payload = {
        "type": "status_update",
        "payload": {"status": status, "message": message},
    }
    disconnected = []
    for ws in connections:
        try:
            await ws.send_json(payload)
        except Exception as exc:
            logger.warning("task_ws_send_failed", task_id=task_id, error=str(exc))
            disconnected.append(ws)
    if disconnected:
        _task_connections[task_id] = [ws for ws in connections if ws not in disconnected]


@router.websocket("/tasks/{task_id}")
async def task_status_websocket(websocket: WebSocket, task_id: int):
    """任务状态订阅端点。

    客户端连接后注册到 _task_connections[task_id]，
    后续任何对该任务的状态变更都会通过 broadcast_task_status_update 推送。
    """
    user = _authenticate_ws(websocket)
    if user is None:
        await _reject_ws_unauthorized(websocket)
        return

    await websocket.accept(subprotocol=_selected_ws_subprotocol(websocket))
    _task_connections.setdefault(task_id, []).append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except json.JSONDecodeError:
                await websocket.send_json(_invalid_ws_message_payload())
    except WebSocketDisconnect:
        logger.info("task_ws_disconnected", task_id=task_id)
    except Exception as exc:
        logger.warning("task_ws_connection_error", task_id=task_id, error=str(exc))
    finally:
        conns = _task_connections.get(task_id, [])
        if websocket in conns:
            conns.remove(websocket)
            if not conns:
                _task_connections.pop(task_id, None)


# ==========================================
# Agent 聊天 WebSocket
# ==========================================
def _is_valid_agent(agent_name: str) -> bool:
    """检查 agent 名称是否在注册表中存在。"""
    try:
        from app.agents import AGENT_REGISTRY

        return agent_name in AGENT_REGISTRY
    except Exception as exc:
        logger.warning("agent_registry_lookup_failed", agent=agent_name, error=str(exc))
        return False


async def _run_agent_chat(agent_name: str, message: str, company_id: int | str | None = None):
    """Stream real AgentRuntime events for the legacy chat WebSocket endpoint.

    If runtime initialization or execution is unavailable, return an explicit error
    event instead of fabricating tool calls or business results.
    """
    try:
        from app.runtime.orchestrator import AgentRuntime

        runtime = AgentRuntime()
        async for event in runtime.run_stream(
            message,
            agent_name=agent_name,
            company_id=str(company_id or ""),
        ):
            yield event
    except Exception as exc:
        logger.warning("agent_chat_runtime_unavailable", agent=agent_name, error=str(exc))
        yield {
            "type": "error",
            "code": "agent_runtime_unavailable",
            "content": "Agent runtime is unavailable; no mock response was generated.",
        }


@router.websocket("/chat/{agent_name}")
async def chat_websocket(websocket: WebSocket, agent_name: str):
    """Agent 聊天流式端点。

    客户端发送 JSON 消息后，服务端流式返回：thinking → tool_call → tool_result → text → done。
    若 agent 不存在，返回 error 事件。
    """
    user = _authenticate_ws(websocket)
    if user is None:
        await _reject_ws_unauthorized(websocket)
        return

    await websocket.accept(subprotocol=_selected_ws_subprotocol(websocket))
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message_data = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json(_invalid_ws_message_payload())
                continue

            if message_data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if not _is_valid_agent(agent_name):
                await websocket.send_json(
                    {
                        "type": "error",
                        "content": f"Agent '{agent_name}' not found",
                    }
                )
                continue

            user_message = message_data.get("message", "")
            async for event in _run_agent_chat(agent_name, user_message, company_id=user.company_id):
                await websocket.send_json(event)
            await websocket.send_json({"type": "done"})
    except WebSocketDisconnect:
        logger.info("agent_chat_ws_disconnected", agent=agent_name)
    except Exception as exc:
        logger.warning("agent_chat_ws_connection_error", agent=agent_name, error=str(exc))
