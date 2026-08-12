"""Runtime helpers for MCP stdio servers."""

from __future__ import annotations

import logging
import os
from typing import Any


def configure_stdio_runtime() -> None:
    """Keep MCP stdio stdout reserved for JSON-RPC protocol messages."""
    os.environ.setdefault("FASTMCP_SHOW_SERVER_BANNER", "false")
    os.environ.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")
    os.environ.setdefault("FASTMCP_LOG_LEVEL", "ERROR")
    os.environ.setdefault("FASTMCP_ENABLE_RICH_LOGGING", "false")
    os.environ.setdefault("FASTMCP_ENABLE_RICH_TRACEBACKS", "false")
    os.environ.setdefault("LOG_TO_STDERR", "true")
    os.environ.setdefault("LOG_LEVEL", "ERROR")

    try:
        from app.core.logging import configure_logging

        configure_logging()
    except Exception:
        pass

    try:
        from fastmcp import settings

        settings.set_setting("show_server_banner", False)
        settings.set_setting("check_for_updates", "off")
        settings.set_setting("log_level", "ERROR")
        settings.set_setting("enable_rich_logging", False)
        settings.set_setting("enable_rich_tracebacks", False)
    except Exception:
        pass

    for logger_name in ("fastmcp", "mcp", "httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(logging.ERROR)


def run_mcp_stdio(mcp: Any) -> None:
    """Run a FastMCP server in clean stdio mode."""
    configure_stdio_runtime()
    mcp.run(transport="stdio", show_banner=False)
