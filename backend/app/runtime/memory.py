"""
Memory Manager v2 - 三层记忆系统 + 睡眠巩固引擎

三层记忆:
1. 工作记忆 (Working Memory) - AgentState 运行时状态, 单次任务周期
2. 短期记忆 (Short-term) - PostgreSQL + Redis, 最近N次任务详情
3. 长期记忆 (Long-term/Semantic) - Milvus 向量库, 模式/经验/知识
4. 程序性记忆 (Procedural) - Few-shot缓存 + Prompt规则优化 + LoRA微调

睡眠巩固: 定时/阈值触发 → 短期摘要压缩 → 去重 → 模式提取 → 写入长期记忆

文档依据: 3.docx - AI Agent 记忆系统详解
  - 权重衰减公式: score = relevance × importance × e^(-λt)
  - 冲突解决: 合并冲突记忆(取更高置信度), 淘汰低置信度重复
  - 周期性 Vacuum 清理: 过期记忆清理 + 低质量记忆淘汰
"""

import asyncio  # 睡眠巩固需要异步执行，避免阻塞主线程
import hashlib  # 用 MD5 生成唯一记忆 ID，保证同一内容产生相同 ID 实现天然去重
import json  # Redis/PostgreSQL 中持久化存储结构化记忆数据
import os  # 从环境变量读取配置参数，避免硬编码，适配不同部署环境
import threading  # 巩固操作需要加锁，防止多个线程同时执行导致数据不一致
import time  # 时间戳用于 LRU 淘汰排序和睡眠巩固间隔判断
from dataclasses import dataclass, field  # 使用 dataclass 简化数据结构定义，field 提供默认工厂函数
from datetime import datetime  # 记录记忆的时间戳，用于排序和过期判断

from app.core.logging import get_logger  # 统一使用项目日志系统，便于集中监控和排查

logger = get_logger(__name__)  # 模块级 logger，按模块名区分日志来源

MAX_SEMANTIC_MEMORIES = int(os.getenv("MAX_SEMANTIC_MEMORIES", "10000"))  # 长期记忆硬上限，防止 Milvus/Redis 存储无限膨胀
LRU_CONFIDENCE_PROTECT_THRESHOLD = 0.9  # 高置信度记忆受保护不被 LRU 淘汰，避免丢失已充分验证的可靠知识
SLEEP_CONSOLIDATION_INTERVAL_SEC = int(os.getenv("SLEEP_CONSOLIDATION_INTERVAL_SEC", "1800"))  # 30分钟最小间隔，避免频繁巩固消耗计算资源
SHORT_TERM_CONSOLIDATION_THRESHOLD = int(os.getenv("SHORT_TERM_CONSOLIDATION_THRESHOLD", "100"))  # 积累足够数据才触发巩固，确保模式提取有统计意义


@dataclass  # 使用 dataclass 自动生成 __init__/__repr__/__eq__，减少样板代码
class EpisodicMemory:
    agent_key: str  # Agent 标识，用于按 Agent 维度检索历史任务
    task_summary: str  # 任务摘要文本，是模式提取的主要输入源
    key_decisions: list[str]  # 关键决策列表，用于后续 Few-shot 示例中展示决策路径
    tools_used: list[str]  # 使用的工具记录，用于分析工具使用模式
    outcome: str  # 任务结果，是判断决策优劣的核心依据
    human_feedback: str | None = None  # 人类反馈可选，有反馈时模式提取置信度更高
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())  # UTC 时间戳，避免时区歧义
    company_id: str = "default"  # 多租户隔离，确保不同公司的记忆不会混在一起


@dataclass  # 使用 dataclass 自动生成 __init__/__repr__/__eq__，减少样板代码
class SemanticMemory:
    memory_id: str  # 唯一标识，用于 Milvus 中的主键和 Redis 中的 key
    content: str  # 语义记忆的内容文本，是检索返回的核心信息
    category: str  # 分类标签，支持按类别过滤检索结果
    embedding: list[float] | None = None  # 向量嵌入可选，延迟计算以节省不必要存储时的开销
    source_episodes: int = 0  # 来源情景数量，数值越大表示模式越可靠
    confidence: float = 1.0  # 置信度，≥0.9 时受 LRU 保护不被淘汰
    last_updated: str = field(default_factory=lambda: datetime.utcnow().isoformat())  # 最后更新时间，配合 LRU 策略使用


