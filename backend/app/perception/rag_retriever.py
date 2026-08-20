"""
感知管道 - RAG 检索器
根据意图从知识库中检索相关内容，委托给 AgenticRAG 引擎
"""
# 委托设计将 RAG 实现细节封装在 agentic_rag 模块中，感知管线只关心"检索到上下文"这个结果

import os
import re
import socket
from dataclasses import dataclass, field  # dataclass 承载多字段检索结果

from app.core.logging import get_logger

logger = get_logger(__name__)

REFERENCE_CONTENT_MAX_CHARS = 200
EVIDENCE_CONTENT_MAX_CHARS = 800
FACT_MARKER_LINE_RE = re.compile(r"\b(?:fact_id|marker)\s*=", re.IGNORECASE)
EVIDENCE_CONTEXT_HEADER_RE = re.compile(
    r"^\s*(?:#|标题|段落|section|title|document|文件|文档)\b",
    re.IGNORECASE,
)


@dataclass
class RagResult:  # 独立的 dataclass 而非嵌套在 Retriever 中，便于其他模块直接引用类型
    """RAG 检索结果"""

    context: str = ""  # 拼接后的上下文字符串，直接注入给 LLM
    references: list[dict] = field(default_factory=list)  # 引用列表用于前端展示来源
    evidence_chunks: list[dict] = field(
        default_factory=list
    )  # 给模型 prompt 使用的较完整证据片段
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
    def _build_reference(result: dict) -> dict:
        """Build compact reference for UI sources and persistence."""
        return {
            "source_file": result.get("source_file", ""),
            "source_page": result.get("source_page", 0),
            "score": result.get("score", 0),
            "content": (result.get("content", "") or "")[:REFERENCE_CONTENT_MAX_CHARS],
        }

    @staticmethod
    def _joined_line_length(lines_by_index: dict[int, str]) -> int:
        if not lines_by_index:
            return 0
        ordered = [lines_by_index[idx] for idx in sorted(lines_by_index)]
        return len("\n".join(ordered))

    @staticmethod
    def _add_evidence_line(
        selected: dict[int, str],
        index: int,
        line: str,
        max_chars: int,
    ) -> bool:
        cleaned = line.strip()
        if not cleaned or index in selected:
            return False
        trial = dict(selected)
        trial[index] = cleaned
        if RagRetriever._joined_line_length(trial) <= max_chars:
            selected[index] = cleaned
            return True
        return False

    @staticmethod
    def _format_evidence_content(
        content: str,
        max_chars: int = EVIDENCE_CONTENT_MAX_CHARS,
    ) -> str:
        """Preserve fact/marker lines for model evidence while keeping a size cap."""
        text = str(content or "")
        if len(text) <= max_chars:
            return text

        lines = text.splitlines()
        fact_line_indexes = [
            idx for idx, line in enumerate(lines) if FACT_MARKER_LINE_RE.search(line or "")
        ]
        if not fact_line_indexes:
            return text[:max_chars]

        selected: dict[int, str] = {}
        for idx in fact_line_indexes:
            line = lines[idx].strip()
            if len(line) > max_chars:
                line = line[: max(0, max_chars - 3)] + "..."
            RagRetriever._add_evidence_line(selected, idx, line, max_chars)

        if not selected:
            return text[:max_chars]

        header_candidates: list[int] = []
        first_fact_idx = min(fact_line_indexes)
        for idx, line in enumerate(lines[:first_fact_idx]):
            stripped = line.strip()
            if not stripped:
                continue
            if idx < 3 or EVIDENCE_CONTEXT_HEADER_RE.search(stripped):
                header_candidates.append(idx)

        context_candidates: list[int] = []
        for idx in sorted(selected):
            context_candidates.extend([idx - 1, idx + 1])

        for idx in [*header_candidates, *context_candidates]:
            if 0 <= idx < len(lines):
                RagRetriever._add_evidence_line(selected, idx, lines[idx], max_chars)

        return "\n".join(selected[idx] for idx in sorted(selected))

    @staticmethod
    def _build_evidence_chunk(result: dict) -> dict:
        """Build richer evidence for model prompts without sending it to the UI."""
        return {
            "source_file": result.get("source_file", ""),
            "source_page": result.get("source_page", 0),
            "score": result.get("score", 0),
            "source": result.get("source", ""),
            "chunk_index": result.get("chunk_index", 0),
            "metadata": result.get("metadata", {}),
            "content": RagRetriever._format_evidence_content(result.get("content", "") or ""),
        }

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

            knowledge_results = structured.get("knowledge_results", []) or []
            refs = [
                self._build_reference(r) for r in knowledge_results
            ]  # 短引用仅用于前端展示和持久化
            evidence_chunks = [
                self._build_evidence_chunk(r) for r in knowledge_results
            ]  # 较完整证据用于模型 prompt

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
                evidence_chunks=evidence_chunks,
                knowledge_results=knowledge_results,  # 保留原始数据方便下游做更多处理
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
