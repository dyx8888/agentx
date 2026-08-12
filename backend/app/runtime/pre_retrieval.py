"""
PreRetrievalLayer - 预检索层

变更② T2.1：用户输入进入 master Agent 之前的前置层。
职责：在调用 LLM/Agent 之前先查缓存和记忆，决定是否能跳过 Agent 调用。

策略:
1. 结果缓存查询 (24h 完全相同问题) → 命中直接返回缓存结果，省 LLM 调用
2. 记忆回忆 (三层记忆系统) → 不直接返回，作为增强上下文
3. 相似问题查找 (7d 内向量相似 > 0.85) → 作为参考增强

文档依据: 02-主Agent编排重构.md 第 4.1 节
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.core.logging import get_logger

logger = get_logger(__name__)

# 缓存键截取长度：12 位 hex 足够避免碰撞，又便于日志和索引
CACHE_KEY_LENGTH = 12
# 结果缓存有效期：24 小时内完全相同问题直接返回
RESULT_CACHE_TTL_HOURS = 24
# 相似问题检索窗口：7 天内的相似问题作为参考增强
SIMILAR_RESULTS_WINDOW_DAYS = 7
# 向量相似度阈值：超过 0.85 视为相似问题
SIMILARITY_THRESHOLD = 0.85
# 相似问题最大返回数量：限制上下文膨胀
MAX_SIMILAR_ANSWERS = 3
# 记忆回忆最大返回数量
MAX_MEMORY_CONTEXT = 5


# 需要去除的标点字符集合（中英文）
# 用 set + 字符过滤代替正则字符类，避免 raw string 中无效转义序列的 SyntaxWarning
_PUNCTUATION_CHARS = set("，。！？；：、''（）()[]{}【】《》<>,.!?;:\"'`~@#$%^&*-_=+/\\|")


def _normalize_input(text: str) -> str:
    """归一化用户输入，提升缓存命中率。

    - 转小写
    - 去除首尾空白
    - 压缩连续空白为单个空格
    - 去除标点（中英文）避免 "现在几点？" 和 "现在几点" 命中不同缓存

    保留语义字符，仅去除对语义无影响的差异。
    """
    if not text:
        return ""
    # 转小写 + 压缩空白
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    # 去除常见中英文标点（保留字母数字和 CJK 字符）
    normalized = "".join(c for c in normalized if c not in _PUNCTUATION_CHARS)
    return normalized


def _build_cache_key(company_id: int, agent_name: str, normalized_input: str) -> str:
    """构建结果缓存键：sha256(company_id + agent_name + normalized_input) 前 12 位。

    agent_name 在 master 编排架构下统一为 "master"，
    但保留参数以便未来按 Agent 维度区分缓存。
    """
    raw = f"{company_id}:{agent_name or 'master'}:{normalized_input}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:CACHE_KEY_LENGTH]


@dataclass
class PreRetrievalResult:
    """预检索层输出。

    设计为 dataclass 而非 dict，便于类型检查和 IDE 自动补全。

    两种主要场景:
    - cache_hit=True 时 direct_return 非空 → 调用方直接返回，跳过 Agent
    - cache_hit=False 时 memory_context/similar_answers 作为增强上下文传给感知层
    """

    cache_hit: bool = False
    direct_return: str | None = None  # 24h 完全相同 → 直接返回的缓存内容
    memory_context: list[dict] = field(default_factory=list)  # 三层记忆片段
    similar_answers: list[dict] = field(default_factory=list)  # 7d 内相似问题参考
    cache_key: str | None = None  # 缓存键，用于后处理层写入缓存时复用

    @classmethod
    def direct_return_result(cls, output: str, cache_key: str) -> "PreRetrievalResult":
        """工厂方法：缓存命中，直接返回。"""
        return cls(
            cache_hit=True,
            direct_return=output,
            cache_key=cache_key,
        )

    @classmethod
    def enhance_result(
        cls,
        memory_context: list[dict],
        similar_answers: list[dict],
        cache_key: str,
    ) -> "PreRetrievalResult":
        """工厂方法：缓存未命中，返回增强上下文。"""
        return cls(
            cache_hit=False,
            direct_return=None,
            memory_context=memory_context,
            similar_answers=similar_answers,
            cache_key=cache_key,
        )


class PreRetrievalLayer:
    """预检索层。

    用户输入进来后先查缓存和记忆，决定是否跳过 Agent 调用。

    使用方式:
        layer = PreRetrievalLayer()
        result = await layer.retrieve(company_id=1, user_input="现在几点", thread_id="t_123")
        if result.cache_hit:
            return result.direct_return  # 跳过 Agent，直接返回缓存
        # 否则把 result.memory_context / result.similar_answers 喂给感知层
    """

    def __init__(self, memory_manager=None, embedding_service=None):
        """构造函数。

        Args:
            memory_manager: 三层记忆管理器实例，None 时延迟获取全局单例
            embedding_service: 嵌入服务实例，None 时延迟创建（相似问题检索才需要）

        延迟获取设计的原因：
        - 避免模块加载时强依赖 Redis/Milvus/SentenceTransformer
        - 允许测试时注入 mock
        """
        self._memory_manager = memory_manager
        self._embedding_service = embedding_service

    # ============ 主入口 ============

    async def retrieve(
        self,
        company_id: int,
        user_input: str,
        thread_id: str | None = None,
        agent_name: str = "master",
    ) -> PreRetrievalResult:
        """预检索主流程。

        Args:
            company_id: 公司 ID（多租户隔离）
            user_input: 用户原始输入
            thread_id: 会话 ID（用于工作记忆隔离，预留字段）
            agent_name: Agent 名称，master 架构下统一为 "master"

        Returns:
            PreRetrievalResult：cache_hit=True 时调用方应直接返回 direct_return
        """
        # 输入归一化：所有后续步骤都基于归一化后的文本
        normalized = _normalize_input(user_input)
        cache_key = _build_cache_key(company_id, agent_name, normalized)

        # Step A: 查结果缓存（24h 完全相同 → 直接返回）
        cached = await self._check_result_cache(company_id, cache_key)
        if cached is not None:
            logger.info(
                "pre_retrieval_cache_hit",
                company_id=company_id,
                cache_key=cache_key,
                thread_id=thread_id,
            )
            return PreRetrievalResult.direct_return_result(
                output=cached,
                cache_key=cache_key,
            )

        # Step B: 记忆回忆（不直接返回，作为增强上下文）
        memory_context = await self._recall_memories(
            company_id=company_id,
            user_input=user_input,
            thread_id=thread_id,
        )

        # Step C: 相似问题查找（7d 内相似 → 作为参考增强）
        similar_answers = await self._find_similar_results(
            company_id=company_id,
            normalized_input=normalized,
            user_input=user_input,
        )

        logger.info(
            "pre_retrieval_miss",
            company_id=company_id,
            cache_key=cache_key,
            memory_count=len(memory_context),
            similar_count=len(similar_answers),
        )

        return PreRetrievalResult.enhance_result(
            memory_context=memory_context,
            similar_answers=similar_answers,
            cache_key=cache_key,
        )

    # ============ Step A: 结果缓存查询 ============

    async def _check_result_cache(
        self,
        company_id: int,
        cache_key: str,
    ) -> str | None:
        """查 result_cache 表，命中且 < 24h 则返回缓存内容。

        缓存键设计：sha256(company_id + agent_name + normalized_input) 前 12 位
        存储位置：ResultCache.key_data 字段（JSON 格式），output_summary 存输出内容
        """
        try:
            from app.database.models import ResultCache
            from app.database.postgres_adapter import PostgresAdapter

            adapter = PostgresAdapter()
            with adapter.get_session() as session:
                # 按 company_id + key_data 查询，key_data 存 cache_key
                # 同一 company 内 cache_key 唯一（sha256 截断冲突概率极低）
                cutoff = datetime.utcnow() - timedelta(hours=RESULT_CACHE_TTL_HOURS)
                cache_entry = (
                    session.query(ResultCache)
                    .filter(
                        ResultCache.company_id == company_id,
                        ResultCache.key_data == cache_key,
                        ResultCache.created_at >= cutoff,
                    )
                    .order_by(ResultCache.created_at.desc())
                    .first()
                )
                if cache_entry is None:
                    return None
                # 命中且在有效期内，返回缓存的输出内容
                return cache_entry.output_summary
        except Exception as e:
            # 缓存查询失败不阻塞主流程，降级为缓存未命中
            logger.warning("pre_retrieval_cache_check_failed", error=str(e))
            return None

    # ============ Step B: 记忆回忆 ============

    async def _recall_memories(
        self,
        company_id: int,
        user_input: str,
        thread_id: str | None = None,
    ) -> list[dict]:
        """调三层记忆系统查询相关历史，作为增强上下文。

        - 工作记忆（当前会话）：通过 thread_id 隔离
        - 短期记忆（Redis 7d）：retrieve_episodic
        - 长期记忆（Milvus）：retrieve_semantic

        不直接返回结果，仅作为 Agent 的上下文增强。
        """
        memories: list[dict] = []
        company_id_str = str(company_id)

        manager = self._get_memory_manager()
        if manager is None:
            return memories

        # 短期记忆：最近相关情景
        try:
            episodes = manager.retrieve_episodic(
                company_id=company_id_str,
                limit=MAX_MEMORY_CONTEXT,
            )
            for ep in episodes:
                memories.append(
                    {
                        "type": "episodic",
                        "source": "short_term",
                        "content": ep.get("summary", ""),
                        "outcome": ep.get("outcome", ""),
                        "timestamp": ep.get("timestamp", ""),
                    }
                )
        except Exception as e:
            logger.warning("recall_episodic_failed", error=str(e))

        # 长期记忆：语义相似经验
        try:
            semantic = manager.retrieve_semantic(
                query=user_input,
                company_id=company_id_str,
                top_k=3,
            )
            for s in semantic:
                memories.append(
                    {
                        "type": "semantic",
                        "source": "long_term",
                        "content": s.get("content", ""),
                        "category": s.get("category", ""),
                        "score": s.get("score", 0.0),
                    }
                )
        except Exception as e:
            logger.warning("recall_semantic_failed", error=str(e))

        return memories[:MAX_MEMORY_CONTEXT]

    # ============ Step C: 相似问题查找 ============

    async def _find_similar_results(
        self,
        company_id: int,
        normalized_input: str,
        user_input: str,
    ) -> list[dict]:
        """对 normalized_input 做向量相似检索，找 7d 内相似问题作为参考。

        实现策略:
        1. 用 embedding_service 编码用户输入
        2. 拉取该公司 7d 内的 result_cache 条目
        3. 对每条 input_summary 编码并计算余弦相似度
        4. 相似度 > 0.85 的作为参考增强返回

        若嵌入服务不可用（如本地模型未加载），降级为关键词重叠匹配。
        """
        try:
            from app.database.models import ResultCache
            from app.database.postgres_adapter import PostgresAdapter

            adapter = PostgresAdapter()
            cutoff = datetime.utcnow() - timedelta(days=SIMILAR_RESULTS_WINDOW_DAYS)

            with adapter.get_session() as session:
                candidates = (
                    session.query(ResultCache)
                    .filter(
                        ResultCache.company_id == company_id,
                        ResultCache.created_at >= cutoff,
                    )
                    .order_by(ResultCache.created_at.desc())
                    .limit(50)  # 限制候选数量，避免大量嵌入计算
                    .all()
                )

                if not candidates:
                    return []

            # 尝试向量相似度检索
            similar = self._vector_similar_search(
                user_input=user_input,
                candidates=candidates,
            )

            # 向量检索失败 → 降级为关键词重叠
            if similar is None:
                similar = self._keyword_fallback_search(
                    normalized_input=normalized_input,
                    candidates=candidates,
                )

            return similar[:MAX_SIMILAR_ANSWERS]
        except Exception as e:
            logger.warning("find_similar_results_failed", error=str(e))
            return []

    def _vector_similar_search(
        self,
        user_input: str,
        candidates: list,
    ) -> list[dict] | None:
        """向量相似度检索。返回 None 表示嵌入服务不可用，需降级。"""
        embedding_service = self._get_embedding_service()
        if embedding_service is None:
            return None

        try:
            import numpy as np

            # 编码用户输入
            query_vec = embedding_service.encode_single(user_input)
            if query_vec is None or len(query_vec) == 0:
                return None
            query_vec = np.asarray(query_vec, dtype=np.float32)

            results: list[dict] = []
            for cand in candidates:
                # 跳过空 input_summary
                if not cand.input_summary:
                    continue
                cand_vec = embedding_service.encode_single(cand.input_summary)
                if cand_vec is None or len(cand_vec) == 0:
                    continue
                cand_vec = np.asarray(cand_vec, dtype=np.float32)

                # 余弦相似度（embedding_service 已归一化，点积即余弦）
                sim = float(np.dot(query_vec, cand_vec))
                if sim >= SIMILARITY_THRESHOLD:
                    results.append(
                        {
                            "input_summary": cand.input_summary,
                            "output_summary": cand.output_summary,
                            "similarity": sim,
                            "created_at": cand.created_at.isoformat() if cand.created_at else "",
                        }
                    )

            # 按相似度降序
            results.sort(key=lambda x: x["similarity"], reverse=True)
            return results
        except Exception as e:
            logger.warning("vector_similar_search_failed", error=str(e))
            return None

    def _keyword_fallback_search(
        self,
        normalized_input: str,
        candidates: list,
    ) -> list[dict]:
        """关键词重叠降级匹配（嵌入服务不可用时使用）。

        使用 Jaccard 字符级重叠度，与 memory.py 中冲突检测的简化策略一致。
        """
        if not normalized_input:
            return []
        query_chars = set(normalized_input)
        results: list[dict] = []
        for cand in candidates:
            if not cand.input_summary:
                continue
            cand_normalized = _normalize_input(cand.input_summary)
            if not cand_normalized:
                continue
            cand_chars = set(cand_normalized)
            union = len(query_chars | cand_chars)
            if union == 0:
                continue
            similarity = len(query_chars & cand_chars) / union
            if similarity >= SIMILARITY_THRESHOLD:
                results.append(
                    {
                        "input_summary": cand.input_summary,
                        "output_summary": cand.output_summary,
                        "similarity": similarity,
                        "created_at": cand.created_at.isoformat() if cand.created_at else "",
                    }
                )
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results

    # ============ 延迟依赖获取 ============

    def _get_memory_manager(self):
        """延迟获取三层记忆管理器单例。

        延迟获取原因：memory_manager 模块加载时需要连 Redis/Milvus，
        若在 PreRetrievalLayer 构造时获取，会在 import 时触发连接。
        """
        if self._memory_manager is not None:
            return self._memory_manager
        try:
            from app.runtime.memory import memory_manager

            self._memory_manager = memory_manager
            return self._memory_manager
        except Exception as e:
            logger.warning("memory_manager_unavailable", error=str(e))
            return None

    def _get_embedding_service(self):
        """延迟获取嵌入服务。

        延迟获取原因：EmbeddingService 首次实例化会加载本地 SentenceTransformer 模型，
        耗时约 2 秒。仅在相似问题检索时才需要。
        """
        if self._embedding_service is not None:
            return self._embedding_service
        try:
            from app.rag.embedding_service import EmbeddingService

            self._embedding_service = EmbeddingService()
            return self._embedding_service
        except Exception as e:
            logger.warning("embedding_service_unavailable", error=str(e))
            return None


__all__ = ["PreRetrievalLayer", "PreRetrievalResult"]
