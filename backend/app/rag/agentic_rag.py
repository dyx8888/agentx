"""# AgenticRAG 模块，智能编排多源检索策略，按 Agent 角色自动选择最优检索组合
AgenticRAG - 智能编排检索  # "Agentic" 意为由 Agent 自主决策，而非硬编码单一检索路径
根据任务类型自动选择合适的检索策略，融合多源数据  # 不同 Agent 角色关注的数据维度不同，一刀切检索会引入噪音
"""

import threading  # 用于保护缓存的并发读写、LRU move_to_end 和 popitem 操作，避免竞态导致链表损坏或重复创建实例
import time  # 用于缓存项 TTL 时间戳，过期后重建实例以拾取知识库更新
from collections import (
    OrderedDict,  # 用于实现 LRU 缓存：move_to_end 标记最近使用，popitem(last=False) 弹出最久未使用项
)
from enum import StrEnum  # 使用 StrEnum 而非普通 str，既保证类型安全又能在序列化时直接输出字符串值

from app.core.logging import get_logger  # 结构化日志，便于追踪不同 Agent 的检索路径和召回情况

logger = get_logger(__name__)  # 模块级 logger，所有实例共享同一日志通道


class RetrieveStrategy(StrEnum):  # 继承 StrEnum 使得 strategy 值可以直接用于 JSON 序列化和日志输出
    HYBRID = "hybrid"  # 混合检索：BM25 + 向量，适合大多数通用场景
    GRAPH = "graph"  # 知识图谱检索：关系推理，适合需要理解实体关联的场景
    EXPERIENCE = "experience"  # 经验记忆检索：历史任务总结，适合需要参考过往经验的场景
    FULL = "full"  # 全量注入：三层上下文全部加载，适合复杂决策场景但 token 消耗大


