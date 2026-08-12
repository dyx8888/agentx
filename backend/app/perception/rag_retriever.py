"""
感知管道 - RAG 检索器
根据意图从知识库中检索相关内容，委托给 AgenticRAG 引擎
"""
# 委托设计将 RAG 实现细节封装在 agentic_rag 模块中，感知管线只关心"检索到上下文"这个结果

import os
import socket
from dataclasses import dataclass, field  # dataclass 承载多字段检索结果

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RagResult:  # 独立的 dataclass 而非嵌套在 Retriever 中，便于其他模块直接引用类型
    """RAG 检索结果"""

    context: str = ""  # 拼接后的上下文字符串，直接注入给 LLM
    references: list[dict] = field(default_factory=list)  # 引用列表用于前端展示来源
    knowledge_results: list[dict] = field(
        default_factory=list
    )  # 原始知识库结果，保留用于后续精确引用
    experience_results: list[dict] = field(
        default_factory=list
    )  # 经验库结果，与小知识分离存储便于不同展示策略
    query: str = ""  # 保留原始查询，方便下游追踪
    intent_type: str = ""  # 意图类型，下游可据此决定如何使用检索结果


class RagRetriever:
    """RAG 检索器 - 委托给 knowledge_retrieval_server / AgenticRAG"""

    def __init__(self):
        self._available = True

    @staticmethod
    def _external_backend_available() -> bool:
        if os.getenv("VECTOR_DB", "milvus").lower() != "milvus":
            return True

        host = os.getenv("MILVUS_HOST", "localhost")
        port = int(os.getenv("MILVUS_PORT", "19530"))
        timeout = float(os.getenv("RAG_PREFLIGHT_TIMEOUT_SECONDS", "0.2"))
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def retrieve(
        self,
        query: str,
        company_id: str = "",
        agent_name: str = "",
        intent_type: str = "general",
        top_k: int = 5,
    ) -> RagResult:
        """
        根据意图从知识库检索相关内容

        Args:
            query: 查询文本
            company_id: 公司 ID
            agent_name: Agent 名称
            intent_type: 意图类型
            top_k: 返回结果数量

        Returns:
            RagResult 包含检索上下文和引用
        """
        if not query or not company_id:  # 两个必要条件缺一则检索无意义，直接返回空结果
            return RagResult(query=query, intent_type=intent_type)
        if not self._available:
            logger.warning("rag_retriever_unavailable", agent=agent_name, company_id=company_id)
            return RagResult(query=query, intent_type=intent_type)
        if not self._external_backend_available():
            self._available = False
            logger.warning("rag_backend_unreachable", agent=agent_name, company_id=company_id)
            return RagResult(query=query, intent_type=intent_type)

        try:
            from app.rag.agentic_rag import get_agentic_rag  # noqa: I001  # 延迟导入，RAG 初始化开销大且可能有循环依赖

            rag = get_agentic_rag(company_id)  # 按公司 ID 获取专属 RAG 实例，实现租户数据隔离
            rag_context = rag.retrieve(
                query=query, agent_name=agent_name, top_k=top_k
            )  # 获取拼接好的上下文文本

            structured = rag.retrieve_structured(
                query=query, agent_name=agent_name, top_k=top_k
            )  # 结构化结果用于生成引用

            refs = [  # 构建引用列表，每个引用截取前 200 字符避免过大
                {
                    "source_file": r.get("source_file", ""),  # 文件来源用于展示和追溯
                    "source_page": r.get("source_page", 0),  # 页码帮助用户定位原文
                    "score": r.get("score", 0),  # 相似度分数，可用于前端展示置信度
                    "content": (r.get("content", "") or "")[:200],  # 截断内容防止引用数据膨胀
                }
                for r in structured.get(
                    "knowledge_results", []
                )  # 只从知识结果中提取引用，经验结果通常不展示来源
            ]

            logger.info(
                "rag_retrieved",
                agent=agent_name,
                company_id=company_id,
                context_length=len(rag_context),
                reference_count=len(refs),
                intent_type=intent_type,
            )

            return RagResult(
                context=rag_context,
                references=refs,
                knowledge_results=structured.get(
                    "knowledge_results", []
                ),  # 保留原始数据方便下游做更多处理
                experience_results=structured.get("experience_results", []),
                query=query,
                intent_type=intent_type,
            )
        except Exception as e:
            self._available = False
            logger.warning(
                "rag_retrieve_failed", error=str(e), agent=agent_name, company_id=company_id
            )  # 包含上下文信息便于排查
            return RagResult(query=query, intent_type=intent_type)  # 降级返回空结果，不阻断管线

    def augment_message(
        self, message: str, rag_result: RagResult
    ) -> str:  # 独立方法便于单独测试注入逻辑
        """将 RAG 检索上下文注入到用户消息中"""
        if not rag_result.context:  # 无上下文时直接返回原文，避免注入空的 --- 分隔符
            return message
        return rag_result.context + "\n\n---\n\n" + message  # --- 分隔符让 LLM 区分上下文和用户查询
