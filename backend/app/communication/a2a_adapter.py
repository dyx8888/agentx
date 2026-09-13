"""
Google A2A Protocol Adapter for AgentX Stage 22
Provides standardized Agent-to-Agent communication using Google A2A protocol.
Enhanced with task lifecycle management, Redis state storage, and capability negotiation.
"""

import json  # A2A 协议传输层使用 JSON 作为标准序列化格式，跨语言兼容
from contextlib import suppress
from datetime import datetime  # 所有任务状态变更都需精确时间戳，便于审计和超时判断
from typing import (  # Any 用于灵活处理不同 Agent 返回的异构数据；Optional 用于可空字段的显式声明
    Any,
)

from app.core.logging import get_logger

# 使用项目统一的结构化 logger，确保关键字事件字段不会传给标准 Logger._log()
logger = get_logger(__name__)


# 使用字符串常量而非 IntEnum，因为 A2A 协议规范要求字符串状态码，便于跨系统序列化
class A2ATaskStatus:
    PENDING = "pending"  # 任务已创建但尚未被 Agent 领取，处于等待调度队列中
    RUNNING = "running"  # Agent 正在执行，此时允许取消但不能直接跳到完成态
    COMPLETED = "completed"  # 终态：任务成功完成，不可再流转
    FAILED = "failed"  # 终态：执行出错，与 COMPLETED 互斥，不可恢复
    TIMEOUT = "timeout"  # 终态：超时未完成，与 FAILED 区分以便独立统计超时率
    CANCELLED = "cancelled"  # 终态：人为取消，可从 PENDING 或 RUNNING 进入，不可撤销


# 显式定义状态流转白名单，防止非法状态跳跃（如从 PENDING 直接跳到 COMPLETED），确保状态机的严格性
TASK_STATUS_TRANSITIONS = {
    A2ATaskStatus.PENDING: [
        A2ATaskStatus.RUNNING,
        A2ATaskStatus.CANCELLED,
    ],  # 待处理只能开始执行或被取消
    A2ATaskStatus.RUNNING: [
        A2ATaskStatus.COMPLETED,
        A2ATaskStatus.FAILED,
        A2ATaskStatus.TIMEOUT,
        A2ATaskStatus.CANCELLED,
    ],  # 运行中四种出口
    A2ATaskStatus.COMPLETED: [],  # 终态无出口
    A2ATaskStatus.FAILED: [],  # 终态无出口
    A2ATaskStatus.TIMEOUT: [],  # 终态无出口
    A2ATaskStatus.CANCELLED: [],  # 终态无出口
}