class AgenticRAG:  # 智能编排检索器，核心价值在于根据 Agent 角色自动选择策略组合
    """智能编排检索引擎"""  # 不是简单的"检索器"，而是"检索策略编排器"

    STRATEGY_MAP = {  # 类级别常量，每种 Agent 角色对应一组检索策略，设计原则：避免不必要的检索以减少噪音和延迟
        "品牌商务": [
            RetrieveStrategy.HYBRID,
            RetrieveStrategy.EXPERIENCE,
            RetrieveStrategy.GRAPH,
        ],  # 品牌商务需要了解竞品关系(GRAPH)和历史合作经验(EXPERIENCE)
        "内容运营": [
            RetrieveStrategy.HYBRID,
            RetrieveStrategy.GRAPH,
        ],  # 内容运营需要理解内容类型与平台的关系(GRAPH)，但不需要历史经验
        "数据分析": [
            RetrieveStrategy.HYBRID,
            RetrieveStrategy.GRAPH,
            RetrieveStrategy.EXPERIENCE,
        ],  # 数据分析需要全维度数据：指标关系(GRAPH) + 历史分析经验(EXPERIENCE)
        "客服专员": [
            RetrieveStrategy.HYBRID,
            RetrieveStrategy.EXPERIENCE,
        ],  # 客服需要历史案例经验(EXPERIENCE)，但不需要知识图谱
        "仓储物流": [RetrieveStrategy.HYBRID],  # 仓储物流只需知识库检索，场景单一不需要额外策略
        "视觉设计": [
            RetrieveStrategy.HYBRID,
            RetrieveStrategy.EXPERIENCE,
        ],  # 视觉设计需要参考历史设计经验(EXPERIENCE)，知识图谱关系不适用
        "供应链选品师": [
            RetrieveStrategy.HYBRID,
            RetrieveStrategy.GRAPH,
            RetrieveStrategy.EXPERIENCE,
        ],  # 选品师需要平台关系(GRAPH) + 历史选品经验(EXPERIENCE)
        "智能投流专员": [
            RetrieveStrategy.HYBRID,
            RetrieveStrategy.GRAPH,
            RetrieveStrategy.EXPERIENCE,
        ],  # 投流需要指标关系(GRAPH) + 历史投放经验(EXPERIENCE)
        "default": [
            RetrieveStrategy.HYBRID,
            RetrieveStrategy.EXPERIENCE,
        ],  # 默认策略保守选择：混合检索 + 经验，避免不必要的图谱查询
    }

    def __init__(
        self, company_id: str = "default"
    ):  # company_id 用于多租户隔离，不同公司有独立的检索索引
        self.company_id = company_id  # 存储公司 ID，后续所有检索操作都基于此 ID 做数据隔离

    def _get_bus(self):  # 懒加载 CompanyContextBus，三层上下文的统一入口
        from .company_context_bus import (
            get_company_context_bus,  # 延迟导入，bus 内部会加载公司资料和知识库
        )

        return get_company_context_bus(self.company_id)  # 按公司 ID 隔离，不同公司的上下文完全独立

    def _get_graph(self):  # 懒加载 GraphRAG，知识图谱是全局共享的，不按公司隔离
        from .graph_rag import get_graph_rag  # 延迟导入，知识图谱启动时初始化电商领域基础实体

        return get_graph_rag()  # 全局单例，因为电商领域的基础知识图谱对所有公司通用

    def get_strategies(
        self, agent_name: str
    ) -> list[RetrieveStrategy]:  # 根据 Agent 名称查询策略映射表
        return self.STRATEGY_MAP.get(
            agent_name, self.STRATEGY_MAP["default"]
        )  # 未匹配到特定 Agent 时回退到默认策略，保证系统不崩溃

    def retrieve(
        self,
        query: str,
        agent_name: str = None,  # 核心检索方法，agent_name 为 None 时使用默认策略
        top_k: int = 5,
        include_knowledge_graph: bool = True,  # include_knowledge_graph 允许调用方显式关闭图谱检索以节省 token
        _precomputed: dict = None,
    ) -> (
        str
    ):  # _precomputed: 调用方预检索结果 {"knowledge":[...],"experience":[...]},避免内部重复查询
        """智能检索并融合结果"""  # 返回的是拼接后的纯文本，可直接注入到 LLM prompt 中
        strategies = (
            self.get_strategies(agent_name) if agent_name else self.STRATEGY_MAP["default"]
        )  # agent_name 为空时回退默认策略，确保向后兼容

        parts = []  # 收集各策略的检索结果片段，最后用双换行拼接

        if RetrieveStrategy.HYBRID in strategies:  # 混合检索策略：从知识库(Layer2)中检索相关文档
            bus = self._get_bus()  # 获取上下文总线，HYBRID 策略实际走的是 Layer2 知识库检索
            # 复用调用方预检索结果(若有),避免 retrieve_structured 场景下重复查询 Milvus
            pre_knowledge = _precomputed.get("knowledge") if _precomputed else None
            layer2 = bus.get_layer2_context(
                query, top_k=top_k, results=pre_knowledge
            )  # Layer2 是公司知识库的 RAG 检索结果
            if layer2:  # 只有检索到结果才添加到 parts，避免空字符串污染上下文
                parts.append(layer2)

        if (
            RetrieveStrategy.EXPERIENCE in strategies
        ):  # 经验记忆策略：从历史任务记录(Layer3)中检索相关经验
            bus = self._get_bus()  # 复用 bus 实例，避免重复创建
            # 复用调用方预检索结果(若有),避免 retrieve_structured 场景下重复查询 Milvus
            pre_experience = _precomputed.get("experience") if _precomputed else None
            layer3 = bus.get_layer3_context(
                query, agent_name=agent_name, top_k=3, results=pre_experience
            )  # 经验检索固定 top_k=3，避免过多历史噪音干扰当前决策
            if layer3:  # 有经验才添加，无经验时静默跳过
                parts.append(layer3)

        if (
            RetrieveStrategy.GRAPH in strategies and include_knowledge_graph
        ):  # 图谱检索需要同时满足策略配置和调用方允许两个条件
            kg_rag = self._get_graph()  # 获取全局知识图谱实例
            kg_context = kg_rag.retrieve(
                query, depth=2
            )  # depth=2 表示最多探索两层关系，平衡覆盖度和噪音
            if kg_context:  # 图谱检索到匹配实体关系才添加，否则跳过
                parts.append(kg_context)

        if RetrieveStrategy.FULL in strategies:  # FULL 策略覆盖前面所有策略，重新获取完整三层上下文
            # 注意:当前 STRATEGY_MAP 中无任何角色启用 FULL 策略,此分支为保留扩展点。
            # 如需启用,在 STRATEGY_MAP 对应角色列表加入 RetrieveStrategy.FULL 即可。
            bus = self._get_bus()  # 重新获取 bus，FULL 策略需要完整的 Layer1+Layer2+Layer3
            full = bus.get_full_context(
                query, agent_name=agent_name
            )  # 全量上下文包含公司资料 + 知识库 + 经验
            if full:  # 如果有全量上下文，直接替换 parts 而非追加，因为 FULL 本身就包含了所有层
                parts = [full]  # 替换而非追加，避免信息重复

        return "\n\n".join(parts)  # 双换行分隔不同来源的上下文片段，便于 LLM 区分不同信息块

    def retrieve_structured(
        self,
        query: str,
        agent_name: str = None,  # 结构化检索返回 dict，适合需要分别处理各层结果的场景
        top_k: int = 5,
    ) -> dict:  # top_k 传递给底层检索器
        """结构化检索结果"""  # 与 retrieve() 不同，返回结构化的 dict 而非拼接文本
        bus = self._get_bus()  # 获取 bus 实例，用于获取公司资料和独立检索结果
        profile = bus.get_profile()  # 从 Layer1 获取公司基础资料（可能触发数据库查询）

        # 预检索知识库和经验一次,后续传入 retrieve 复用,避免 retrieve() 内部再次查询 Milvus
        knowledge_results = bus.search_knowledge(
            query, top_k=top_k
        )  # 知识库原始检索结果，可做二次处理
        experience_results = bus.search_experiences(
            query, agent_name=agent_name, top_k=3
        )  # 经验原始结果，可做溯源展示

        # 将预检索结果传入 retrieve,内部 get_layer2_context/get_layer3_context 直接复用,不再重复查询
        context_str = self.retrieve(
            query,
            agent_name=agent_name,
            top_k=top_k,
            _precomputed={"knowledge": knowledge_results, "experience": experience_results},
        )

        return {  # 返回结构化 dict，调用方可以按需取用各个字段
            "context": context_str,  # 拼接后的完整上下文文本
            "company_profile": profile.to_context_string()
            if profile
            else "",  # 公司资料独立字段，方便前端展示
            "knowledge_results": knowledge_results,  # 知识库原始检索结果，可做二次处理
            "experience_results": experience_results,  # 经验原始结果，可做溯源展示
        }


