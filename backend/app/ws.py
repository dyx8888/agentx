"""
WebSocket Manager - Real-time Push Notifications
Supports: task status updates, alerts, review notifications, agent status changes
"""
# WebSocket 而非 SSE/轮询：实时推送延迟最低，且支持双向通信（客户端可发 ping/订阅消息）

import asyncio  # asyncio.Lock 保证并发修改连接字典时的线程安全，避免竞态条件导致连接泄漏或崩溃
import json  # 消息体用 JSON 而非二进制：与前端 JavaScript 原生兼容，且方便在代理/日志中直接阅读调试
from typing import Any  # 消息 dict 的键值类型灵活，用 Any 避免过于严格的类型约束

from fastapi import APIRouter, WebSocket, WebSocketDisconnect  # WebSocketDisconnect 是 FastAPI 内置异常，精确捕获客户端断开事件

from app.core.logging import get_logger  # 结构化日志：支持按 company_id/user_id 过滤，便于排查某个租户的连接问题

logger = get_logger(__name__)  # 模块级 logger，线上排查 WebSocket 问题时可按模块 grep

router = APIRouter()  # 独立路由模块：WebSocket 端点和 HTTP 端点可以共存于同一个 router 中，便于按功能分组


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
            self._connections: dict[int, list[WebSocket]] = {}  # 按 company_id 分组：实现租户级广播隔离的最直接数据结构
            self._user_connections: dict[str, WebSocket] = {}  # user_id → 单一连接：假设每个用户只维持一个 WebSocket，简化一对一推送
            self._lock = asyncio.Lock()  # 异步锁：所有读写连接字典的操作都必须串行化，防止并发 add/del 导致 KeyError 或数据丢失
            logger.info("websocket_manager_initialized")

    async def connect(self, websocket: WebSocket, company_id: int, user_id: str = None):
        await websocket.accept()  # 必须先 accept 才能收发消息，这是 WebSocket 协议握手的第一步
        async with self._lock:
            # 锁内操作：确保_connections和_user_connections的插入是原子性的，不会出现"只插入了一个"的中间状态
            if company_id not in self._connections:
                self._connections[company_id] = []  # 惰性创建列表：只在第一个用户连接时分配，节省无连接租户的内存
            self._connections[company_id].append(websocket)
            if user_id:
                self._user_connections[user_id] = websocket  # 不检查旧连接是否被覆盖：新连接覆盖旧连接，旧连接会自动失效
        logger.info("ws_connected", company_id=company_id, user_id=user_id,
                     total_company_connections=len(self._connections.get(company_id, [])))  # 记录连接数用于监控和容量规划

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
                del self._user_connections[user_id]  # 只删除当前用户对应的连接，不检查是否与 websocket 参数匹配
        logger.info("ws_disconnected", company_id=company_id, user_id=user_id)

    async def broadcast_to_company(self, company_id: int, message: dict[str, Any]):
        async with self._lock:
            connections = self._connections.get(company_id, [])  # 锁内拷贝引用：尽量减少持锁时间，避免阻塞其他连接/断开操作
        disconnected = []
        for ws in connections:
            try:
                await ws.send_json(message)  # send_json 自动序列化 dict 并添加 WebSocket 帧头，比手动 json.dumps + send_text 简洁
            except Exception:
                disconnected.append(ws)  # 记录发送失败的连接，延迟清理而非立即操作，避免在遍历中修改原列表
        if disconnected:
            async with self._lock:
                if company_id in self._connections:
                    self._connections[company_id] = [
                        c for c in self._connections[company_id] if c not in disconnected
                    ]  # 批量清理断开的连接：不在发消息时逐个删，减少锁竞争次数

    async def send_to_user(self, user_id: str, message: dict[str, Any]):
        async with self._lock:
            ws = self._user_connections.get(user_id)  # 锁内读取：保证 user_id 对应的连接引用在读取时有效
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                async with self._lock:
                    self._user_connections.pop(user_id, None)  # 发送失败则移除，防止后续调用反复向已断开的连接发送

    async def broadcast_all(self, message: dict[str, Any]):
        async with self._lock:
            all_connections = [
                (company_id, list(conns))
                for company_id, conns in self._connections.items()
            ]  # 锁内深拷贝：list(conns) 创建快照，避免持锁期间遍历大量连接导致其他操作饥饿
        for company_id, conns in all_connections:
            for ws in conns:
                try:
                    await ws.send_json(message)
                except Exception:
                    pass  # 全局广播时静默忽略失败：不可能为了个别断连用户而中止整个广播流程

    async def broadcast_task_status(self, company_id: int, task_id: int, status: str,
                                     agent_key: str = None, result: dict = None):
        # 使用统一的消息结构：前端只需监听 type 字段即可路由到不同的 UI 更新逻辑，降低耦合
        await self.broadcast_to_company(company_id, {
            "type": "task_status",
            "taskId": task_id,
            "status": status,
            "agent": agent_key,
            "result": result,
        })

    async def broadcast_alert(self, company_id: int, alert_id: int, alert_type: str,
                               title: str, message: str, severity: str = "warning",
                               related_agents: list[str] = None):
        await self.broadcast_to_company(company_id, {
            "type": "alert",
            "alertId": alert_id,
            "alertType": alert_type,
            "title": title,
            "message": message,
            "severity": severity,
            "relatedAgents": related_agents or [],  # 用 or [] 而非默认参数默认值：避免可变默认参数的经典陷阱
            "timestamp": None,  # 预留字段：前端可自行填充当前时间，避免服务端时区与客户端不一致的问题
        })

    async def broadcast_review_notification(self, company_id: int, review_id: int,
                                              agent_key: str, level: str):
        await self.broadcast_to_company(company_id, {
            "type": "review_notification",
            "reviewId": review_id,
            "agent": agent_key,
            "level": level,
        })

    async def broadcast_agent_status(self, company_id: int, agent_key: str,
                                       status: str, task_count: int = 0):
        await self.broadcast_to_company(company_id, {
            "type": "agent_status",
            "agent": agent_key,
            "status": status,
            "taskCount": task_count,
        })

    async def broadcast_chain_progress(self, company_id: int, chain_name: str,
                                         completed_steps: int, total_steps: int,
                                         current_step: str = None):
        # 使用驼峰命名：与前端 JavaScript 约定一致，避免 snake_case/camelCase 转换
        await self.broadcast_to_company(company_id, {
            "type": "chain_progress",
            "chain": chain_name,
            "completedSteps": completed_steps,
            "totalSteps": total_steps,
            "currentStep": current_step,
        })

    def get_connection_count(self, company_id: int = None) -> int:
        # 同步方法不需要锁：Python GIL 保证 int 和简单 dict.get 的读取操作是原子性的
        if company_id is not None:
            return len(self._connections.get(company_id, []))
        return sum(len(conns) for conns in self._connections.values())  # sum 遍历所有租户，用于全局监控大盘