class A2AAdapter:
    """
    Adapter for Google A2A Protocol implementation
    Handles agent registration, discovery, task delegation, and task lifecycle management.
    """

    def __init__(self, db_manager):
        """
        Initialize A2A adapter with database manager

        Args:
            db_manager: Database manager instance for agent registration
        """
        self.db = db_manager  # 数据库持久化是 Redis 的兜底方案，确保 Redis 不可用时任务状态不丢失
        self._redis = None  # 延迟初始化 Redis，避免“启动即连接失败导致整个服务不可用”

    def _get_redis(self):
        """Lazy-load Redis connection for task state storage"""
        if self._redis is None:  # 仅在首次调用时尝试连接，减少 Redis 不可用时的重复连接开销
            try:
                import redis  # 延迟导入，避免 environments 未安装 redis 模块时 import 就报错

                from app.core.config import get_settings

                settings = get_settings()
                redis_url = getattr(
                    settings, "REDIS_URL", "redis://localhost:6379/0"
                )  # 生产环境通过配置注入 Redis 地址
                self._redis = redis.from_url(
                    redis_url, decode_responses=True
                )  # decode_responses 避免手动 decode 字节串
                self._redis.ping()  # 立即验证连接可用性，连接失败则走数据库降级
                logger.info("a2a_redis_connected")
            except Exception as e:
                logger.warning(
                    "a2a_redis_unavailable",
                    error=str(e),
                    suggestion="Redis 不可用，A2A 任务状态将仅使用数据库存储",
                )
                self._redis = None  # 保持 None，后续所有操作走数据库降级路径
        return self._redis

    # ── 任务状态管理 ──────────────────────────────────────

    def _make_task_key(self, task_id: str) -> str:
        """生成 Redis key: a2a:task:{task_id}"""
        return f"a2a:task:{task_id}"  # 使用统一前缀命名空间，方便按前缀批量清理或监控 Redis 键

    def set_task_status(
        self, task_id: str, status: str, result: dict = None, error: str = None
    ) -> bool:
        """
        设置任务状态，支持状态流转校验。
        使用 Redis 存储: a2a:task:{task_id} → {status, result, created_at, updated_at}

        Args:
            task_id: 任务 ID
            status: 新状态 (pending/running/completed/failed/timeout/cancelled)
            result: 任务结果
            error: 错误信息

        Returns:
            True if status updated successfully
        """
        now = datetime.utcnow().isoformat()  # 使用 UTC 时间避免时区问题，A2A 协议要求 UTC

        redis = self._get_redis()
        current = None
        if redis:
            try:
                current = redis.hget(
                    self._make_task_key(task_id), "status"
                )
            except Exception as e:
                logger.warning("a2a_redis_status_read_failed", error=str(e))

        if not current:
            current = self._get_task_status_db(task_id).get("status")
        if current in TASK_STATUS_TRANSITIONS and status not in TASK_STATUS_TRANSITIONS[current]:
            logger.warning(
                "a2a_invalid_status_transition",
                task_id=task_id,
                from_status=current,
                to_status=status,
            )
            return False

        if not self._update_task_status_db(task_id, status, result=result, error=error):
            return False

        if redis:
            try:
                task_data = {"status": status, "updated_at": now}
                if result is not None:
                    task_data["result"] = json.dumps(result, ensure_ascii=False)
                if error is not None:
                    task_data["error"] = error
                if status in (
                    A2ATaskStatus.COMPLETED,
                    A2ATaskStatus.FAILED,
                    A2ATaskStatus.TIMEOUT,
                    A2ATaskStatus.CANCELLED,
                ):
                    task_data["completed_at"] = now
                redis.hset(self._make_task_key(task_id), mapping=task_data)
            except Exception as e:
                logger.warning("a2a_redis_status_update_failed", error=str(e))
                if hasattr(redis, "delete"):
                    with suppress(Exception):
                        redis.delete(self._make_task_key(task_id))

        logger.info("a2a_task_status_updated", task_id=task_id, status=status)
        return True

    def get_task_status(self, task_id: str) -> dict:
        """
        轮询接口：获取任务状态。
        优先从 Redis 读取，降级到数据库。

        Returns:
            {task_id, status, result, error, created_at, updated_at, completed_at}
        """
        redis = self._get_redis()
        if redis:  # Redis 优先，因为状态更新也优先写 Redis，保证读到的数据是最新的
            try:
                data = redis.hgetall(
                    self._make_task_key(task_id)
                )  # HGETALL 一次性获取所有字段，减少网络往返
                if data:
                    result = dict(data)
                    if "result" in result:
                        with suppress(json.JSONDecodeError, TypeError):
                            result["result"] = json.loads(
                                result["result"]
                            )  # 反序列化 JSON 字符串为 Python 对象
                    return result
            except Exception as e:
                logger.warning("a2a_redis_status_read_failed", error=str(e))

        return self._get_task_status_db(task_id)  # Redis 不可用时降级到数据库查询

    def _store_task(self, task_data: dict[str, Any]) -> str:
        """Store task and initialize Redis state"""
        company_id = task_data.get("company_id")
        if company_id is None:
            raise ValueError("company_id is required to store an A2A task")

        create_kwargs = {
            "sender": task_data["sender"],
            "recipients": task_data["recipient"],
            "task": task_data["description"],
            "task_type": task_data["type"],
            "company_id": company_id,
            "payload": task_data.get("payload", {}),
        }
        if task_data.get("id"):
            create_kwargs["message_id"] = task_data["id"]
        task_id = self.db.create_a2a_message(
            **create_kwargs,
        )

        # 数据库是持久化事实源，成功后再刷新 Redis 缓存。
        redis = self._get_redis()
        if redis:
            try:
                initial_data = {
                    "status": A2ATaskStatus.PENDING,  # 新任务初始状态统一为 PENDING
                    "task_type": task_data.get("type", "general"),
                    "sender": task_data.get("sender", ""),
                    "recipient": task_data.get("recipient", ""),
                    "description": task_data.get("description", ""),
                    "payload": json.dumps(
                        task_data.get("payload", {}), ensure_ascii=False
                    ),  # 保存原始 payload 以便后续步骤回溯
                    "company_id": str(company_id),
                    "created_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat(),
                }
                redis.hset(self._make_task_key(task_id), mapping=initial_data)
                redis.expire(
                    self._make_task_key(task_id), 86400
                )  # 24 小时 TTL，避免 Redis 内存被历史任务无限占用
            except Exception as e:
                logger.warning("a2a_redis_state_init_failed", error=str(e))

        return task_id

    def _update_task_status_db(
        self,
        task_id: str,
        status: str,
        result: dict = None,
        error: str = None,
    ) -> bool:
        """Fallback: 更新数据库中的任务状态"""
        try:
            stored_result = None
            if result is not None or error is not None:
                payload = dict(result or {})
                if error is not None:
                    payload["error"] = error
                stored_result = json.dumps(payload, ensure_ascii=False)
            return self.db.update_a2a_message_status(task_id, status, stored_result)
        except Exception as e:
            logger.error(f"Failed to update task status in DB: {e}")
            return False  # 数据库更新失败时返回 False，让调用方知道状态未持久化

    def _get_task_status_db(self, task_id: str) -> dict:
        """Fallback: 从数据库读取任务状态"""
        try:
            result = self.db.get_a2a_message_status(task_id)
            if result:
                return result
        except Exception as e:
            logger.error(f"Failed to read task status from DB: {e}")
        return {"task_id": task_id, "status": "unknown"}  # 兜底返回 unknown，避免前端因空返回而崩溃

    # ── 标准化 Agent Card ──────────────────────────────────

    def get_agent_card(self, agent_name: str) -> dict[str, Any] | None:
        """
        Get standardized agent card aligned with Google A2A spec.
        Includes: name, url, skills, defaultInputModes, defaultOutputModes, capabilities.
        """
        try:
            agent = self.db.get_agent_by_name(agent_name)
            if not agent:
                return None  # 返回 None 让调用方自行处理"Agent 不存在"的逻辑

            card = {
                "name": agent.name,
                "description": agent.description,
                "url": f"/a2a/agents/{agent.name}",  # RESTful 风格端点，符合 A2A 规范的 Agent 发现机制
                "version": "1.0.0",  # 固定版本号，简化版本协商
                "protocol": "a2a",  # 协议标识，用于前端判断是否需要 A2A 适配
                "capabilities": self._extract_capabilities(agent),  # 从 agent 模型中提取能力列表
                "skills": self._extract_skills(agent),  # 基于 capabilities 生成技能卡片
                "defaultInputModes": ["text", "json"],  # 声明支持的输入格式，便于调用方适配
                "defaultOutputModes": ["text", "json"],  # 声明支持的输出格式
                "company_id": agent.company_id,
                "status": "active",
                "registered_at": agent.created_at.isoformat()
                if hasattr(agent.created_at, "isoformat")
                else str(agent.created_at),  # 兼容 datetime 和字符串两种类型
            }

            # 动态同步 MCP 工具列表到 capabilities
            try:
                from app.tools.loader import get_tool_loader  # 延迟导入，避免循环依赖

                loader = get_tool_loader()
                card["mcp_tools"] = (
                    loader.get_health_status()
                )  # 附加 MCP 工具健康状态，帮助发现可用工具
            except Exception:  # MCP 工具加载失败不影响 Agent Card 的返回
                pass

            return card

        except Exception as e:
            logger.error(f"Failed to get agent card for {agent_name}: {e}")
            return None

    def _extract_skills(self, agent) -> list[dict]:
        """Extract agent skills from registered capabilities"""
        capabilities = self._extract_capabilities(agent)
        return [
            {"id": cap, "name": cap, "description": self._get_skill_description(cap)}
            for cap in capabilities
        ]  # 每个 capability 映射为一个 skill，提供中文描述

    def _get_skill_description(self, skill_id: str) -> str:
        """Get skill description from registry"""
        SKILL_DESCRIPTIONS = {  # 硬编码的中文技能描述映射表，方便前端展示给用户
            "search_kols": "搜索达人",
            "generate_outreach": "生成邀约话术",
            "generate_script": "生成视频脚本",
            "generate_performance_report": "生成效果报告",
            "generate_strategy_suggestion": "生成策略建议",
            "check_delivery_status": "查询配送状态",
            "generate_arrival_script": "生成到货提醒",
            "search_knowledge": "知识检索",
            "add_knowledge": "添加知识",
            "delegate_task": "任务委派",
            "a2a_delegate_task": "A2A 任务委派",
        }
        return SKILL_DESCRIPTIONS.get(skill_id, skill_id)  # 未知技能返回原始 ID 作为兜底

    def _resolve_registry_agent_key(self, agent_name: str) -> str | None:
        """Resolve a configured built-in agent by key or display name."""
        try:
            from app.agents import get_active_agents

            normalized = str(agent_name or "").strip().lower()
            if not normalized:
                return None

            for key, info in get_active_agents().items():
                aliases = {
                    key,
                    str(info.get("name_display", "")),
                    str(info.get("module", "")).rsplit(".", 1)[-1],
                }
                if normalized in {alias.strip().lower() for alias in aliases if alias}:
                    return key
        except Exception as e:
            logger.warning("a2a_registry_agent_resolve_failed", error=str(e))
        return None

    def _registry_capabilities(self, agent_key: str, info: dict) -> list[str]:
        capabilities = [agent_key]
        role = info.get("role")
        if role:
            capabilities.append(str(role))

        try:
            from app.agents import get_agent_definition

            definition = get_agent_definition(agent_key) or {}
            tools = definition.get("default_tools") or []
            if isinstance(tools, list):
                capabilities.extend(str(tool) for tool in tools if tool)
        except Exception as e:
            logger.warning("a2a_registry_capabilities_failed", agent=agent_key, error=str(e))

        deduped = []
        seen = set()
        for capability in capabilities:
            if capability not in seen:
                seen.add(capability)
                deduped.append(capability)
        return deduped

    def _registry_agent_card(self, agent_key: str, info: dict, company_id: int) -> dict:
        display_name = info.get("name_display") or agent_key
        role = info.get("role", "agent")
        now = datetime.utcnow().isoformat() + "Z"
        capabilities = self._registry_capabilities(agent_key, info)
        return {
            "name": agent_key,
            "display_name": display_name,
            "description": (
                f"Built-in AgentX catalog agent '{agent_key}' ({role}). "
                "This card describes configured system capability, not live runtime telemetry."
            ),
            "url": f"/a2a/agents/{agent_key}",
            "version": "1.0.0",
            "protocol": "a2a",
            "capabilities": capabilities,
            "skills": [
                {
                    "id": capability,
                    "name": capability,
                    "description": self._get_skill_description(capability),
                }
                for capability in capabilities
            ],
            "defaultInputModes": ["text", "json"],
            "defaultOutputModes": ["text", "json"],
            "company_id": company_id,
            "status": "configured",
            "source": "agent_registry",
            "registered_at": now,
        }

    def _registry_agent_cards(self, company_id: int) -> list[dict]:
        try:
            from app.agents import get_active_agents

            return [
                self._registry_agent_card(agent_key, info, company_id)
                for agent_key, info in get_active_agents().items()
            ]
        except Exception as e:
            logger.warning("a2a_registry_discovery_failed", company_id=company_id, error=str(e))
            return []

    # ── Agent 发现与任务委派（供 app/api/a2a.py 路由调用） ──────────────────────────────────

    def discover_agents(self, company_id: int) -> list[dict]:
        """
        发现当前公司下所有 active 状态的 Agent，转换为 A2A AgentCard 格式返回。
        复用 get_agent_card 生成标准化卡片，单个 Agent 构建失败不影响整体返回。
        """
        try:
            # 复用数据库管理器按公司查询 Agent 列表
            agents = self.db.get_agents_by_company(company_id)
        except Exception as e:
            # 数据库查询失败时降级到内置 Agent 目录，避免阻断 A2A 发现端点
            logger.warning(f"Failed to query agents for company {company_id}: {e}")
            agents = []

        cards = []
        for agent in agents:
            try:
                # 复用 get_agent_card 生成标准化 AgentCard，避免重复构建逻辑
                card = self.get_agent_card(agent.name)
                if card:
                    cards.append(card)
            except Exception as e:
                # 单个 Agent 卡片构建失败时跳过，继续处理其他 Agent
                logger.warning(
                    f"Failed to build agent card for {getattr(agent, 'name', 'unknown')}: {e}"
                )
                continue
        if cards:
            return cards
        return self._registry_agent_cards(company_id)

    def send_task(
        self,
        target_agent_name: str,
        task_message: str,
        task_type: str = "general",
        payload: dict = None,
        company_id: int | None = None,
    ) -> dict:
        """
        创建任务并委派给目标 Agent，初始状态为 pending。
        复用 _store_task 持久化任务记录（内部已初始化 pending 状态）。
        """
        # 校验目标 Agent 是否存在，避免向不存在的 Agent 委派任务
        try:
            try:
                agent = self.db.get_agent_by_name(
                    target_agent_name,
                    company_id=company_id,
                )
            except TypeError:
                agent = self.db.get_agent_by_name(target_agent_name)
        except Exception as e:
            logger.warning("a2a_agent_lookup_failed", target=target_agent_name, error=str(e))
            agent = None
        registry_agent_key = self._resolve_registry_agent_key(target_agent_name)
        if not agent and not registry_agent_key:
            return {"success": False, "error": "Agent not found"}
        agent_company_id = getattr(agent, "company_id", None) if agent else None
        if company_id is not None and agent_company_id is not None and agent_company_id != company_id:
            return {"success": False, "error": "Agent not found"}
        resolved_company_id = company_id if company_id is not None else agent_company_id
        if resolved_company_id is None:
            return {"success": False, "error": "company_id is required"}
        recipient = agent.name if agent else registry_agent_key

        # 构建任务数据字典，_store_task 期望 sender/recipient/description/type/payload 等键
        task_data = {
            "sender": "a2a_service",  # A2A 服务作为统一发送方
            "recipient": recipient,
            "description": task_message,
            "type": task_type,
            "payload": payload or {},
            "company_id": resolved_company_id,
        }

        # 复用 _store_task 创建任务记录，内部已将 Redis/DB 状态初始化为 pending
        try:
            task_id = self._store_task(task_data)
        except Exception as e:
            logger.error("a2a_task_persistence_failed", error=str(e))
            return {"success": False, "error": "Task persistence failed"}

        return {
            "success": True,
            "task_id": task_id,
            "message": "Task delegated",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }


# 模块级单例变量：延迟初始化，避免在 import 阶段就创建数据库连接
_a2a_adapter_instance = None


def get_a2a_adapter() -> A2AAdapter:
    """获取 A2A 适配器单例。首次调用时用全局 db 实例初始化，后续直接返回缓存实例"""
    global _a2a_adapter_instance
    if _a2a_adapter_instance is None:
        from app.database import db  # 延迟导入避免循环依赖

        _a2a_adapter_instance = A2AAdapter(db_manager=db)
    return _a2a_adapter_instance
