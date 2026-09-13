"""
KOL Search MCP Server
Provides search functionality for Key Opinion Leaders (KOLs) in Chinese e-commerce market.
"""

import inspect
import os
import sys

# Add the project root to Python path for standalone execution
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastmcp import FastMCP
from pydantic import BaseModel

from app.core.logging import get_logger
from app.mcp_servers.mock_data import MOCK_KOLS
from app.mcp_servers.mock_policy import mock_fallback_blocked_result, mock_fallback_enabled
from app.tools.result import ERROR_SUGGESTIONS, ErrorCode, ToolResult

logger = get_logger(__name__)

# Create MCP server
mcp = FastMCP("kol_search_server")


class SearchKolsRequest(BaseModel):
    category: str
    count: int = 3
    company_id: int | None = None


async def search_kols_http_endpoint(request: SearchKolsRequest):
    """HTTP wrapper for the MCP tool that preserves tenant context."""
    return await search_kols(request.category, request.count, company_id=request.company_id)


def _resolve_company_id(fallback: str = "default") -> str:
    """从 MCP 请求上下文中读取 company_id（优先），fallback 到参数值"""
    try:
        from fastmcp.server.context import get_request_context

        ctx = get_request_context()
        if ctx and hasattr(ctx, "meta") and ctx.meta:
            return str(ctx.meta.get("company_id", fallback))
    except Exception:
        pass
    return str(fallback)


@mcp.tool()
async def search_kols(category: str, count: int = 3, company_id: int = None) -> str:
    """
    Search for KOLs (Key Opinion Leaders) in a specific category.

    Args:
        category (str): The category to search for KOLs (e.g., "美妆", "时尚", "美食")
        count (int): Number of KOLs to return (default: 3)
        company_id (int): Company ID for using company-specific credentials (optional,
            overridden by protocol-level X-Company-Id header if available)

    Returns:
        JSON string of ToolResult containing list of KOL information
    """
    try:
        # Phase 1: 优先从请求上下文读取 company_id，参数作为 fallback
        resolved_company_id = _resolve_company_id(str(company_id) if company_id else "default")
        category_normalized = category.lower().strip()

        from app.platforms import get_platform_adapter

        platform_adapter = get_platform_adapter("douyin_star", resolved_company_id)
        if platform_adapter and platform_adapter.is_available():
            try:
                result = platform_adapter.search_creators(category_normalized, count)
                creators = await result if inspect.isawaitable(result) else result
                if creators:
                    logger.info("kol_creators_retrieved", count=len(creators))
                    return ToolResult.ok(
                        data=creators, message=f"Found {len(creators)} KOLs from platform API."
                    ).to_json()
            except Exception as e:
                logger.error("kol_platform_error", error=str(e))

        if not mock_fallback_enabled():
            logger.warning("kol_mock_fallback_blocked", category=category_normalized)
            return mock_fallback_blocked_result("KOL search")

        logger.warning("kol_mock_fallback", category=category_normalized)
        # Fallback to mock data
        category_mapping = {
            "beauty": "beauty",
            "fashion": "fashion",
            "tech": "tech",
            "food": "food",
        }
        english_category = category_mapping.get(category_normalized, category_normalized)
        kols = MOCK_KOLS.get(english_category, [])
        if not kols:
            return ToolResult.error(
                error_code=ErrorCode.INVALID_PARAMS,
                message=f"未找到类别 '{category}' 的达人数据。",
                suggestion=f"请尝试以下类别: {', '.join(category_mapping.keys())}",
            ).to_json()
        actual_count = min(count, 5, len(kols))
        result = kols[:actual_count]
        return ToolResult.ok(
            data=result, message=f"Found {len(result)} KOLs in category '{category}' (mock data)."
        ).to_json()
    except Exception as e:
        return ToolResult.error(
            error_code=ErrorCode.UNKNOWN_ERROR,
            message=f"搜索达人时出错：{str(e)}",
            suggestion=ERROR_SUGGESTIONS[ErrorCode.UNKNOWN_ERROR],
        ).to_json()


if __name__ == "__main__":
    import os

    # Check if we should run as HTTP service
    if os.getenv("RUN_AS_HTTP_SERVICE", "false").lower() == "true":
        # Run as independent FastAPI service
        import uvicorn
        from fastapi import FastAPI

        app = FastAPI(title="KOL Search Service")

        @app.get("/")
        async def root():
            return {"service": "KOL Search", "version": "1.0.0"}

        @app.get("/health")
        async def health_check():
            return {"status": "healthy", "service": "kol_search"}

        @app.post("/tools/search_kols")
        async def search_kols_endpoint(request: SearchKolsRequest):
            return await search_kols_http_endpoint(request)

        port = int(os.getenv("PORT", "8101"))
        logger.info("kol_server_starting", port=port)
        uvicorn.run(app, host="0.0.0.0", port=port)
    else:
        # Run the MCP server
        from app.mcp_servers.runtime import run_mcp_stdio

        run_mcp_stdio(mcp)
