"""
AI 自动进化引擎 (Phase 7)

三层记忆系统:
  - Layer 1 工作记忆 (Working Memory): AgentState 运行时上下文
  - Layer 2 短期记忆 (Short-term): PostgreSQL + Redis, 热数据快速检索
  - Layer 3 长期记忆 (Long-term): Milvus 向量存储, 压缩后的知识模式

核心机制:
  - 任务完成后自动摘要写入短期记忆
  - 睡眠巩固: 定时/阈值触发, 摘要压缩 + 去重 + 模式提取 → 长期记忆
  - 反馈驱动进化: 审核决策 → 偏好提取 → 上下文注入
  - Skill 自动优化: 历史任务分析 → 优化建议 → 人工审核

注：LoRA 微调框架已移除（T2.6），保留 user_lora 表结构与历史数据，企业版/未来再启用
"""  # AI自动进化引擎：通过记忆系统、反馈学习实现Agent的持续自我优化

import threading  # 用于所有引擎的线程锁和定时器线程
import time  # 用于生成唯一ID中的时间戳和定时器间隔
from dataclasses import dataclass, field  # 用于所有记忆/日志类型的数据载体
from datetime import datetime, timedelta  # datetime用于时间戳，timedelta用于TTL计算和间隔判断
from enum import StrEnum  # 使用StrEnum，因为记忆层级和事件类型需要字符串表示

from app.core.logging import get_logger  # 统一日志记录

logger = get_logger(__name__)  # 模块级logger


class MemoryTier(StrEnum):  # 记忆层级枚举，对应认知科学的三层记忆模型
    WORKING = "working"  # 工作记忆：当前任务上下文，生命周期=单次任务
    SHORT_TERM = "short_term"  # 短期记忆：7-30天内的任务记录
    LONG_TERM = "long_term"  # 长期记忆：半永久的知识模式


class EvolutionEventType(StrEnum):  # 进化事件类型枚举，用于全量演化日志的分类和查询
    CONFIG_CHANGE = "config_change"  # 配置变更：人工调整Agent参数
    MEMORY_CONSOLIDATION = "memory_consolidation"  # 记忆巩固：睡眠引擎执行压缩
    SKILL_UPDATE = "skill_update"  # Skill更新：优化建议被采纳并部署
    MODEL_SWITCH = "model_switch"  # 模型切换：路由策略变更
    FEEDBACK_APPLIED = "feedback_applied"  # 反馈应用：审核意见被提取为偏好
    PATTERN_EXTRACTED = "pattern_extracted"  # 模式提取：从记忆中识别出重复模式
    OPTIMIZATION_SUGGESTION = "optimization_suggestion"  # 优化建议：Skill优化引擎生成建议


# ── 7.1 三层记忆系统 ──────────────────────────────────────────────────


@dataclass  # 使用dataclass，因为WorkingMemory是纯数据载体
class WorkingMemory:  # 工作记忆：仅存在于单次任务生命周期，任务结束后丢弃
    """工作记忆: Agent 运行时上下文, 单次任务生命周期内有效"""

    agent_key: str = ""  # Agent标识
    company_id: int = 0  # 企业ID
    task_id: str = ""  # 任务唯一标识
    messages: list[dict] = field(default_factory=list)  # 对话消息，使用field避免可变默认值
    tool_calls: list[dict] = field(default_factory=list)  # 工具调用记录
    current_plan: dict | None = None  # 当前执行计划，None表示未制定
    retrieved_context: str = ""  # RAG检索到的上下文
    intermediate_results: dict = field(default_factory=dict)  # 中间结果
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())  # 创建时间


@dataclass  # 使用dataclass，因为ShortTermMemory是纯数据载体
class ShortTermMemory:  # 短期记忆：存储在PostgreSQL+Redis中，保留7-30天
    """短期记忆: PostgreSQL + Redis 存储, 7-30天保留, 记录型数据"""

    id: str = ""  # 唯一标识
    company_id: int = 0  # 企业ID，用于多租户隔离
    agent_key: str = ""  # Agent标识
    task_id: str = ""  # 关联的任务ID
    task_type: str = ""  # 任务类型
    summary: str = ""  # 任务摘要
    outcome: str = ""  # 任务结果
    key_decisions: list[str] = field(default_factory=list)  # 关键决策列表
    errors: list[str] = field(default_factory=list)  # 错误列表
    feedback_score: float = 0.0  # 反馈评分，0.0-1.0
    tokens_used: int = 0  # 消耗的token数
    duration_seconds: float = 0.0  # 任务耗时（秒）
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())  # 创建时间
    expires_at: str = field(
        default_factory=lambda: (  # 过期时间，默认30天后自动清理
            datetime.utcnow() + timedelta(days=30)
        ).isoformat()
    )