ws_manager = WebSocketManager()  # 模块级单例：所有业务代码统一通过此实例操作，避免连接状态跨实例不一致


@router.websocket("/connect/{company_id}")
async def websocket_endpoint(websocket: WebSocket, company_id: int):
    user_id = websocket.query_params.get("user_id", None)  # query_params 比路径参数灵活：前端在建立 WebSocket 时可在 URL 后拼接参数
    await ws_manager.connect(websocket, company_id, user_id)
    try:
        while True:
            data = await websocket.receive_text()  # receive_text 会阻塞当前协程直到收到消息，但不会阻塞事件循环
            try:
                message = json.loads(data)
                msg_type = message.get("type", "")
                if msg_type == "ping":
                    # 应用层心跳：浏览器 WebSocket 协议自身有心跳机制，但部分代理/防火墙会断开空闲连接
                    # 应用层 ping/pong 确保长连接在代理环境下保持活跃
                    await websocket.send_json({"type": "pong"})
                elif msg_type == "subscribe":
                    pass  # 预留订阅接口：当前未实现细粒度频道，但不声明会引发 KeyError，pass 保留扩展性
            except json.JSONDecodeError:
                pass  # 静默忽略非法 JSON：客户端可能误发非 JSON 消息，不应因此关闭连接
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket, company_id, user_id)  # 正常断开：用户关闭页面或网络中断时触发
    except Exception:
        # 兜底异常处理：任何未预期的异常都应触发断开，防止僵尸连接残留
        await ws_manager.disconnect(websocket, company_id, user_id)


@router.get("/status")
async def ws_status():
    # HTTP 端点与 WebSocket 共存：运维监控可随时检查连接状态，不需要 WebSocket 客户端
    return {
        "total_connections": ws_manager.get_connection_count(),
        "active": True,
    }