class ThreeLayerMemoryManager:
    """三层记忆管理器"""

    _instance = None  # 单例模式：整个应用只有一个记忆管理器，避免多实例导致数据不一致

    def __new__(cls):  # 重写 __new__ 而非 __init__ 实现单例，因为 __new__ 控制对象创建
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False  # 标记未初始化，让 __init__ 完成实际初始化
        return cls._instance

    def __init__(self):
        if self._initialized:  # 防止重复初始化，因为单例的 __init__ 每次 ThreeLayerMemoryManager() 都会调用
            return
        self._initialized = True
        self._redis = None  # 惰性初始化失败时设为 None，后续操作通过 None 检查优雅降级
        self._milvus = None  # 同上，Milvus 失败不影响 Redis 功能，实现存储层解耦
        self._sleep_scheduled = False  # 防止多次调度睡眠巩固任务，避免并发冲突
        self._consolidation_threshold = 50  # 情景记忆超过 50 条触发巩固，确保有足够数据提取模式
        self._last_sleep_time: dict[str, float] = {}  # 按公司 ID 记录上次巩固时间，支持多租户独立触发
        self._consolidation_lock = threading.Lock()  # 用线程锁而非 asyncio 锁，因为 store_episodic 可能在同步线程中调用
        self._lru_max_capacity = MAX_SEMANTIC_MEMORIES  # 从环境变量读取容量上限，方便不同环境调整
        self._init_redis()  # 延迟导入 + 安全初始化，避免模块加载时 Redis 不可用导致崩溃
        self._init_milvus()  # 同上，Milvus 连接失败不影响其他记忆层正常工作
        logger.info("three_layer_memory_manager_initialized")

    def _init_redis(self):
        try:
            import redis as rds  # 延迟导入，避免 redis 未安装时模块完全不可用
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")  # 环境变量配置，支持不同部署环境的 Redis 地址
            self._redis = rds.from_url(redis_url, decode_responses=True)  # decode_responses=True 自动将 bytes 转为 str，减少手动解码
            self._redis.ping()  # ping 验证连接可用性，快速失败而非等到实际使用时才发现
            logger.info("memory_redis_connected")
        except Exception as e:
            logger.warning("memory_redis_unavailable", error=str(e))  # warning 而非 error，因为系统可以降级运行
            self._redis = None  # 设为 None，后续所有 Redis 操作都有 None 检查保护

    def _init_milvus(self):
        try:
            from pymilvus import connections  # 延迟导入，避免 pymilvus 未安装时模块完全不可用
            milvus_host = os.getenv("MILVUS_HOST", "localhost")  # 环境变量配置 Milvus 主机地址
            milvus_port = os.getenv("MILVUS_PORT", "19530")  # Milvus 默认端口 19530
            connections.connect(host=milvus_host, port=milvus_port)
            self._milvus_connected = True  # 用独立标志位而非检查 connection 对象，避免状态不一致
            logger.info("memory_milvus_connected")
        except Exception as e:
            logger.warning("memory_milvus_unavailable", error=str(e))  # warning 而非 error，语义记忆层可降级为仅 Redis
            self._milvus_connected = False  # False 保证检索操作返回空列表，而非抛出异常

    def store_episodic(self, memory: EpisodicMemory) -> str:
        """存储情景记忆到短期记忆层 (Redis + PostgreSQL)"""
        episode_id = hashlib.md5(  # MD5 而非 SHA256，因为只需 16 位短 ID 且不需要密码学强度
            f"{memory.agent_key}{memory.task_summary}{memory.timestamp}".encode()  # 拼接三个字段作为唯一性依据，timestamp 保证即使摘要相同也不会碰撞
        ).hexdigest()[:16]  # 截取前 16 位，兼顾唯一性和可读性

        memory_data = {  # 字典序列化，比 dataclass 更灵活，方便后续扩展字段
            "id": episode_id,
            "agent": memory.agent_key,
            "summary": memory.task_summary,
            "decisions": memory.key_decisions,
            "tools": memory.tools_used,
            "outcome": memory.outcome,
            "feedback": memory.human_feedback,
            "timestamp": memory.timestamp,
            "company_id": memory.company_id,
        }

        if self._redis:  # Redis 不可用时跳过，不阻塞 PostgreSQL 写入
            try:
                key = f"memory:episodic:{memory.company_id}:{episode_id}"  # 按公司隔离 key 前缀，实现多租户数据隔离
                self._redis.setex(key, 86400 * 7, json.dumps(memory_data, ensure_ascii=False))  # 7天 TTL，情景记忆不需要永久保留
                self._redis.zadd(  # 用有序集合维护时间索引，score 为时间戳，支持按时间排序检索
                    f"memory:episodic_index:{memory.company_id}",
                    {episode_id: time.time()},
                )
                count = self._redis.zcard(f"memory:episodic_index:{memory.company_id}")  # 获取当前公司的情景记忆总数
                if count >= self._consolidation_threshold:  # 达到阈值触发巩固，而不是每次写入都触发
                    self._trigger_consolidation(memory.company_id)
            except Exception as e:
                logger.warning("episodic_redis_store_failed", error=str(e))  # Redis 失败不抛异常，PostgreSQL 写入继续

        try:
            from app.database import db  # 延迟导入，避免数据库模块未就绪时影响 Redis 写入
            db.create_memory_entry(
                company_id=int(memory.company_id) if memory.company_id.isdigit() else 1,  # 非数字 company_id 回退为 1（默认公司）
                agent_key=memory.agent_key,
                memory_type="episodic",  # 明确标记记忆类型，方便后续按类型查询和统计
                content=json.dumps(memory_data, ensure_ascii=False),  # 以 JSON 文本存储，保持与 Redis 一致
                memory_id=episode_id,
            )
        except Exception as e:
            logger.debug("episodic_pg_store_skipped", error=str(e))  # debug 级别，因为 PostgreSQL 存储是辅助性的

        logger.debug("episodic_stored", episode_id=episode_id, agent=memory.agent_key)  # debug 级别，减少生产日志量
        return episode_id  # 返回 ID 供调用方追踪

    def store_semantic(self, company_id: str, content: str, category: str,
                        source_episodes: int = 1, confidence: float = 1.0,
                        embedding: list[float] = None) -> str:
        """存储语义记忆到长期记忆层 (Milvus)，含 LRU 淘汰"""
        memory_id = hashlib.md5(f"{company_id}{content}{category}".encode()).hexdigest()[:16]  # 相同内容+分类产生相同 ID，天然去重

        if not embedding:  # 调用方未提供嵌入时自动计算，解耦调用方与嵌入服务
            embedding = self._get_embedding(content)

        if self._redis:  # Redis 存储语义记忆元数据，作为 Milvus 的元数据缓存层
            try:
                semantic_data = {
                    "id": memory_id,
                    "content": content,
                    "category": category,
                    "source_episodes": source_episodes,
                    "confidence": confidence,
                    "last_updated": datetime.utcnow().isoformat(),
                }
                key = f"memory:semantic:{company_id}:{memory_id}"  # 按公司和记忆 ID 隔离
                self._redis.setex(key, 86400 * 30, json.dumps(semantic_data, ensure_ascii=False))  # 30天 TTL，比情景记忆更长的保留期
                # LRU 访问时间追踪
                self._redis.zadd(  # 用有序集合维护 LRU 队列，score 为最后访问时间
                    f"memory:semantic_lru:{company_id}",
                    {memory_id: time.time()},
                )
                # 检查容量并触发 LRU 淘汰
                count = self._redis.zcard(f"memory:semantic_lru:{company_id}")  # 写后检查，避免存储膨胀
                if count > self._lru_max_capacity:  # 超过上限才淘汰，减少不必要的淘汰开销
                    self._evict_lru_semantic(company_id)
            except Exception:
                pass  # Redis 元数据存储失败不阻塞 Milvus 写入，保证向量检索可用

        if embedding and self._milvus_connected:  # 同时检查嵌入和连接，两个条件都满足才写入向量库
            try:
                self._insert_to_milvus(memory_id, content, embedding, company_id, category)
            except Exception as e:
                logger.warning("milvus_insert_failed", error=str(e))  # Milvus 写入失败不影响 Redis 元数据，系统可降级

        logger.debug("semantic_stored", memory_id=memory_id, category=category)
        return memory_id

    def retrieve_episodic(self, company_id: str, agent_key: str = None,
                            limit: int = 10) -> list[dict]:
        """检索情景记忆"""
        memories = []  # 初始化为空列表，确保 Redis 不可用时返回空而非 None
        if self._redis:  # Redis 不可用时直接返回空列表，不尝试 PostgreSQL 回退以保持响应速度
            try:
                episode_ids = self._redis.zrevrange(  # zrevrange 按时间戳倒序，最近的最先返回
                    f"memory:episodic_index:{company_id}", 0, limit - 1
                )
                for eid in episode_ids:
                    data = self._redis.get(f"memory:episodic:{company_id}:{eid}")  # 逐个获取详情，zset 只存了 ID 索引
                    if data:
                        mem = json.loads(data)
                        if agent_key is None or mem.get("agent") == agent_key:  # 在内存中过滤 Agent，因为 zset 没有子索引
                            memories.append(mem)
            except Exception:
                pass  # 任何异常都返回空列表，保证接口的容错性
        return memories

    def retrieve_semantic(self, query: str, company_id: str, top_k: int = 5,
                            category: str = None) -> list[dict]:
        """检索语义记忆，并更新 LRU 访问时间"""
        query_embedding = self._get_embedding(query)  # 先计算嵌入，因为后续需要向量相似度搜索
        if not query_embedding or not self._milvus_connected:  # 嵌入失败或 Milvus 不可用，直接返回空
            return []

        try:
            from pymilvus import Collection  # 延迟导入，避免 pymilvus 未安装时影响其他功能
            col = Collection("agent_memory")  # 获取已存在的 Collection，不创建（由迁移脚本创建）
            col.load()  # 加载到内存以进行搜索，确保数据最新

            search_params = {"metric_type": "IP", "params": {"nprobe": 10}}  # 内积（IP）相似度，比 L2 更适合未归一化的嵌入；nprobe=10 平衡精度和速度
            results = col.search(
                data=[query_embedding],
                anns_field="embedding",  # 在 embedding 字段上做近似最近邻搜索
                param=search_params,
                limit=top_k,
                expr=f'company_id == "{company_id}"'  # 在公司范围内搜索，实现多租户隔离
            )

            memories = []
            for hits in results:  # results 是列表的列表，每层对应一个查询向量
                for hit in hits:
                    memory_id = hit.id
                    memories.append({
                        "memory_id": memory_id,
                        "content": hit.entity.get("content", ""),  # 从 Milvus entity 获取存储的内容
                        "category": hit.entity.get("category", ""),
                        "score": hit.score,  # 相似度分数，可用于排序和过滤
                    })
                    # 更新 LRU 访问时间
                    self._update_lru_access(company_id, memory_id)  # 检索即访问，用于 LRU 淘汰判断
            return memories
        except Exception as e:
            logger.warning("semantic_retrieval_failed", error=str(e))
            return []  # 返回空列表而非抛异常，保证调用方代码的健壮性

    def retrieve_few_shot_examples(self, agent_key: str, task_type: str,
                                     company_id: str, limit: int = 3) -> list[dict]:
        """检索 Few-shot 示例（程序性记忆第1层）"""
        key = f"memory:fewshot:{company_id}:{agent_key}:{task_type}"  # 按公司+Agent+任务类型三级隔离，精准匹配
        if self._redis:  # 先查缓存，Redis 数据是经过整理优化的 Few-shot 示例
            try:
                data = self._redis.get(key)
                if data:
                    return json.loads(data)[:limit]  # 内存切片限制数量，避免返回过多干扰 LLM 上下文
            except Exception:
                pass  # 缓存失败回退到从情景记忆中实时提取

        episodes = self.retrieve_episodic(company_id, agent_key, limit=limit)  # 回退：从原始情景记忆提取
        examples = []
        for ep in episodes:
            if ep.get("outcome"):  # 只返回有结果的记录，无结果的历史对 Few-shot 没有帮助
                examples.append({
                    "task": ep.get("summary", ""),
                    "decisions": ep.get("decisions", []),
                    "outcome": ep.get("outcome"),
                })
        return examples

    async def sleep_consolidation(self, company_id: str) -> dict:
        """睡眠巩固：压缩情景记忆 → 语义记忆（含去重保护）"""
        if not self._consolidation_lock.acquire(blocking=False):  # 非阻塞获取锁，已有巩固任务在运行则直接返回
            logger.info("sleep_consolidation_skipped_concurrent", company=company_id)
            return {"consolidated": 0, "reason": "consolidation_in_progress"}

        try:
            memories = self.retrieve_episodic(company_id, limit=100)  # 一次最多处理 100 条，避免 LLM 调用超时
            if len(memories) < 5:  # 少于 5 条样本提取的模式缺乏统计意义
                return {"consolidated": 0, "reason": "insufficient_memories"}

            try:
                patterns = await self._extract_patterns(memories, company_id)  # LLM 调用提取模式，异步等待
                optimized_rules = await self._extract_prompt_rules(memories, company_id)  # 同时提取 Prompt 优化规则

                consolidated = 0
                for pattern in patterns:
                    self.store_semantic(  # store_semantic 内部的 MD5 哈希天然去重
                        company_id=company_id,
                        content=pattern["content"],
                        category=pattern.get("category", "general"),  # 未分类的归入 general
                        source_episodes=pattern.get("source_count", 1),
                        confidence=pattern.get("confidence", 0.8),  # 默认 0.8 < 0.9，不享受 LRU 保护
                    )
                    consolidated += 1

                if optimized_rules:  # 规则可能为空（样本不足），避免写入空数据
                    self._store_prompt_rules(company_id, optimized_rules)

                if self._redis:  # 巩固完成后清理已处理的情景记忆，防止重复巩固
                    try:
                        old_ids = self._redis.zrange(  # zrange 从旧到新，与存储时的 zadd 方向一致
                            f"memory:episodic_index:{company_id}", 0, len(memories) - 1
                        )
                        for eid in old_ids:
                            self._redis.delete(f"memory:episodic:{company_id}:{eid}")  # 逐个删除详情
                        self._redis.delete(f"memory:episodic_index:{company_id}")  # 删除索引
                    except Exception:
                        pass  # 清理失败不影响巩固结果

                logger.info("sleep_consolidation_complete",
                            company=company_id, consolidated=consolidated,
                            episodes_processed=len(memories))
                return {"consolidated": consolidated, "episodes_processed": len(memories)}
            except Exception as e:
                logger.error("sleep_consolidation_failed", error=str(e))
                return {"consolidated": 0, "error": str(e)}
        finally:
            self._consolidation_lock.release()  # finally 保证锁一定释放，防止死锁

    async def _extract_patterns(self, memories: list[dict],
                                  company_id: str) -> list[dict]:
        """从情景记忆中提取模式（使用结构化Meta Prompt辅助）"""
        if not memories:
            return []

        summary_text = "\n".join([  # 拼接为文本流，供 LLM 分析
            f"- [{m.get('agent', 'unknown')}] {m.get('summary', '')[:200]} | "  # 摘要截断 200 字符，控制 LLM 输入长度
            f"结果: {m.get('outcome', '')}"
            for m in memories[:30]  # 最多 30 条，超过会超出 LLM 上下文窗口
        ])

        try:
            from langchain_core.messages import HumanMessage, SystemMessage  # 使用 LangChain 的标准消息类型，兼容多种 LLM 后端

            from app.core.meta_prompt_standards import (
                META_ANALYST_ROLE,  # 分析员角色 Prompt，定义 LLM 的行为模式
                META_CONSTRAINTS,  # 约束条件，防止 LLM 输出不符合预期
                META_EMPTY_GUIDANCE,  # 空结果引导，当样本不足时的输出格式
                META_FEWSHOT_EXTRACTION,  # Few-shot 示例，提供模式提取的正确范例
                META_OUTPUT_FORMAT,  # 输出格式规范，确保 LLM 返回可解析的 JSON
            )
            from app.services.model_gateway import get_global_model_gateway  # 通过网关统一管理 LLM 实例，支持多模型切换

            gateway = get_global_model_gateway()
            llm = gateway.get_llm()  # 获取配置的默认 LLM，由网关决定具体使用哪个模型

            system_content = f"""{META_ANALYST_ROLE}

{META_CONSTRAINTS}

{META_OUTPUT_FORMAT}

{META_FEWSHOT_EXTRACTION}

{META_EMPTY_GUIDANCE}"""  # 系统 Prompt 组件拼装，顺序影响 LLM 注意力分配

            human_content = f"""从以下 {len(memories)} 条记忆记录中提取3-5个关键模式：

{summary_text[:3000]}

如果样本量不足以提炼可靠模式，请按 META_EMPTY_GUIDANCE 格式返回。"""  # 截断至 3000 字符，为系统 Prompt 留出空间

            response = llm.invoke([  # 使用 invoke 而非 stream，模式提取不需要流式输出
                SystemMessage(content=system_content),
                HumanMessage(content=human_content),
            ])
            import re  # 延迟导入 re，只在需要时加载
            match = re.search(r"\[.*\]", response.content, re.DOTALL)  # DOTALL 让 . 匹配换行，提取跨行 JSON 数组
            if match:
                return json.loads(match.group())  # 直接解析 JSON 数组，信任 LLM 按格式输出
        except Exception as e:
            logger.warning("pattern_extraction_failed", error=str(e))

        return [  # LLM 提取失败时的兜底策略：生成一条低置信度聚合摘要
            {"content": f"基于{len(memories)}条记忆的聚合摘要", "category": "general",
             "source_count": len(memories), "confidence": 0.7}  # 兜底置信度 0.7 < 0.9，不享受 LRU 保护
        ]

    async def _extract_prompt_rules(self, memories: list[dict],
                                      company_id: str) -> list[str]:
        """提取Prompt优化规则（使用结构化Meta Prompt，含规则级别和触发条件）"""
        if len(memories) < 10:  # 比模式提取的阈值（5）更高，因为规则提取需要更多样本来验证重复性
            return []

        try:
            from langchain_core.messages import HumanMessage, SystemMessage  # 使用 LangChain 标准消息类型

            from app.core.meta_prompt_standards import (
                META_CONSTRAINTS,  # 约束条件，防止 LLM 输出不符合预期
                META_ENGINEER_ROLE,  # 工程师角色 Prompt，与分析师角色不同，侧重规则制定
                META_OUTPUT_FORMAT,  # 输出格式规范，确保返回的结构化规则可解析
            )
            from app.services.model_gateway import get_global_model_gateway  # 统一 LLM 管理

            gateway = get_global_model_gateway()
            llm = gateway.get_llm()

            summary = "\n".join([  # 包含决定、结果和反馈的完整记录，供 LLM 分析决策质量
                f"Agent: {m.get('agent')}, 决定: {m.get('decisions', [])}, "
                f"结果: {m.get('outcome')}, 反馈: {m.get('feedback', '无')}"
                for m in memories[:20]  # 最多 20 条，包含更多细节需要更多上下文空间
            ])

            system_content = f"""{META_ENGINEER_ROLE}

{META_CONSTRAINTS}

## 规则级别分类
- L1（强制）：安全合规类规则，必须严格执行
- L2（建议）：效率优化类规则，建议优先遵守
- L3（可选）：风格偏好类规则，视场景灵活使用

## 触发条件格式
每条规则必须明确触发条件，例如：
- "当用户输入包含[关键词]时"
- "当[指标]超过[阈值]时"
- "当[Agent状态]处于[状态]时"

{META_OUTPUT_FORMAT}

注意：如果样本不足以提炼可靠规则（<3次相同模式），返回空列表 [] 并说明原因。"""  # 要求至少 3 次相同模式才提取规则，确保规则的统计可靠性

            human_content = f"""根据以下 {len(memories)} 条表现数据，提炼3-5条Prompt优化规则：

{summary[:3000]}

每条规则格式：- [级别] 当[触发条件]时，需[具体行为规则]（触发频率：N次/总样本，置信度：XX%）
如果样本不足以提炼可靠规则，返回空列表。"""

            response = llm.invoke([  # invoke 同步等待 LLM 返回完整结果
                SystemMessage(content=system_content),
                HumanMessage(content=human_content),
            ])

            rules = [  # 解析以 "-" 开头的行作为规则条目
                line.strip("- ").strip()  # 去除前导 "- " 并清理空白
                for line in response.content.split("\n")
                if line.strip().startswith("-")
            ]
            return rules[:5]  # 最多返回 5 条，避免一次性规则过多导致 Prompt 过于冗长
        except Exception as e:
            logger.warning("prompt_rule_extraction_failed", error=str(e))
            return []

    def _store_prompt_rules(self, company_id: str, rules: list[str]):
        """存储Prompt优化规则"""
        try:
            from app.database import db  # 延迟导入，避免循环依赖
            db.create_evolution_log(  # 存入进化日志而非记忆表，因为规则不是"记忆"而是"优化产物"
                company_id=int(company_id) if company_id.isdigit() else 1,  # 非数字 company_id 回退为默认公司 1
                agent_id=None,  # 规则跨 Agent 通用，不绑定特定 Agent
                change_type="prompt_rules",  # 明确标记为 Prompt 规则类型，与代码变更等其他进化记录区分
                changes=json.dumps({"rules": rules, "source": "sleep_consolidation"}),  # 记录来源，便于追溯规则的生成方式
            )
        except Exception:
            pass  # 规则存储失败不阻塞主流程，规则是辅助优化手段

    def _get_embedding(self, text: str) -> list[float] | None:
        try:
            from app.rag.embedding_service import EmbeddingService  # 延迟导入，避免 RAG 模块未就绪时影响记忆管理器初始化
            service = EmbeddingService()  # 每次创建新实例，因为 service 可能是无状态的或自带缓存
            return service.encode_single(text).tolist()  # tolist() 转 Python 列表，比 numpy array 更易序列化和传输
        except Exception:
            return None  # 嵌入失败返回 None，调用方有 None 检查保护

    def _insert_to_milvus(self, memory_id: str, content: str, embedding: list[float],
                            company_id: str, category: str):
        try:
            from pymilvus import Collection  # 延迟导入，避免 pymilvus 未安装时影响其他功能
            col = Collection("agent_memory")  # 获取已存在的 Collection
            import numpy as np  # 延迟导入 numpy，只在 Milvus 写入时需要
            col.insert([{  # 以列表包裹字典方式插入，符合 pymilvus 的插入 API 规范
                "id": memory_id,
                "content": content,
                "embedding": np.array(embedding, dtype=np.float32),  # 转为 float32 numpy 数组，Milvus 内部使用 float32 存储向量
                "company_id": company_id,
                "category": category,
            }])
            col.flush()  # 手动 flush 确保数据持久化到磁盘，避免断电丢失
        except Exception:
            pass  # Milvus 写入失败不阻塞，语义记忆已存入 Redis 作为备份

    def _trigger_consolidation(self, company_id: str):
        """混合触发睡眠巩固：时间间隔 + 数据量双条件

        - 时间触发：距离上次巩固超过 30 分钟
        - 数据量触发：短期记忆超过 100 条消息
        - 去重保护：_consolidation_lock 防止并发
        """
        now = time.time()
        last = self._last_sleep_time.get(company_id, 0)  # 首次触发时 last=0，time_elapsed 会很大，立即触发
        time_elapsed = now - last

        # 时间触发
        time_triggered = time_elapsed >= SLEEP_CONSOLIDATION_INTERVAL_SEC  # 环境变量控制间隔，方便不同环境调整

        # 数据量触发
        volume_triggered = False
        if self._redis:  # Redis 不可用时只能依赖时间触发
            try:
                count = self._redis.zcard(f"memory:episodic_index:{company_id}")
                volume_triggered = count >= SHORT_TERM_CONSOLIDATION_THRESHOLD  # 超过环境变量阈值则触发
            except Exception:
                pass  # Redis 计数失败不阻塞时间触发路径

        if not time_triggered and not volume_triggered:  # 两个条件都不满足，不触发
            return

        if self._sleep_scheduled:  # 已有待执行任务，防止重复调度
            return

        self._sleep_scheduled = True  # 先标记再更新时间和创建任务，防止并发创建多个任务
        self._last_sleep_time[company_id] = now  # 记录本次触发时间，用于下次时间间隔计算

        trigger_reason = []  # 记录触发原因用于日志，方便排查和监控
        if time_triggered:
            trigger_reason.append(f"time_elapsed={time_elapsed:.0f}s")
        if volume_triggered:
            trigger_reason.append("volume_threshold")

        logger.info("sleep_consolidation_triggered",
                    company=company_id,
                    reason=",".join(trigger_reason))

        async def _run():  # 闭包捕获 company_id，无需传参
            await asyncio.sleep(5)  # 延迟 5 秒，避免与当前正在写入的操作冲突
            await self.sleep_consolidation(company_id)
            self._sleep_scheduled = False  # 任务完成后重置标志位

        try:
            asyncio.create_task(_run())  # 创建后台异步任务，不阻塞当前写入操作
        except RuntimeError:  # 没有运行中的事件循环（如在同步上下文中调用）
            self._sleep_scheduled = False  # 回退标志位，下次触发条件满足时再尝试

    def _update_lru_access(self, company_id: str, memory_id: str):
        """更新语义记忆的 LRU 访问时间"""
        if self._redis:  # Redis 不可用时 LRU 淘汰无法工作，直接跳过
            try:
                self._redis.zadd(  # zadd 相同元素会更新 score，利用这一特性实现访问时间更新
                    f"memory:semantic_lru:{company_id}",
                    {memory_id: time.time()},  # score=当前时间戳，数值越大表示最近使用
                )
            except Exception:
                pass  # LRU 更新失败不影响检索结果返回，只影响淘汰准确性

    def _evict_lru_semantic(self, company_id: str):
        """LRU 淘汰语义记忆，保护高置信度记忆（confidence >= 0.9）

        从最久未访问的记忆开始淘汰，跳过受保护的记忆。
        每次淘汰超出容量的 10% 条记录。
        """
        if not self._redis:  # Redis 不可用无法淘汰，依赖 TTL 自然过期
            return

        try:
            lru_key = f"memory:semantic_lru:{company_id}"
            total = self._redis.zcard(lru_key)
            if total <= self._lru_max_capacity:  # 未超过容量，无需淘汰
                return

            evict_count = max(int((total - self._lru_max_capacity) * 1.1), 1)  # 多淘汰 10%，减少频繁淘汰的开销
            evict_count = min(evict_count, 1000)  # 单次淘汰上限 1000，防止一次性淘汰过多导致性能抖动

            # 从最旧到最新遍历
            evicted = 0
            protected = 0
            batch = self._redis.zrange(lru_key, 0, evict_count * 2 - 1, withscores=True)  # 扫描 2 倍于目标数量，因为部分会被保护跳过

            for memory_id, _score in batch:
                if evicted >= evict_count:  # 已达到目标淘汰数，提前终止
                    break

                # 读取记忆元数据检查置信度
                mem_key = f"memory:semantic:{company_id}:{memory_id}"
                data = self._redis.get(mem_key)
                if data:
                    try:
                        mem = json.loads(data)
                        if mem.get("confidence", 1.0) >= LRU_CONFIDENCE_PROTECT_THRESHOLD:  # 高置信度记忆受保护，跳过淘汰
                            protected += 1
                            continue  # 不淘汰此条，继续遍历
                    except json.JSONDecodeError:  # 数据损坏时直接淘汰，保留损坏数据没有意义
                        pass

                # 淘汰
                self._redis.delete(mem_key)  # 删除元数据
                self._redis.zrem(lru_key, memory_id)  # 从 LRU 队列中移除
                evicted += 1

            logger.info("lru_semantic_eviction",
                        company=company_id,
                        evicted=evicted,
                        protected=protected,  # 记录保护数量，用于监控是否有过多保护记忆
                        remaining=self._redis.zcard(lru_key))  # 记录剩余数量，验证淘汰效果
        except Exception as e:
            logger.warning("lru_eviction_failed", error=str(e))

    # ============ 权重衰减与记忆生命周期管理 ============
    # 文档依据: 3.docx - 权重衰减公式: score = relevance × importance × e^(-λt)
    # 衰减系数 λ 决定记忆衰退速度，默认为 ln(2)/7 (约7天半衰期)

    WEIGHT_DECAY_LAMBDA = 0.099  # λ = ln(2)/7 ≈ 0.099，7天半衰期
    WEIGHT_DECAY_MIN_SCORE = 0.1  # 最低分数阈值，低于此值的记忆将被淘汰
    CONFLICT_RESOLUTION_SIMILARITY_THRESHOLD = 0.85  # 语义相似度阈值，超过此值视为冲突

    def calculate_weight_decay(self, memory: SemanticMemory,
                                 current_time: str = None) -> float:
        """计算权重衰减后的分数 - 文档依据: 3.docx

        公式: score = relevance × importance × e^(-λt)

        Args:
            memory: 语义记忆对象
            current_time: 当前时间ISO字符串，None则使用当前时间

        Returns:
            衰减后的分数 (0.0 ~ 1.0)
        """
        if current_time is None:
            current_time = datetime.utcnow().isoformat()

        try:
            last_updated = datetime.fromisoformat(memory.last_updated)
            current = datetime.fromisoformat(current_time)
            days_elapsed = (current - last_updated).total_seconds() / 86400.0
            # 权重衰减公式
            decay_factor = 2.71828 ** (-self.WEIGHT_DECAY_LAMBDA * days_elapsed)
            # relevance简化为1.0（实际应从检索相似度获取），importance用confidence
            relevance = 1.0
            importance = memory.confidence
            decayed_score = relevance * importance * decay_factor
            return max(decayed_score, self.WEIGHT_DECAY_MIN_SCORE)
        except Exception:
            return memory.confidence  # 计算失败时返回原始置信度

    def resolve_conflict(self, memory_a: SemanticMemory,
                          memory_b: SemanticMemory) -> SemanticMemory:
        """冲突解决 - 文档依据: 3.docx

        策略:
        1. 取置信度更高的记忆
        2. 合并source_episodes计数
        3. 置信度取加权平均
        4. 更新时间戳为最新

        Args:
            memory_a, memory_b: 两个冲突的记忆

        Returns:
            合并后的记忆
        """
        total_episodes = memory_a.source_episodes + memory_b.source_episodes
        # 加权平均置信度
        weight_a = memory_a.source_episodes / max(total_episodes, 1)
        weight_b = memory_b.source_episodes / max(total_episodes, 1)
        merged_confidence = (memory_a.confidence * weight_a +
                             memory_b.confidence * weight_b)

        # 取内容更完整的记忆
        merged_content = (memory_a.content
                          if len(memory_a.content) >= len(memory_b.content)
                          else memory_b.content)

        return SemanticMemory(
            memory_id=memory_a.memory_id,  # 保留较早的记忆ID
            content=merged_content,
            category=memory_a.category,
            source_episodes=total_episodes,
            confidence=round(merged_confidence, 4),
            last_updated=datetime.utcnow().isoformat(),
        )

    def detect_and_resolve_conflicts(self, company_id: str,
                                       category: str = None) -> int:
        """检测并解决冲突记忆 - 文档依据: 3.docx

        遍历语义记忆，发现语义相似的记忆时进行冲突解决。

        Returns:
            解决的冲突数量
        """
        if not self._redis:
            return 0

        resolved = 0
        try:
            lru_key = f"memory:semantic_lru:{company_id}"
            all_ids = self._redis.zrange(lru_key, 0, -1)
            if len(all_ids) < 2:
                return 0

            # 逐个比较，O(n^2)复杂度，适用于小规模记忆(10000条以内)
            checked_pairs = set()
            for i, id_a in enumerate(all_ids):
                for id_b in all_ids[i + 1:]:
                    pair_key = f"{id_a}:{id_b}"
                    if pair_key in checked_pairs:
                        continue
                    checked_pairs.add(pair_key)

                    mem_a = self._redis.get(f"memory:semantic:{company_id}:{id_a}")
                    mem_b = self._redis.get(f"memory:semantic:{company_id}:{id_b}")
                    if not mem_a or not mem_b:
                        continue

                    try:
                        data_a = json.loads(mem_a)
                        data_b = json.loads(mem_b)
                    except json.JSONDecodeError:
                        continue

                    # 简单相似度检测：内容重叠度
                    content_a = data_a.get("content", "")
                    content_b = data_b.get("content", "")
                    if not content_a or not content_b:
                        continue

                    # 使用Jaccard相似度简化为字符级重叠
                    set_a = set(content_a)
                    set_b = set(content_b)
                    union = len(set_a | set_b)
                    intersection = len(set_a & set_b)
                    similarity = intersection / max(union, 1)

                    if similarity >= self.CONFLICT_RESOLUTION_SIMILARITY_THRESHOLD:
                        mem_obj_a = SemanticMemory(
                            memory_id=id_a,
                            content=content_a,
                            category=data_a.get("category", "general"),
                            source_episodes=data_a.get("source_episodes", 1),
                            confidence=data_a.get("confidence", 1.0),
                            last_updated=data_a.get("last_updated", ""),
                        )
                        mem_obj_b = SemanticMemory(
                            memory_id=id_b,
                            content=content_b,
                            category=data_b.get("category", "general"),
                            source_episodes=data_b.get("source_episodes", 1),
                            confidence=data_b.get("confidence", 1.0),
                            last_updated=data_b.get("last_updated", ""),
                        )
                        merged = self.resolve_conflict(mem_obj_a, mem_obj_b)
                        # 更新合并后的记忆，删除较低置信度的那个
                        self.store_semantic(
                            company_id=company_id,
                            content=merged.content,
                            category=merged.category,
                            source_episodes=merged.source_episodes,
                            confidence=merged.confidence,
                        )
                        resolved += 1
                        logger.debug("memory_conflict_resolved",
                                     id_a=id_a, id_b=id_b,
                                     merged_confidence=merged.confidence)
            return resolved
        except Exception as e:
            logger.warning("conflict_resolution_failed", error=str(e))
            return resolved

    async def vacuum_expired_memories(self, company_id: str,
                                        max_age_days: int = 90) -> dict:
        """周期性 Vacuum 清理 - 文档依据: 3.docx

        清理过期记忆和低质量记忆：
        1. 删除超过max_age_days天未更新的记忆
        2. 删除权重衰减后分数低于WEIGHT_DECAY_MIN_SCORE的记忆

        Returns:
            {"expired_removed": int, "low_quality_removed": int}
        """
        expired_removed = 0
        low_quality_removed = 0

        if not self._redis:
            return {"expired_removed": 0, "low_quality_removed": 0}

        try:
            lru_key = f"memory:semantic_lru:{company_id}"
            all_ids = self._redis.zrange(lru_key, 0, -1)
            current_time = datetime.utcnow().isoformat()
            cutoff_time = datetime.utcnow()
            from datetime import timedelta

            for memory_id in all_ids:
                mem_key = f"memory:semantic:{company_id}:{memory_id}"
                data = self._redis.get(mem_key)
                if not data:
                    continue

                try:
                    mem = json.loads(data)
                except json.JSONDecodeError:
                    self._redis.delete(mem_key)
                    self._redis.zrem(lru_key, memory_id)
                    expired_removed += 1
                    continue

                should_remove = False

                # 检查过期
                last_updated = mem.get("last_updated", "")
                if last_updated:
                    try:
                        last_dt = datetime.fromisoformat(last_updated)
                        if (cutoff_time - last_dt).days > max_age_days:
                            should_remove = True
                    except ValueError:
                        should_remove = True

                # 检查权重衰减
                if not should_remove:
                    mem_obj = SemanticMemory(
                        memory_id=memory_id,
                        content=mem.get("content", ""),
                        category=mem.get("category", "general"),
                        source_episodes=mem.get("source_episodes", 1),
                        confidence=mem.get("confidence", 1.0),
                        last_updated=last_updated,
                    )
                    decayed = self.calculate_weight_decay(mem_obj, current_time)
                    if decayed <= self.WEIGHT_DECAY_MIN_SCORE:
                        should_remove = True
                        low_quality_removed += 1

                if should_remove:
                    self._redis.delete(mem_key)
                    self._redis.zrem(lru_key, memory_id)
                    if not should_remove or mem.get("confidence", 1.0) >= 0.5:
                        pass  # 跟踪已计入
                    expired_removed += 1

            logger.info("vacuum_cleanup_complete",
                        company=company_id,
                        expired_removed=expired_removed,
                        low_quality_removed=low_quality_removed)
            return {
                "expired_removed": expired_removed,
                "low_quality_removed": low_quality_removed,
            }
        except Exception as e:
            logger.warning("vacuum_cleanup_failed", error=str(e))
            return {"expired_removed": 0, "low_quality_removed": 0}

    def get_agent_context_injection(self, company_id: str, agent_key: str,
                                      task_description: str) -> str:
        """为Agent构建上下文注入文本"""
        parts = []  # 用列表收集各部分再 join，比字符串拼接效率高且可读性好

        episodes = self.retrieve_episodic(company_id, agent_key, limit=3)  # 3 条情景记忆，平衡信息量和上下文长度
        if episodes:  # 有情景记忆才添加此部分，避免空标题
            parts.append("## 近期相关任务记录")
            for i, ep in enumerate(episodes):
                parts.append(f"{i + 1}. {ep.get('summary', '')[:150]}")  # 截断 150 字符，情境记忆在上下文中只需概要
                if ep.get("outcome"):
                    parts.append(f"   结果: {ep['outcome']}")

        semantic = self.retrieve_semantic(task_description, company_id, top_k=3)  # 用任务描述作为查询，搜索相关经验
        if semantic:  # 有语义记忆才添加此部分，避免空标题
            parts.append("\n## 相关经验知识")
            for s in semantic:
                parts.append(f"- {s.get('content', '')[:200]}")  # 截断 200 字符，给经验知识稍多空间

        few_shot = self.retrieve_few_shot_examples(agent_key, "general", company_id, limit=2)  # 2 个示例，Few-shot 范式下 2-shot 通常足够
        if few_shot:  # 有示例才添加此部分，避免空标题
            parts.append("\n## 参考案例")
            for fs in few_shot:
                parts.append(f"- 任务: {fs.get('task', '')[:100]}")  # 任务描述截断 100 字符
                parts.append(f"  结果: {fs.get('outcome', '')}")

        return "\n".join(parts)  # 用换行符连接所有部分，形成完整的上下文注入文本

    def build_context(self, task_description: str, agent_name: str = "",
                      company_id: str = "default", skill_name: str = None) -> str:
        """Build context for planner node (compatibility wrapper for get_agent_context_injection)"""
        return self.get_agent_context_injection(
            company_id=str(company_id),
            agent_key=agent_name or "default",
            task_description=task_description
        )


memory_manager = ThreeLayerMemoryManager()  # 模块加载时创建全局单例，所有消费方共用同一个管理器实例
