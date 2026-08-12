"""
ToolResult - 统一的工具调用结果结构

提供结构化错误语义，支持 LLM 自愈循环。
"""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ToolResult:
    """工具调用结果的统一包装

    status 的三种状态：
      - "ok": 成功执行
      - "error": 执行失败，suggestion 和 fallback_tool 供 LLM 自愈
      - "pending_approval": 需人工审批后执行
    """

    status: Literal["ok", "error", "pending_approval"]
    data: Any = None
    error_code: str | None = None
    message: str = ""
    suggestion: str | None = None
    fallback_tool: str | None = None
    # pending_approval 相关
    tool_name: str = ""
    proposed_params: dict = field(default_factory=dict)

    @classmethod
    def ok(cls, data: Any = None, message: str = "") -> "ToolResult":
        """成功结果"""
        return cls(status="ok", data=data, message=message)

    @classmethod
    def error(
        cls,
        error_code: str,
        message: str = "",
        suggestion: str | None = None,
        fallback_tool: str | None = None,
    ) -> "ToolResult":
        """错误结果（带自愈建议）"""
        return cls(
            status="error",
            error_code=error_code,
            message=message,
            suggestion=suggestion,
            fallback_tool=fallback_tool,
        )

    @classmethod
    def pending_approval(
        cls,
        tool_name: str,
        proposed_params: dict = None,
        message: str = "",
    ) -> "ToolResult":
        """等待审批"""
        return cls(
            status="pending_approval",
            tool_name=tool_name,
            proposed_params=proposed_params or {},
            message=message or f"Tool '{tool_name}' requires approval before execution.",
        )

    def to_dict(self) -> dict:
        """序列化为字典（供 LLM 消息使用）"""
        d = {"status": self.status}
        if self.status == "ok":
            d["data"] = self.data
        elif self.status == "error":
            d["error_code"] = self.error_code
            d["message"] = self.message
            if self.suggestion:
                d["suggestion"] = self.suggestion
            if self.fallback_tool:
                d["fallback_tool"] = self.fallback_tool
        elif self.status == "pending_approval":
            d["tool_name"] = self.tool_name
            d["message"] = self.message
        return d

    def to_json(self) -> str:
        """序列化为 JSON 字符串（注入 LLM 消息历史）"""
        import json

        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    def is_error(self) -> bool:
        return self.status == "error"

    def is_ok(self) -> bool:
        return self.status == "ok"

    def needs_approval(self) -> bool:
        return self.status == "pending_approval"


# ── 错误码常量 ──────────────────────────────────────────────────


class ErrorCode:
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    INVALID_PARAMS = "INVALID_PARAMS"
    MAX_CALLS_EXCEEDED = "MAX_CALLS_EXCEEDED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


# ── 错误码 → 自愈建议映射 ──────────────────────────────────────

ERROR_SUGGESTIONS = {
    ErrorCode.TOOL_TIMEOUT: "Try reducing the scope of your request or retry later.",
    ErrorCode.CONNECTION_ERROR: "The service is unreachable. Consider using a fallback tool or skipping this step.",
    ErrorCode.RATE_LIMITED: "You are being rate limited. Wait briefly before retrying, or use a cached tool if available.",
    ErrorCode.INVALID_PARAMS: "Check your parameters and try again with corrected values.",
    ErrorCode.MAX_CALLS_EXCEEDED: "Maximum tool calls reached. Summarize findings and proceed to the next step.",
    ErrorCode.PERMISSION_DENIED: "You do not have permission to perform this action. Contact your administrator or request elevated access.",
    ErrorCode.UNKNOWN_ERROR: "An unexpected error occurred. Try an alternative approach.",
}