@dataclass  # 使用dataclass，因为LongTermMemory是纯数据载体
class LongTermMemory:  # 长期记忆：存储在Milvus向量库，半永久保留
    """长期记忆: Milvus 向量存储, 半永久保留, 压缩后的知识模式"""

    id: str = ""  # 唯一标识
    company_id: int = 0  # 企业ID
    agent_key: str = ""  # Agent标识
    pattern_type: str = ""  # 模式类型（performance/error/collaboration）
    pattern_summary: str = ""  # 模式摘要
    embedding: list[float] | None = None  # 向量嵌入，None表示尚未计算
    source_task_ids: list[str] = field(default_factory=list)  # 来源任务ID列表
    confidence: float = 0.0  # 模式置信度
    usage_count: int = 0  # 使用次数
    last_used_at: str = ""  # 最后使用时间
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())  # 创建时间
    consolidated_count: int = 0  # 被巩固的次数


# ── 7.2 记忆自动写入 ─────────────────────────────────────────────────


class MemoryAutoWriter:  # 记忆自动写入器：Agent任务完成后自动生成摘要并写入短期记忆
    """Agent 任务完成后自动摘要写入短期记忆"""

    def __init__(self):  # 初始化待写入队列和线程锁
        self._pending_writes: list[ShortTermMemory] = []  # 待写入队列，用于批量刷新
        self._lock = threading.Lock()  # 线程锁，保护队列操作

    def write_from_task(  # 从任务上下文自动生成短期记忆条目
        self,
        company_id: int,
        agent_key: str,
        task_id: str,
        task_type: str,
        messages: list,
        output: str,
        errors: list[str] | None = None,
        tokens_used: int = 0,
        duration_seconds: float = 0.0,
    ) -> ShortTermMemory:
        summary = self._generate_summary(messages, output)  # 生成摘要
        decisions = self._extract_decisions(messages, output)  # 提取关键决策

        memory = ShortTermMemory(  # 构建短期记忆条目
            id=f"stm_{company_id}_{agent_key}_{task_id}_{int(time.time())}",  # 使用复合键生成唯一ID
            company_id=company_id,
            agent_key=agent_key,
            task_id=task_id,
            task_type=task_type,
            summary=summary,
            outcome=output[:500],  # 截取前500字符作为结果摘要，防止过长
            key_decisions=decisions,
            errors=errors or [],  # 空列表兜底
            tokens_used=tokens_used,
            duration_seconds=duration_seconds,
        )

        with self._lock:  # 线程安全地加入待写入队列
            self._pending_writes.append(memory)

        self._persist_to_db(memory)  # 持久化到数据库
        self._cache_to_redis(memory)  # 缓存到Redis

        logger.info(
            "memory_auto_written",
            company_id=company_id,
            agent_key=agent_key,
            memory_id=memory.id,
            summary_len=len(summary),
        )
        return memory

    def _generate_summary(
        self, messages: list, output: str
    ) -> str:  # 基于规则生成简单摘要，不依赖LLM
        lines = []
        lines.append(f"任务输出摘要: {output[:200]}")  # 截取输出前200字符
        if messages:  # 仅在有消息时提取用户需求
            human_msgs = [m for m in messages if m.get("role") == "user"]
            if human_msgs:
                lines.append(
                    f"用户需求: {human_msgs[-1].get('content', '')[:150]}"
                )  # 取最后一条用户消息的前150字符
        return " | ".join(lines)  # 用分隔符连接，简洁明确

    def _extract_decisions(
        self, messages: list, output: str
    ) -> list[str]:  # 从消息中提取关键决策关键词
        decisions = []
        for m in messages:
            content = m.get("content", "")
            if "决定" in content or "建议" in content or "选择" in content:  # 中文决策关键词
                decisions.append(content[:100])
        if "审核" in output or "通过" in output:  # 审核相关关键词
            decisions.append(f"审核结果: {output[:80]}")
        if not decisions:  # 没有提取到决策时用输出摘要兜底
            decisions.append(f"执行摘要: {output[:80]}")
        return decisions[:5]  # 最多返回5条决策

    def _persist_to_db(self, memory: ShortTermMemory):  # 持久化到数据库，使用延迟导入
        try:
            agent_runtime = _get_agent_runtime()  # 获取运行时实例
            if agent_runtime and hasattr(agent_runtime, "store_memory"):  # 防御性检查
                agent_runtime.store_memory(
                    memory.company_id,
                    memory.id,
                    memory.agent_key,
                    memory.summary,
                    memory.outcome,
                    memory.tokens_used,
                )
        except Exception as e:
            logger.warning("memory_db_persist_failed", error=str(e))

    def _cache_to_redis(self, memory: ShortTermMemory):  # 缓存到Redis，7天过期
        try:
            from app.services.session_store import get_session_store  # 延迟导入，避免循环依赖

            store = get_session_store()
            memory_key = f"stm:{memory.company_id}:{memory.agent_key}:latest"  # 使用命名空间前缀
            import json  # 仅在需要时导入

            data = {
                "id": memory.id,
                "summary": memory.summary[:500],  # 截取摘要，Redis中存储精简版
                "outcome": memory.outcome[:300],
                "tokens_used": memory.tokens_used,
                "created_at": memory.created_at,
            }
            # session_store.set_cache 已改为 async，这里用 create_task 非阻塞调用
            # 调用方是同步方法，无法 await；用 create_task 把协程调度到事件循环上执行
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    store.set_cache(memory_key, json.dumps(data, ensure_ascii=False), 7 * 86400)
                )  # 7天TTL
            except RuntimeError:
                # 没有运行中的事件循环（如同步线程中调用），跳过 Redis 缓存
                pass
        except Exception:  # Redis缓存失败不影响主流程
            pass

    def get_pending_count(self) -> int:  # 获取待写入队列长度
        return len(self._pending_writes)

    def flush_all(self):  # 批量刷新所有待写入记忆
        with self._lock:
            count = len(self._pending_writes)
            self._pending_writes.clear()  # 清空队列
        logger.info("memory_flush_complete", flushed_count=count)
        return count


