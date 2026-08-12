"""
Knowledge Retrieval MCP Server
Provides RAG-based knowledge retrieval for brand script templates.
Now delegates to CompanyContextBus + HybridRetriever (Milvus) as the unified backend.
"""

from fastmcp import FastMCP

from app.core.logging import get_logger
from app.tools.result import ERROR_SUGGESTIONS, ErrorCode, ToolResult

logger = get_logger(__name__)

mcp = FastMCP("knowledge_retrieval_server")


def _resolve_company_id(fallback: str = "default") -> str:
    """从 MCP 请求上下文中读取 company_id（优先），fallback 到参数值"""
    try:
        from fastmcp.server.context import get_request_context

        ctx = get_request_context()
        if ctx and hasattr(ctx, "meta") and ctx.meta:
            return ctx.meta.get("company_id", fallback)
    except Exception:
        pass
    return fallback


def _get_bus_for_company(company_id: str = "default"):
    from app.rag.company_context_bus import get_company_context_bus

    return get_company_context_bus(company_id)


@mcp.tool()
def search_knowledge(query: str, n_results: int = 3, company_id: str = "default") -> str:
    """
    Search for relevant knowledge from the brand script database.
    Uses unified HybridRetriever (Milvus + BM25) backend.

    Args:
        query: Search query for finding relevant scripts
        n_results: Number of results to return (default: 3)
        company_id: Company identifier for multi-tenant isolation (default: 'default')

    Returns:
        JSON string of ToolResult containing list of relevant script templates with metadata
    """
    try:
        # Phase 1: 优先从请求上下文读取 company_id，参数作为 fallback
        resolved_id = _resolve_company_id(company_id)
        bus = _get_bus_for_company(resolved_id)
        results = bus.search_knowledge(query, top_k=n_results)

        formatted = []
        for r in results:
            formatted.append(
                {
                    "content": r.get("content", ""),
                    "metadata": r.get("metadata", {}),
                    "distance": 1.0 - r.get("score", 0),
                    "score": r.get("score"),
                    "source": r.get("source"),
                    "bm25_score": r.get("bm25_score"),
                    "vector_score": r.get("vector_score"),
                    "rrf_score": r.get("rrf_score"),
                    "rerank_score": r.get("rerank_score"),
                    "source_file": r.get("source_file", ""),
                    "chunk_index": r.get("chunk_index", 0),
                    "source_page": r.get("source_page", 0),
                }
            )
        return ToolResult.ok(
            data=formatted, message=f"Found {len(formatted)} knowledge results for query."
        ).to_json()
    except Exception as e:
        logger.error("knowledge_query_error", error=str(e))
        return ToolResult.error(
            error_code=ErrorCode.CONNECTION_ERROR,
            message=f"知识检索失败：{str(e)}",
            suggestion="Milvus 服务可能不可用，请稍后重试或使用备用数据源。",
        ).to_json()


@mcp.tool()
def add_knowledge(text: str, metadata: dict, company_id: str = "default") -> str:
    """
    Add new knowledge to the brand script database.
    Uses unified HybridRetriever (Milvus + BM25) backend.

    Args:
        text: The script template content to add
        metadata: Dictionary containing category, scenario, and other metadata
        company_id: Company identifier for multi-tenant storage (default: 'default')

    Returns:
        JSON string of ToolResult with success message and document ID
    """
    try:
        # Phase 1: 优先从请求上下文读取 company_id，参数作为 fallback
        resolved_id = _resolve_company_id(company_id)
        bus = _get_bus_for_company(resolved_id)
        doc_id = bus.add_knowledge(
            content=text,
            metadata=metadata,
        )
        return ToolResult.ok(
            data={"doc_id": doc_id}, message=f"Successfully added knowledge with ID: {doc_id}"
        ).to_json()
    except Exception as e:
        return ToolResult.error(
            error_code=ErrorCode.UNKNOWN_ERROR,
            message=f"Error adding knowledge: {str(e)}",
            suggestion=ERROR_SUGGESTIONS[ErrorCode.UNKNOWN_ERROR],
        ).to_json()


if __name__ == "__main__":
    from app.mcp_servers.runtime import run_mcp_stdio

    run_mcp_stdio(mcp)
