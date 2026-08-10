"""
Google A2A Protocol Adapter for AgentX Stage 22
Provides standardized Agent-to-Agent communication using Google A2A protocol.
Enhanced with task lifecycle management, Redis state storage, and capability negotiation.
"""

import json  # A2A 协议传输层使用 JSON 作为标准序列化格式，跨语言兼容
import logging  # 结构化日志用于追踪 Agent 间通信的完整链路
from datetime import datetime  # 所有任务状态变更都需精确时间戳，便于审计和超时判断
from typing import Any, Optional  # Any 用于灵活处理不同 Agent 返回的异构数据；Optional 用于可空字段的显式声明

# 使用模块级 logger 而非 root logger，便于按通信模块过滤和分级查看日志
logger = logging.getLogger(__name__)

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
    A2ATaskStatus.PENDING: [A2ATaskStatus.RUNNING, A2ATaskStatus.CANCELLED],  # 待处理只能开始执行或被取消
    A2ATaskStatus.RUNNING: [A2ATaskStatus.COMPLETED, A2ATaskStatus.FAILED, A2ATaskStatus.TIMEOUT, A2ATaskStatus.CANCELLED],  # 运行中四种出口
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
                redis_url = getattr(settings, 'REDIS_URL', 'redis://localhost:6379/0')  # 生产环境通过配置注入 Redis 地址
                self._redis = redis.from_url(redis_url, decode_responses=True)  # decode_responses 避免手动 decode 字节串
                self._redis.ping()  # 立即验证连接可用性，连接失败则走数据库降级
                logger.info("a2a_redis_connected")
            except Exception as e:
                logger.warning("a2a_redis_unavailable", error=str(e),
                               suggestion="Redis 不可用，A2A 任务状态将仅使用数据库存储")
                self._redis = None  # 保持 None，后续所有操作走数据库降级路径
        return self._redis

    # ── 任务状态管理 ──────────────────────────────────────

    def _make_task_key(self, task_id: str) -> str:
        """生成 Redis key: a2a:task:{task_id}"""
        return f"a2a:task:{task_id}"  # 使用统一前缀命名空间，方便按前缀批量清理或监控 Redis 键

    def set_task_status(self, task_id: str, status: str, result: dict = None,
                        error: str = None) -> bool:
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
        if redis:  # Redis 优先：高性能状态读写，适合高频轮询场景
            try:
                # 获取当前状态，校验流转
                current = redis.hget(self._make_task_key(task_id), "status")  # 先读后写，确保状态流转合法性
                if current and status not in TASK_STATUS_TRANSITIONS.get(current, []):  # 白名单校验，拒绝非法跳跃
                    logger.warning("a2a_invalid_status_transition",
                                   task_id=task_id, from_status=current, to_status=status)
                    return False  # 返回 False 而非抛异常，让调用方可以优雅处理

                task_data = {
                    "status": status,
                    "updated_at": now,
                }
                if result is not None:
                    task_data["result"] = json.dumps(result, ensure_ascii=False)  # ensure_ascii=False 保留中文可读性
                if error is not None:
                    task_data["error"] = error
                if status in (A2ATaskStatus.COMPLETED, A2ATaskStatus.FAILED,
                              A2ATaskStatus.TIMEOUT, A2ATaskStatus.CANCELLED):  # 终态统一记录完成时间
                    task_data["completed_at"] = now

                redis.hset(self._make_task_key(task_id), mapping=task_data)  # HSET 原子操作，避免并发覆盖
                logger.info("a2a_task_status_updated", task_id=task_id, status=status)
                return True
            except Exception as e:
                logger.warning("a2a_redis_status_update_failed", error=str(e))

        # Fallback: 更新数据库
        return self._update_task_status_db(task_id, status)

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
                data = redis.hgetall(self._make_task_key(task_id))  # HGETALL 一次性获取所有字段，减少网络往返
                if data:
                    result = dict(data)
                    if "result" in result:
                        try:
                            result["result"] = json.loads(result["result"])  # 反序列化 JSON 字符串为 Python 对象
                        except (json.JSONDecodeError, TypeError):  # 容错：如果 result 不是合法 JSON，保持原样
                            pass
                    return result
            except Exception as e:
                logger.warning("a2a_redis_status_read_failed", error=str(e))

        return self._get_task_status_db(task_id)  # Redis 不可用时降级到数据库查询

    def _store_task(self, task_data: dict[str, Any]) -> str:
        """Store task and initialize Redis state"""
        task_id = task_data.get('id', f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}")  # 如果没有提供 id，自动生成带时间戳的唯一 ID

        # 初始化 Redis 状态
        redis = self._get_redis()
        if redis:  # Redis 写入失败不影响数据库存储，两者独立执行
            try:
                initial_data = {
                    "status": A2ATaskStatus.PENDING,  # 新任务初始状态统一为 PENDING
                    "task_type": task_data.get("type", "general"),
                    "sender": task_data.get("sender", ""),
                    "recipient": task_data.get("recipient", ""),
                    "description": task_data.get("description", ""),
                    "payload": json.dumps(task_data.get("payload", {}), ensure_ascii=False),  # 保存原始 payload 以便后续步骤回溯
                    "created_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat(),
                }
                redis.hset(self._make_task_key(task_id), mapping=initial_data)
                redis.expire(self._make_task_key(task_id), 86400)  # 24 小时 TTL，避免 Redis 内存被历史任务无限占用
            except Exception as e:
                logger.warning("a2a_redis_state_init_failed", error=str(e))

        # 数据库存储：作为持久化兜底，Redis 过期后数据仍可查询
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO a2a_messages (
                    message_id, sender_agent_name, recipient_agent_name, 
                    task_description, task_type, payload, 
                    company_id, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task_id, task_data['sender'], task_data['recipient'],
                task_data['description'], task_data['type'], json.dumps(task_data['payload']),
                1, A2ATaskStatus.PENDING, datetime.utcnow().isoformat()
            ))
            conn.commit()
            conn.close()  # 显式关闭连接，避免连接池耗尽
        except Exception as e:
            logger.error(f"Failed to store task in DB: {e}")

        return task_id

    def _update_task_status_db(self, task_id: str, status: str) -> bool:
        """Fallback: 更新数据库中的任务状态"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            now = datetime.utcnow().isoformat()
            cursor.execute(
                "UPDATE a2a_messages SET status = ?, completed_at = ? WHERE message_id = ?",
                (status, now, task_id)
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to update task status in DB: {e}")
            return False  # 数据库更新失败时返回 False，让调用方知道状态未持久化

    def _get_task_status_db(self, task_id: str) -> dict:
        """Fallback: 从数据库读取任务状态"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT status, created_at, completed_at FROM a2a_messages WHERE message_id = ?",
                (task_id,)
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                return {
                    "task_id": task_id,
                    "status": row[0],
                    "created_at": row[1],
                    "completed_at": row[2],
                }
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
                "registered_at": agent.created_at.isoformat() if hasattr(agent.created_at, 'isoformat') else str(agent.created_at),  # 兼容 datetime 和字符串两种类型
            }

            # 动态同步 MCP 工具列表到 capabilities
            try:
                from app.tools.loader import get_tool_loader  # 延迟导入，避免循环依赖
                loader = get_tool_loader()
                card["mcp_tools"] = loader.get_health_status()  # 附加 MCP 工具健康状态，帮助发现可用工具
            except Exception:  # MCP 工具加载失败不影响 Agent Card 的返回
                pass

            return card

        except Exception as e:
            logger.error(f"Failed to get agent card for {agent_name}: {e}")
            return None

    def _extract_skills(self, agent) -> list[dict]:
        """Extract agent skills from registered capabilities"""
        capabilities = self._extract_capabilities(agent)
        return [{"id": cap, "name": cap, "description": self._get_skill_description(cap)}
                for cap in capabilities]  # 每个 capability 映射为一个 skill，提供中文描述

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