# ── 7.3 睡眠巩固引擎 ──────────────────────────────────────────────────


class SleepConsolidationEngine:  # 睡眠巩固引擎：模拟人类睡眠记忆巩固过程，将短期记忆压缩为长期知识模式
    """定时/阈值触发 → 摘要压缩 + 去重 + 模式提取 → 写入长期记忆"""

    DEFAULT_INTERVAL_HOURS = 4  # 默认4小时触发一次，平衡计算成本和时效性
    DEFAULT_THRESHOLD_COUNT = 20  # 累积20条短期记忆后触发，基于阈值
    DEFAULT_MAX_BATCH = 50  # 每次处理最多50条，防止内存溢出

    def __init__(  # 初始化睡眠引擎，支持自定义间隔和阈值
        self,
        interval_hours: int | None = None,
        threshold_count: int | None = None,
    ):
        self.interval_hours = (
            interval_hours if interval_hours is not None else self.DEFAULT_INTERVAL_HOURS
        )  # 使用None而非or，因为0是合法值
        self.threshold_count = (
            threshold_count if threshold_count is not None else self.DEFAULT_THRESHOLD_COUNT
        )
        self._last_consolidation: dict[int, str] = {}  # 记录每个企业的最后巩固时间
        self._short_term_counts: dict[int, int] = {}  # 记录每个企业的短期记忆计数
        self._timer: threading.Timer | None = None  # 定时器实例
        self._running = False  # 运行状态标志

    def should_consolidate(self, company_id: int) -> bool:  # 判断是否需要执行巩固：阈值或间隔触发
        count = self._short_term_counts.get(company_id, 0)
        if count >= self.threshold_count:  # 基于数量的阈值触发
            return True

        last = self._last_consolidation.get(company_id)
        if last:  # 基于时间的间隔触发
            last_dt = datetime.fromisoformat(last)
            return datetime.utcnow() - last_dt >= timedelta(
                hours=self.interval_hours
            )  # 超过间隔时间
        return True  # 从未巩固过，立即执行

    def consolidate(
        self, company_id: int
    ) -> dict:  # 执行一次巩固周期：获取→压缩→去重→提取模式→写入
        memories = self._fetch_short_term_memories(company_id)  # 获取短期记忆
        if not memories:  # 无记忆时跳过
            return {"status": "no_memories", "company_id": company_id}

        compressed = self._compress_memories(memories)  # 压缩去重
        deduplicated = self._deduplicate(compressed)  # 二次去重
        patterns = self._extract_patterns(deduplicated, company_id)  # 提取模式
        self._write_to_long_term(patterns, company_id)  # 写入长期记忆

        self._last_consolidation[company_id] = datetime.utcnow().isoformat()  # 更新最后巩固时间
        self._short_term_counts[company_id] = 0  # 重置计数

        self._log_evolution(
            company_id=company_id,
            event_type=EvolutionEventType.MEMORY_CONSOLIDATION,
            detail={
                "input_count": len(memories),
                "compressed_count": len(compressed),
                "pattern_count": len(patterns),
            },
        )

        return {
            "status": "completed",
            "company_id": company_id,
            "input_memories": len(memories),
            "compressed": len(compressed),
            "patterns_extracted": len(patterns),
            "patterns": [
                {"type": p["type"], "summary": p["summary"][:100], "confidence": p["confidence"]}
                for p in patterns
            ],
        }

    def _fetch_short_term_memories(
        self, company_id: int
    ) -> list[dict]:  # 从AgentRuntime获取近期记忆
        try:
            agent_runtime = _get_agent_runtime()
            if agent_runtime and hasattr(agent_runtime, "get_recent_memories"):  # 防御性检查
                return agent_runtime.get_recent_memories(
                    company_id,
                    limit=self.DEFAULT_MAX_BATCH,  # 限制批量大小
                )
        except Exception as e:
            logger.warning("fetch_memories_failed", error=str(e))
        return []

    def _compress_memories(self, memories: list[dict]) -> list[dict]:  # 基于摘要前200字符的哈希去重
        compressed = []
        seen_hashes = set()  # 使用set做O(1)去重查找
        for mem in memories:
            summary = mem.get("summary", "")
            content_hash = hash(summary[:200])  # 取前200字符的哈希，减少碰撞
            if content_hash in seen_hashes:  # 重复则跳过
                continue
            seen_hashes.add(content_hash)
            compressed.append(
                {  # 提取关键字段，丢弃无关数据
                    "id": mem.get("id", ""),
                    "agent_key": mem.get("agent_key", ""),
                    "summary": summary,
                    "outcome": mem.get("outcome", ""),
                    "errors": mem.get("errors", []),
                    "duration": mem.get("duration_seconds", 0),
                    "tokens": mem.get("tokens_used", 0),
                }
            )
        return compressed

    def _deduplicate(self, memories: list[dict]) -> list[dict]:  # 二次去重，当前为透传，预留扩展
        return memories  # 当前直接返回，未来可增加语义级别的去重

    def _extract_patterns(
        self, memories: list[dict], company_id: int
    ) -> list[dict]:  # 从记忆中提取性能模式和错误模式
        patterns = []
        agent_groups: dict[str, list] = {}  # 按Agent分组
        for mem in memories:
            ak = mem.get("agent_key", "unknown")
            if ak not in agent_groups:
                agent_groups[ak] = []
            agent_groups[ak].append(mem)

        for agent_key, group in agent_groups.items():  # 遍历每个Agent的分组
            if len(group) < 3:  # 少于3条不足以形成可信模式
                continue

            success_count = sum(1 for m in group if not m.get("errors"))  # 统计成功数
            success_rate = success_count / len(group)
            avg_duration = sum(m.get("duration", 0) for m in group) / len(group)
            avg_tokens = sum(m.get("tokens", 0) for m in group) / len(group)

            common_errors: dict[str, int] = {}  # 统计错误频率
            for m in group:
                for err in m.get("errors", []):
                    common_errors[err] = common_errors.get(err, 0) + 1
            top_errors = sorted(common_errors.items(), key=lambda x: x[1], reverse=True)[
                :3
            ]  # 取前3高频错误

            patterns.append(
                {  # 性能模式
                    "company_id": company_id,
                    "agent_key": agent_key,
                    "type": "performance_pattern",
                    "summary": (
                        f"{agent_key} 近{len(group)}次任务: "
                        f"成功率{success_rate:.0%}, "
                        f"平均耗时{avg_duration:.1f}s, "
                        f"平均Token{avg_tokens:.0f}"
                    ),
                    "confidence": min(0.5 + success_rate * 0.5, 0.95),  # 置信度基于成功率，上限0.95
                    "metrics": {
                        "task_count": len(group),
                        "success_rate": success_rate,
                        "avg_duration_seconds": avg_duration,
                        "avg_tokens": avg_tokens,
                        "common_errors": top_errors,
                    },
                }
            )

            if top_errors and top_errors[0][1] >= 2:  # 某错误出现至少2次才形成错误模式
                patterns.append(
                    {
                        "company_id": company_id,
                        "agent_key": agent_key,
                        "type": "error_pattern",
                        "summary": f"{agent_key} 高频错误: {top_errors[0][0]} (出现{top_errors[0][1]}次)",
                        "confidence": min(
                            0.3 + top_errors[0][1] / len(group) * 0.5, 0.85
                        ),  # 置信度基于错误频率占比
                        "common_errors": top_errors,
                    }
                )

        patterns.extend(
            self._extract_cross_agent_patterns(memories, company_id)
        )  # 添加跨Agent协作模式
        return patterns

    def _extract_cross_agent_patterns(
        self, memories: list[dict], company_id: int
    ) -> list[dict]:  # 提取跨Agent协作模式
        agent_pairs: dict[tuple[str, str], int] = {}  # (agent_a, agent_b) → 共现次数
        for i, mem_a in enumerate(memories):
            for j, mem_b in enumerate(memories):
                if i >= j:  # 避免重复计数和自比较
                    continue
                ak_a = mem_a.get("agent_key", "")
                ak_b = mem_b.get("agent_key", "")
                if ak_a == ak_b:  # 同一Agent不计数
                    continue
                if ak_a == "unknown" or ak_b == "unknown":  # 未知Agent忽略
                    continue
                pair = tuple(sorted([ak_a, ak_b]))  # 排序确保(a,b)和(b,a)被视为同一对
                agent_pairs[pair] = agent_pairs.get(pair, 0) + 1

        cross_patterns = []
        for (agent_a, agent_b), count in sorted(
            agent_pairs.items(), key=lambda x: x[1], reverse=True
        )[:3]:  # 取前3高频协作对
            cross_patterns.append(
                {
                    "company_id": company_id,
                    "agent_key": f"{agent_a}↔{agent_b}",
                    "type": "collaboration_pattern",
                    "summary": f"{agent_a} 与 {agent_b} 高频协作 ({count}次)",
                    "confidence": 0.7,  # 固定置信度，因为基于简单共现统计
                }
            )
        return cross_patterns

    def _write_to_long_term(
        self, patterns: list[dict], company_id: int
    ):  # 将提取的模式写入长期记忆
        for pattern in patterns:
            memory = LongTermMemory(  # 转换为LongTermMemory对象
                id=f"ltm_{company_id}_{pattern['agent_key']}_{int(time.time())}",
                company_id=company_id,
                agent_key=pattern["agent_key"],
                pattern_type=pattern["type"],
                pattern_summary=pattern["summary"],
                confidence=pattern["confidence"],
            )
            try:
                self._store_long_term(memory)  # 存储
            except Exception as e:
                logger.warning("ltm_store_failed", error=str(e), pattern=pattern["type"])

    def _store_long_term(self, memory: LongTermMemory):  # 通过公司上下文总线存储长期记忆
        try:
            from app.rag.company_context_bus import get_company_context_bus  # 延迟导入

            bus = get_company_context_bus(str(memory.company_id))  # 获取企业上下文总线
            if bus:
                bus.record_experience(  # 记录为经验条目
                    agent_name=memory.agent_key,
                    task_type=memory.pattern_type,
                    summary=memory.pattern_summary,
                    tags=[memory.pattern_type],
                )
        except Exception as e:
            logger.warning("ltm_bus_store_failed", error=str(e))

    def _log_evolution(
        self, company_id: int, event_type: EvolutionEventType, detail: dict
    ):  # 记录进化事件日志
        log = EvolutionLog(
            company_id=company_id,
            event_type=event_type,
            description=f"睡眠巩固 - {event_type.value}",
            detail=detail,
        )
        get_evolution_logger().record(log)

    def start_scheduler(self):  # 启动定时调度器
        self._running = True
        self._run_timer()

    def _run_timer(self):  # 运行定时器线程，检查间隔不超过1小时
        if not self._running:
            return
        check_interval = min(self.interval_hours * 3600, 3600)  # 上限1小时，防止间隔过长
        self._timer = threading.Timer(check_interval, self._timer_tick)  # 创建定时器
        self._timer.daemon = True  # 守护线程，主程序退出时自动终止
        self._timer.start()

    def _timer_tick(self):  # 定时器回调，检查所有企业是否需要巩固
        try:
            for company_id in list(self._short_term_counts.keys()):  # 使用list避免迭代中修改
                if self.should_consolidate(company_id):
                    self.consolidate(company_id)
        except Exception as e:
            logger.error("consolidation_tick_error", error=str(e))
        if self._running:  # 仍在运行则重新设置定时器
            self._run_timer()

    def stop_scheduler(self):  # 停止定时调度器
        self._running = False
        if self._timer:
            self._timer.cancel()  # 取消定时器

    def notify_new_memory(self, company_id: int):  # 通知有新记忆写入，触发阈值检查
        self._short_term_counts[company_id] = (
            self._short_term_counts.get(company_id, 0) + 1
        )  # 计数+1
        if self.should_consolidate(company_id):  # 达到阈值时立即巩固
            self.consolidate(company_id)


