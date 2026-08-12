"""
ContextPackage - 感知层增强后的综合上下文包

变更② T2.2：感知层最终输出，供 MasterAgentRouter 消费。

ContextPackage 汇总了感知管线所有阶段的结果：
- 改写后的查询 + 原始输入
- 意图类型 + 实体
- RAG 检索片段
- 记忆上下文 + 相似问题参考（来自预检索层）
- 匹配的技能清单
- 可用工具 + 可用子 Agent 清单
- 公司画像上下文

文档依据: 02-主Agent编排重构.md 第 4.2 节
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # 仅类型检查时导入，避免运行时循环依赖
    from app.skills.registry import SkillMeta


@dataclass
class ContextPackage:
    """感知层综合上下文包 — master Agent 路由决策的输入。

    设计为 dataclass 而非 dict：
    - 类型安全，IDE 自动补全
    - 字段默认值清晰，避免调用方传入不完整 dict
    - 可扩展（新增字段不破坏现有调用方）

    两种产出场景：
    1. 缓存命中 → cache_hit=True, direct_return 非空，其余字段为默认值
       调用方应直接返回 direct_return，跳过 MasterAgentRouter
    2. 缓存未命中 → cache_hit=False，所有字段填充完整
       调用方将其传给 MasterAgentRouter.execute()
    """

    # === 查询相关 ===
    rewritten_query: str = ""  # 改写后的查询，为空时调用方应用 raw_input
    raw_input: str = ""  # 原始用户输入，保留用于日志审计

    # === 意图相关 ===
    intent_type: str = "general"  # 意图类型字符串（IntentType.value）
    intent_entities: dict = field(default_factory=dict)  # 意图实体（product_name, date_range 等）

    # === 检索结果 ===
    rag_chunks: list[dict] = field(default_factory=list)  # RAG 检索片段

    # === 预检索层产出 ===
    memory_context: list[dict] = field(default_factory=list)  # 三层记忆片段（增强上下文）
    similar_answers: list[dict] = field(default_factory=list)  # 7d 内相似问题参考

    # === 技能与工具 ===
    matched_skills: list["SkillMeta"] = field(default_factory=list)  # 语义匹配的技能清单
    available_tools: list[str] = field(default_factory=list)  # 当前可用工具名清单
    available_agents: list[str] = field(default_factory=list)  # 当前可委派的子 Agent 名清单

    # === 上下文 ===
    company_id: str = ""  # 公司 ID，用于后续 LLM 成本归因、审计和多租户上下文传递
    company_context: dict = field(default_factory=dict)  # 公司画像上下文（品牌、品类、平台等）

    # === 缓存命中标记（预检索层直接返回时使用）===
    cache_hit: bool = False  # True 表示预检索缓存命中，调用方应直接返回 direct_return
    direct_return: str | None = None  # 缓存命中时的直接返回内容
    cache_key: str | None = None  # 缓存键，供后处理层写入缓存复用

    def to_dict(self) -> dict:
        """序列化为字典，用于日志和 SSE 事件。

        注意：matched_skills 中的 SkillMeta 是 dataclass，这里仅取关键字段避免序列化嵌套过深。
        """
        return {
            "rewritten_query": self.rewritten_query,
            "raw_input": self.raw_input,
            "intent_type": self.intent_type,
            "intent_entities": self.intent_entities,
            "rag_chunks_count": len(self.rag_chunks),
            "memory_context_count": len(self.memory_context),
            "similar_answers_count": len(self.similar_answers),
            "matched_skills": [s.name for s in self.matched_skills],
            "available_tools": self.available_tools,
            "available_agents": self.available_agents,
            "company_id": self.company_id,
            "cache_hit": self.cache_hit,
            "cache_key": self.cache_key,
        }


__all__ = ["ContextPackage"]
