"""
Platform Tools MCP Server (T4.3)
将平台适配器的能力方法封装为 MCP 工具。

每个平台每个能力注册为一个独立的 @mcp.tool() 函数：
  函数名格式: {platform_code}_{capability_name}
  如 douyin_star_search_creators, taobao_get_shop_data

所有调用经 T3.2 熔断器保护，返回统一 ToolResult。
"""

import json
import os
import sys

# 保证 standalone 执行时项目根目录在 path 中
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastmcp import FastMCP

from app.core.circuit_breaker import CircuitBreakerOpenError, get_circuit_breaker
from app.core.logging import get_logger
from app.platforms import PLATFORM_ADAPTERS, get_platform_adapter
from app.tools.result import ErrorCode, ToolResult

logger = get_logger(__name__)

mcp = FastMCP("platform_tools")


# ── 辅助函数 ────────────────────────────────────────────────────


def _resolve_company_id(fallback: str = "default") -> str:
    """从 MCP 请求上下文中读取 company_id，fallback 到参数值"""
    try:
        from fastmcp.server.context import get_request_context

        ctx = get_request_context()
        if ctx and hasattr(ctx, "meta") and ctx.meta:
            return str(ctx.meta.get("company_id", fallback))
    except Exception:
        pass
    return str(fallback)


def _tool_result(result: ToolResult) -> str:
    """将 ToolResult 序列化为 JSON 字符串"""
    return json.dumps(
        {
            "status": result.status,
            "data": result.data,
            "error_code": result.error_code,
            "message": result.message,
            "suggestion": result.suggestion,
        },
        ensure_ascii=False,
        default=str,
    )


def _call_adapter_method(platform_code: str, method_name: str, company_id: str, *args, **kwargs):
    """通过熔断器调用适配器方法（同步）"""
    adapter = get_platform_adapter(platform_code, company_id)
    if not adapter:
        return ToolResult.error(
            ErrorCode.NOT_FOUND,
            message=f"平台 '{platform_code}' 未注册或不可用",
            suggestion="请检查平台凭证是否已配置",
        )

    method = getattr(adapter, method_name, None)
    if method is None or not callable(method):
        return ToolResult.error(
            ErrorCode.NOT_SUPPORTED,
            message=f"平台 '{platform_code}' 不支持能力 '{method_name}'",
        )

    breaker = get_circuit_breaker(f"platform_{platform_code}", 5, 30)
    try:
        result = breaker.call_sync(method, *args, **kwargs)
        return ToolResult.ok(data=result, message=f"{platform_code}.{method_name} 成功")
    except CircuitBreakerOpenError as e:
        return ToolResult.error(
            ErrorCode.RATE_LIMITED,
            message=f"平台 '{platform_code}' 熔断中，请 {e.retry_after}s 后重试",
            suggestion="等待熔断恢复或检查平台 API 状态",
        )
    except Exception as e:
        logger.error(
            "platform_tool_call_failed", platform=platform_code, method=method_name, error=str(e)
        )
        return ToolResult.error(
            ErrorCode.INTERNAL_ERROR,
            message=f"调用 {platform_code}.{method_name} 失败: {e}",
            suggestion="检查凭证配置或平台 API 可用性",
        )


# ── 能力 → 方法映射 ────────────────────────────────────────────

_CAPABILITY_MAP = {
    "search_creators": {
        "method": "search_creators",
        "params": [("category", str), ("count", int)],
        "doc": "搜索平台达人/KOL",
    },
    "get_campaign_report": {
        "method": "get_campaign_report",
        "params": [("kol_id", str), ("campaign_id", str)],
        "doc": "获取投放 campaign 效果报告",
    },
    "get_shop_data": {
        "method": "get_shop_data",
        "params": [("shop_id", str)],
        "doc": "获取店铺运营数据",
    },
    "get_platform_info": {
        "method": "get_platform_info",
        "params": [],
        "doc": "获取平台信息与能力",
    },
}


# ── 动态注册工具 ────────────────────────────────────────────────


def register_platform_tools(mcp_instance: FastMCP) -> int:
    """为每个平台 × 每个能力注册一个 MCP 工具。

    Returns:
        注册的工具数量
    """
    count = 0
    for platform_code in PLATFORM_ADAPTERS:
        for cap_name, cap_info in _CAPABILITY_MAP.items():
            tool_name = f"{platform_code}_{cap_name}"
            _register_tool(mcp_instance, platform_code, cap_name, cap_info, tool_name)
            count += 1
    logger.info("platform_tools_registered", count=count)
    return count


def _register_tool(mcp_instance, platform_code, cap_name, cap_info, tool_name):
    """注册单个平台工具"""
    method_name = cap_info["method"]
    doc = f"{cap_info['doc']}（平台: {platform_code}）"

    # 根据参数签名动态构建工具函数
    params = cap_info["params"]

    if not params:
        # 无参数工具
        def tool_func(company_id: int = None) -> str:
            """{doc}"""
            cid = _resolve_company_id(str(company_id) if company_id else "default")
            result = _call_adapter_method(platform_code, method_name, cid)
            return _tool_result(result)

    elif len(params) == 1:
        p0_name, p0_type = params[0]

        def tool_func(p0: p0_type, company_id: int = None) -> str:
            """{doc}"""
            cid = _resolve_company_id(str(company_id) if company_id else "default")
            result = _call_adapter_method(platform_code, method_name, cid, p0)
            return _tool_result(result)

    elif len(params) == 2:
        p0_name, p0_type = params[0]
        p1_name, p1_type = params[1]

        def tool_func(p0: p0_type, p1: p1_type, company_id: int = None) -> str:
            """{doc}"""
            cid = _resolve_company_id(str(company_id) if company_id else "default")
            result = _call_adapter_method(platform_code, method_name, cid, p0, p1)
            return _tool_result(result)

    else:
        return  # 不支持 3+ 参数

    # 设置函数名和文档
    tool_func.__name__ = tool_name
    tool_func.__doc__ = doc

    # 注册到 MCP
    mcp_instance.tool()(tool_func)


# 模块加载时自动注册所有平台工具
register_platform_tools(mcp)


if __name__ == "__main__":
    from app.mcp_servers.runtime import run_mcp_stdio

    run_mcp_stdio(mcp)