# ── 7.4 EvolutionLog ──────────────────────────────────────────────────


@dataclass  # 使用dataclass，因为EvolutionLog是纯数据载体
class EvolutionLog:  # 进化事件日志条目，记录所有进化相关事件
    company_id: int  # 企业ID，必填
    event_type: EvolutionEventType  # 事件类型，必填
    description: str  # 事件描述，必填
    detail: dict = field(default_factory=dict)  # 事件详情，使用field避免可变默认值
    agent_key: str = ""  # 关联的Agent标识
    operator: str = "system"  # 操作者，默认system表示系统自动操作
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())  # 时间戳


class EvolutionLogger:  # 全量进化日志记录器：内存缓存 + 数据库持久化双写
    """全量演化日志: 配置变更 / 记忆巩固 / Skill 更新 / 模型切换"""

    def __init__(self, max_in_memory: int = 1000):  # 内存中最多保留1000条，防止内存泄漏
        self._logs: list[EvolutionLog] = []  # 内存日志列表
        self._max_in_memory = max_in_memory  # 内存上限
        self._lock = threading.Lock()  # 线程锁，保护日志列表

    def record(self, log: EvolutionLog):  # 记录一条进化日志，内存+数据库双写
        with self._lock:  # 线程安全地追加
            self._logs.append(log)
            if len(self._logs) > self._max_in_memory:  # 超过上限时丢弃最早的日志
                self._logs = self._logs[-self._max_in_memory :]  # 保留最近的1000条

        try:  # 数据库持久化失败不影响内存记录
            self._persist_log(log)
        except Exception as e:
            logger.warning("evolution_log_persist_failed", error=str(e))

        logger.info(  # 记录到应用日志
            "evolution_event",
            event_type=log.event_type.value,
            company_id=log.company_id,
            description=log.description[:100],  # 截取描述前100字符
            agent_key=log.agent_key,
        )

    def _persist_log(self, log: EvolutionLog):  # 持久化到PostgreSQL的evolution_log表
        try:
            from app.database import db  # 延迟导入

            if hasattr(db, "execute"):  # 防御性检查
                db.execute(  # 参数化查询防止SQL注入
                    "INSERT INTO evolution_log "
                    "(company_id, agent_key, event_type, description, detail_json, "
                    "operator, timestamp) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    [
                        log.company_id,
                        log.agent_key,
                        log.event_type.value,
                        log.description,
                        str(log.detail),  # detail字典转为字符串存储
                        log.operator,
                        log.timestamp,
                    ],
                )
        except Exception:  # 持久化失败静默处理
            pass

    def query(  # 多条件查询日志，支持按企业、事件类型、Agent筛选
        self,
        company_id: int | None = None,
        event_type: EvolutionEventType | None = None,
        agent_key: str | None = None,
        limit: int = 50,  # 默认返回50条
    ) -> list[EvolutionLog]:
        with self._lock:  # 线程安全地获取日志快照
            results = self._logs
        if company_id is not None:  # 按企业筛选
            results = [log for log in results if log.company_id == company_id]
        if event_type is not None:  # 按事件类型筛选
            results = [log for log in results if log.event_type == event_type]
        if agent_key:  # 按Agent筛选
            results = [log for log in results if log.agent_key == agent_key]
        return results[-limit:]  # 返回最近的limit条

    def get_evolution_feed(
        self, company_id: int, limit: int = 20
    ) -> list[dict]:  # 获取企业的进化动态流
        logs = self.query(company_id=company_id, limit=limit)
        return [  # 转换为字典格式，便于前端展示
            {
                "event_type": log.event_type.value,
                "description": log.description,
                "detail": log.detail,
                "agent_key": log.agent_key,
                "timestamp": log.timestamp,
                "operator": log.operator,
            }
            for log in logs
        ]

    def clear(self):  # 清空所有日志
        with self._lock:
            self._logs.clear()