# ============ 缓存配置 ============
# 缓存上限：按 company_id 隔离，100 个公司覆盖绝大多数多租户场景；可按需调整
MAX_CACHE_SIZE = 100
# 缓存项 TTL（秒）：1 小时，过期后重新创建实例以拾取知识库/公司资料更新；
# 设太短会增加初始化开销，设太长会导致数据陈旧
CACHE_TTL_SECONDS = 3600

_agentic_rag_cache: "OrderedDict[str, tuple[float, AgenticRAG]]" = OrderedDict()
# 模块级 LRU 缓存，按 company_id 存储 (创建时间戳, AgenticRAG 实例)；
# OrderedDict 便于在超限时弹出头部（最久未使用）项实现 LRU 失效，避免长期运行内存泄漏
_rag_cache_lock = threading.Lock()
# 线程锁，保护缓存的并发读写、LRU move_to_end 和 popitem 操作，避免竞态导致链表损坏或重复创建实例


def get_agentic_rag(company_id: str = "default") -> AgenticRAG:
    """工厂函数，保证每个公司只有一个 AgenticRAG 实例（双检锁 + LRU + TTL）

    并发安全：双检锁避免并发时创建多个实例；
    内存安全：LRU 策略限制缓存上限，防止长期运行内存泄漏；
    数据新鲜度：TTL 过期后自动重建实例，拾取知识库更新。
    """
    # 快速路径：无锁读取（CPython GIL 保证 dict.get 原子性），命中且未过期直接返回
    entry = _agentic_rag_cache.get(company_id)
    if entry is not None:
        created_at, instance = entry
        if time.time() - created_at < CACHE_TTL_SECONDS:
            # 命中且未过期：在锁内做 move_to_end 标记为最近使用，保证 LRU 一致性
            with _rag_cache_lock:
                # 再次确认项仍在缓存中（可能被其他线程 LRU 淘汰或 clear）
                if company_id in _agentic_rag_cache:
                    _agentic_rag_cache.move_to_end(company_id)
            return instance
        # 已过期：落入下方加锁路径，移除旧项并重建

    with _rag_cache_lock:
        # 双检锁：再次检查，防止其他线程在等待锁期间已创建实例
        entry = _agentic_rag_cache.get(company_id)
        if entry is not None:
            created_at, instance = entry
            if time.time() - created_at < CACHE_TTL_SECONDS:
                _agentic_rag_cache.move_to_end(company_id)
                return instance
            else:
                # 过期：移除旧项，继续创建新实例
                _agentic_rag_cache.pop(company_id, None)
                logger.info("agentic_rag_cache_expired", company_id=company_id)

        # 缓存未命中或已过期：创建新实例并写入缓存末尾（最近使用位置）
        instance = AgenticRAG(company_id)
        _agentic_rag_cache[company_id] = (time.time(), instance)
        # LRU 失效：超过上限时弹出头部（最久未使用）项
        if len(_agentic_rag_cache) > MAX_CACHE_SIZE:
            evicted_key, _ = _agentic_rag_cache.popitem(last=False)  # last=False 弹出最旧项
            logger.info(
                "agentic_rag_cache_evicted",
                company_id=evicted_key,
                cache_size=len(_agentic_rag_cache),
            )
        return instance


def clear_agentic_rag_cache() -> int:
    """清空整个 AgenticRAG 缓存，返回被清除的项数量

    何时应调用：
    - 知识库更新后：强制下次访问重新初始化，拾取最新数据
    - 公司资料变更后：确保 Layer1 上下文刷新
    - 测试隔离：单元/集成测试间避免缓存串扰
    - 手动刷新：运维场景下需要强制重建实例
    """
    with _rag_cache_lock:
        cleared = len(_agentic_rag_cache)
        _agentic_rag_cache.clear()
    logger.info("agentic_rag_cache_cleared", cleared_count=cleared)
    return cleared
