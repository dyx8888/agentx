"""Runtime policy for MCP tools that still have demo/mock fixtures."""

import os

from app.tools.result import ErrorCode, ToolResult


def _env_flag(name: str, default: str = "false") -> bool:
    value = os.getenv(name, default)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def mock_fallback_enabled() -> bool:
    env = (os.getenv("ENV") or os.getenv("APP_ENV") or "dev").strip().lower()
    if _env_flag("ALLOW_PLATFORM_MOCK_FALLBACK", "false"):
        return True
    return env not in {"prod", "production"}


def mock_fallback_blocked_result(domain: str) -> str:
    return ToolResult.error(
        error_code=ErrorCode.CONNECTION_ERROR,
        message=f"{domain} data source unavailable; mock fallback is disabled.",
        suggestion=(
            "Bind verified platform credentials, import company-owned data, or enable "
            "ALLOW_PLATFORM_MOCK_FALLBACK=true only for local demo environments."
        ),
    ).to_json()