# ── 7.5 反馈驱动进化 ──────────────────────────────────────────────────


class FeedbackDrivenEvolution:  # 反馈驱动进化：从人工审核决策中提取偏好，注入Agent上下文
    """审核决策(批准/修改/拒绝) → 提取偏好 → 注入 Agent 上下文"""

    def __init__(self):  # 初始化反馈缓存和偏好缓存
        self._feedback_cache: dict[int, list[dict]] = {}  # 企业ID → 反馈列表
        self._preference_cache: dict[str, list[str]] = {}  # "企业ID:AgentKey" → 偏好列表
        self._lock = threading.Lock()  # 线程锁

    def record_feedback(  # 记录一条审核反馈并提取偏好
        self,
        company_id: int,
        agent_key: str,
        task_id: str,
        decision: str,  # 审核决策：approved/modified/rejected
        reviewer_notes: str,  # 审核备注
        original_output: str,  # 原始Agent输出
    ):
        feedback = {  # 构建反馈记录
            "company_id": company_id,
            "agent_key": agent_key,
            "task_id": task_id,
            "decision": decision,
            "reviewer_notes": reviewer_notes,
            "original_output": original_output[:500],  # 截取输出前500字符
            "timestamp": datetime.utcnow().isoformat(),
        }

        with self._lock:  # 线程安全地追加到反馈缓存
            if company_id not in self._feedback_cache:
                self._feedback_cache[company_id] = []
            self._feedback_cache[company_id].append(feedback)
            if len(self._feedback_cache[company_id]) > 200:  # 限制每企业最多200条
                self._feedback_cache[company_id] = self._feedback_cache[company_id][-200:]

        preferences = self._extract_preferences(feedback)  # 提取偏好
        self._update_preference_cache(company_id, agent_key, preferences)  # 更新偏好缓存

        get_evolution_logger().record(
            EvolutionLog(  # 记录进化事件
                company_id=company_id,
                event_type=EvolutionEventType.FEEDBACK_APPLIED,
                description=f"反馈驱动进化: {decision} - {reviewer_notes[:80]}",
                detail={
                    "decision": decision,
                    "notes": reviewer_notes,
                    "preferences_extracted": preferences,
                },
                agent_key=agent_key,
            )
        )

    def _extract_preferences(self, feedback: dict) -> list[str]:  # 从反馈中提取偏好规则
        prefs = []
        decision = feedback.get("decision", "")
        notes = feedback.get("reviewer_notes", "")

        if decision == "rejected":  # 拒绝 → 生成"避免"偏好
            prefs.append(f"避免: {notes[:100]}")
        elif decision == "modified":  # 修改 → 生成"调整"偏好
            prefs.append(f"偏好调整: {notes[:100]}")

        if "太冗长" in notes or "精简" in notes:  # 冗长度偏好
            prefs.append("输出偏好: 简洁明了")
        if "详细" in notes or "不够具体" in notes:  # 详细度偏好
            prefs.append("输出偏好: 详细具体")
        if "数据" in notes or "指标" in notes:  # 数据驱动偏好
            prefs.append("偏好日期时段: 用数据说话")
        if "语气" in notes or "称呼" in notes or "礼貌" in notes:  # 沟通风格偏好
            prefs.append("沟通风格: 专业礼貌")

        return prefs

    def _update_preference_cache(
        self, company_id: int, agent_key: str, prefs: list[str]
    ):  # 更新偏好缓存，去重+限制条数
        cache_key = f"{company_id}:{agent_key}"  # 复合缓存键
        with self._lock:
            if cache_key not in self._preference_cache:
                self._preference_cache[cache_key] = []
            for pref in prefs:
                if pref not in self._preference_cache[cache_key]:  # 去重
                    self._preference_cache[cache_key].append(pref)
            if len(self._preference_cache[cache_key]) > 20:  # 限制最多20条偏好
                self._preference_cache[cache_key] = self._preference_cache[cache_key][-20:]

    def get_preferences(
        self, company_id: int, agent_key: str
    ) -> list[str]:  # 获取指定企业的Agent偏好
        cache_key = f"{company_id}:{agent_key}"
        return self._preference_cache.get(cache_key, [])

    def get_preference_context(
        self, company_id: int, agent_key: str
    ) -> str:  # 将偏好格式化为可注入Agent的上下文文本
        prefs = self.get_preferences(company_id, agent_key)
        if not prefs:  # 无偏好返回空字符串
            return ""
        lines = ["[用户偏好 - 从审核反馈中学习]"]  # 上下文前缀
        for i, pref in enumerate(prefs[-8:], 1):  # 取最近8条偏好
            lines.append(f"{i}. {pref}")
        return "\n".join(lines)

    def get_feedback_summary(self, company_id: int, agent_key: str) -> dict:  # 获取反馈统计摘要
        with self._lock:
            feedbacks = self._feedback_cache.get(company_id, [])
            agent_feedbacks = [f for f in feedbacks if f["agent_key"] == agent_key]

        if not agent_feedbacks:  # 无反馈
            return {"total": 0}

        approved = sum(1 for f in agent_feedbacks if f["decision"] == "approved")
        modified = sum(1 for f in agent_feedbacks if f["decision"] == "modified")
        rejected = sum(1 for f in agent_feedbacks if f["decision"] == "rejected")
        total = len(agent_feedbacks)

        return {
            "total": total,
            "approved": approved,
            "modified": modified,
            "rejected": rejected,
            "approval_rate": approved / max(total, 1),  # 防止除零
            "recent_notes": [
                f["reviewer_notes"][:100] for f in agent_feedbacks[-5:]
            ],  # 最近5条备注
            "preferences": self.get_preferences(company_id, agent_key),
        }


