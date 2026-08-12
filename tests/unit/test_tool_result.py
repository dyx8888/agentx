"""
16.1.4 _wrap_tool_result() 单元测试
ok/error/pending_approval/非ToolResult
"""


class TestWrapToolResult:
    """工具结果包装单元测试"""

    def test_ok_result(self):
        """ok 结果"""
        from app.tools.result import ToolResult

        result = ToolResult.ok(data={"count": 10}, message="成功")
        assert result.is_ok()
        assert result.data == {"count": 10}
        assert result.message == "成功"

    def test_error_result(self):
        """error 结果"""
        from app.tools.result import ToolResult, ErrorCode

        result = ToolResult.error(
            error_code=ErrorCode.TOOL_TIMEOUT,
            message="工具执行超时",
            suggestion="请减少请求范围后重试",
        )
        assert result.is_error()
        assert result.error_code == ErrorCode.TOOL_TIMEOUT
        assert result.suggestion is not None

    def test_pending_approval_result(self):
        """pending_approval 结果"""
        from app.tools.result import ToolResult

        result = ToolResult.pending_approval(
            tool_name="schedule_task",
            proposed_params={"platform": "douyin"},
            message="需要管理员审批",
        )
        assert result.needs_approval()
        assert result.tool_name == "schedule_task"

    def test_non_tool_result_string(self):
        """非ToolResult（字符串）"""
        output = "普通字符串结果"
        from app.tools.result import ToolResult

        assert not isinstance(output, ToolResult)

    def test_non_tool_result_dict(self):
        """非ToolResult（字典）"""
        output = {"status": "ok", "data": [1, 2, 3]}
        from app.tools.result import ToolResult

        assert not isinstance(output, ToolResult)

    def test_error_code_enum(self):
        """ErrorCode 常量完整性"""
        from app.tools.result import ErrorCode

        codes = [
            ErrorCode.TOOL_TIMEOUT,
            ErrorCode.CONNECTION_ERROR,
            ErrorCode.RATE_LIMITED,
            ErrorCode.INVALID_PARAMS,
            ErrorCode.MAX_CALLS_EXCEEDED,
            ErrorCode.PERMISSION_DENIED,
            ErrorCode.UNKNOWN_ERROR,
        ]
        assert len(codes) == 7

    def test_error_suggestions(self):
        """ERROR_SUGGESTIONS 映射表"""
        from app.tools.result import ERROR_SUGGESTIONS, ErrorCode

        expected_codes = [
            ErrorCode.TOOL_TIMEOUT,
            ErrorCode.CONNECTION_ERROR,
            ErrorCode.RATE_LIMITED,
            ErrorCode.INVALID_PARAMS,
            ErrorCode.MAX_CALLS_EXCEEDED,
            ErrorCode.PERMISSION_DENIED,
            ErrorCode.UNKNOWN_ERROR,
        ]
        for code in expected_codes:
            assert code in ERROR_SUGGESTIONS, f"{code} 缺少建议"