# ── 7.6 Skill 自动优化建议 ────────────────────────────────────────────


class SkillOptimizationEngine:
    """分析历史任务数据 → 生成 Skill 优化建议 → 推送审核"""

    def __init__(self):
        self._task_history: list[dict] = []
        self._suggestions: list[dict] = []
        self._lock = threading.Lock()

    def feed_task(self, company_id: int, agent_key: str, task_data: dict):
        with self._lock:
            self._task_history.append(
                {
                    "company_id": company_id,
                    "agent_key": agent_key,
                    "task_type": task_data.get("task_type", ""),
                    "duration_seconds": task_data.get("duration_seconds", 0),
                    "tokens_used": task_data.get("tokens_used", 0),
                    "errors": task_data.get("errors", []),
                    "feedback": task_data.get("feedback", ""),
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )
            if len(self._task_history) > 500:
                self._task_history = self._task_history[-500:]

    def analyze_and_suggest(self, company_id: int, agent_key: str) -> list[dict]:
        with self._lock:
            agent_tasks = [
                t
                for t in self._task_history
                if t["company_id"] == company_id and t["agent_key"] == agent_key
            ]

        if len(agent_tasks) < 5:
            return []

        suggestions = []

        durations = [t["duration_seconds"] for t in agent_tasks if t["duration_seconds"] > 0]
        if len(durations) >= 5:
            avg_duration = sum(durations) / len(durations)
            recent_avg = sum(durations[-3:]) / min(len(durations[-3:]), 1)
            if recent_avg > avg_duration * 1.3:
                suggestions.append(
                    {
                        "type": "performance",
                        "agent_key": agent_key,
                        "suggestion": f"最近3次任务平均耗时 {recent_avg:.0f}s, 较整体均值 {avg_duration:.0f}s 增长 {(recent_avg / avg_duration - 1) * 100:.0f}%, 建议优化 {agent_key} 的 System Prompt 或简化工具调用链",
                        "severity": "warning",
                        "evidence": {
                            "overall_avg_duration": avg_duration,
                            "recent_avg_duration": recent_avg,
                        },
                    }
                )

        error_tasks = [t for t in agent_tasks if t.get("errors")]
        if len(error_tasks) >= 3:
            error_counts: dict[str, int] = {}
            for t in error_tasks:
                for err in t.get("errors", []):
                    error_counts[err] = error_counts.get(err, 0) + 1
            top_err = max(error_counts, key=error_counts.get)
            suggestions.append(
                {
                    "type": "error_handling",
                    "agent_key": agent_key,
                    "suggestion": f"高频错误 ({top_err}) 出现 {error_counts[top_err]} 次, 建议为 {agent_key} 增加错误处理 Skill 或调整工具参数校验",
                    "severity": "critical" if error_counts[top_err] >= 5 else "warning",
                    "evidence": {"error": top_err, "count": error_counts[top_err]},
                }
            )

        feedback_tasks = [t for t in agent_tasks if t.get("feedback")]
        if len(feedback_tasks) >= 3:
            latest_feedback = [t["feedback"][:100] for t in feedback_tasks[-3:]]
            suggestions.append(
                {
                    "type": "output_quality",
                    "agent_key": agent_key,
                    "suggestion": f"近{len(feedback_tasks)}次任务有审核反馈: {'; '.join(latest_feedback)}, 建议更新 {agent_key} 的输出规范",
                    "severity": "info",
                    "evidence": {"feedback_count": len(feedback_tasks), "latest": latest_feedback},
                }
            )

        token_usages = [t["tokens_used"] for t in agent_tasks if t["tokens_used"] > 0]
        if len(token_usages) >= 5:
            avg_tokens = sum(token_usages) / len(token_usages)
            if avg_tokens > 5000:
                suggestions.append(
                    {
                        "type": "cost_optimization",
                        "agent_key": agent_key,
                        "suggestion": f"平均每次任务消耗 {avg_tokens:.0f} tokens, 建议为 {agent_key} 增加缓存或精简上下文注入策略降低成本",
                        "severity": "info" if avg_tokens < 10000 else "warning",
                        "evidence": {"avg_tokens": avg_tokens},
                    }
                )

        with self._lock:
            self._suggestions.extend(suggestions)
            if len(self._suggestions) > 100:
                self._suggestions = self._suggestions[-100:]

        for s in suggestions:
            get_evolution_logger().record(
                EvolutionLog(
                    company_id=company_id,
                    event_type=EvolutionEventType.OPTIMIZATION_SUGGESTION,
                    description=s["suggestion"],
                    detail=s,
                    agent_key=agent_key,
                )
            )

        return suggestions

    def get_pending_suggestions(
        self, company_id: int | None = None, agent_key: str | None = None
    ) -> list[dict]:
        with self._lock:
            results = self._suggestions
        if company_id is not None:
            results = [s for s in results if s.get("company_id", 0) == company_id]
        if agent_key:
            results = [s for s in results if s["agent_key"] == agent_key]
        return results


# ── 单例 & 便捷访问 ────────────────────────────────────────────────────


_auto_writer: MemoryAutoWriter | None = None
_consolidation: SleepConsolidationEngine | None = None
_evolution_logger: EvolutionLogger | None = None
_feedback_evolution: FeedbackDrivenEvolution | None = None
_skill_optimizer: SkillOptimizationEngine | None = None
_lock = threading.Lock()

_agent_runtime = None


def _get_agent_runtime():
    global _agent_runtime
    if _agent_runtime is None:
        try:
            from app.runtime.orchestrator import AgentRuntime

            _agent_runtime = AgentRuntime()
        except Exception:
            pass
    return _agent_runtime


def get_memory_writer() -> MemoryAutoWriter:
    global _auto_writer
    if _auto_writer is None:
        with _lock:
            if _auto_writer is None:
                _auto_writer = MemoryAutoWriter()
    return _auto_writer


def get_consolidation_engine() -> SleepConsolidationEngine:
    global _consolidation
    if _consolidation is None:
        with _lock:
            if _consolidation is None:
                _consolidation = SleepConsolidationEngine()
    return _consolidation


def get_evolution_logger() -> EvolutionLogger:
    global _evolution_logger
    if _evolution_logger is None:
        with _lock:
            if _evolution_logger is None:
                _evolution_logger = EvolutionLogger()
    return _evolution_logger


def get_feedback_evolution() -> FeedbackDrivenEvolution:
    global _feedback_evolution
    if _feedback_evolution is None:
        with _lock:
            if _feedback_evolution is None:
                _feedback_evolution = FeedbackDrivenEvolution()
    return _feedback_evolution


def get_skill_optimizer() -> SkillOptimizationEngine:
    global _skill_optimizer
    if _skill_optimizer is None:
        with _lock:
            if _skill_optimizer is None:
                _skill_optimizer = SkillOptimizationEngine()
    return _skill_optimizer


def start_evolution_services():
    consolidation = get_consolidation_engine()
    consolidation.start_scheduler()
    logger.info("evolution_services_started")


def stop_evolution_services():
    consolidation = get_consolidation_engine()
    consolidation.stop_scheduler()
    logger.info("evolution_services_stopped")
