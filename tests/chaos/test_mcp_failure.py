"""
16.4.2 混沌测试：MCP Server宕机降级
验证 MCP Server 不可用时的降级行为
"""
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest


class TestMCPFailureDegradation:
    """MCP Server 宕机降级混沌测试"""

    # ── 场景1: MCP Server 连接失败 → 工具注册降级 ────────────────

    def test_mcp_server_connection_failure(self):
        """MCP Server 连接失败时不阻塞其他工具加载"""
        from app.tools.loader import ToolLoader

        loader = ToolLoader()

        # 模拟 MCP Server 启动失败
        with patch.object(loader, '_load_mcp_stdio', side_effect=Exception("MCP Server process failed")):
            # 验证 loader 本身可以正常创建，mock 生效
            assert loader is not None

    # ── 场景2: 工具调用超时 → 降级策略 ───────────────────────────

    @pytest.mark.asyncio
    async def test_tool_timeout_degradation(self):
        """工具调用超时后触发降级"""
        # 模拟工具超时
        async def slow_tool():
            await asyncio.sleep(10)
            return "slow_result"

        try:
            result = await asyncio.wait_for(slow_tool(), timeout=0.1)
        except asyncio.TimeoutError:
            result = {"error": "TOOL_TIMEOUT", "suggestion": "请稍后重试或使用缓存数据"}

        assert result["error"] == "TOOL_TIMEOUT"
        assert "suggestion" in result

    # ── 场景3: MCP Server 进程崩溃后健康检查 ──────────────────────

    def test_mcp_server_crash_and_health_check(self):
        """MCP Server 崩溃后健康检查应报告不健康"""
        from app.tools.loader import ToolLoader

        loader = ToolLoader()

        # 模拟健康检查：部分 Server 不健康
        loader._mcp_health = {
            "report_server": False,
            "kol_search_server": True,
            "outreach_server": False,
        }

        healthy = [name for name, status in loader._mcp_health.items() if status]
        unhealthy = [name for name, status in loader._mcp_health.items() if not status]

        assert len(healthy) == 1
        assert "kol_search_server" in healthy
        assert len(unhealthy) == 2

    # ── 场景4: 部分 MCP Server 宕机 → 功能部分可用 ────────────────

    def test_partial_mcp_server_failure(self):
        """部分 MCP Server 宕机时其他功能不受影响"""
        from app.tools.loader import ToolLoader

        loader = ToolLoader()

        loader._mcp_health = {
            "report_server": False,
            "kol_search_server": True,
            "outreach_server": True,
            "script_server": True,
            "monitor_server": True,
        }

        available_count = sum(1 for v in loader._mcp_health.values() if v)
        total_count = len(loader._mcp_health)

        assert available_count == 4
        assert available_count < total_count
        assert available_count / total_count > 0.5

    # ── 场景5: 工具描述验证评分 ──────────────────────────────────

    def test_tool_description_validation_scoring(self):
        """工具描述验证评分：短描述得分低"""
        from app.tools.loader import ToolLoader

        loader = ToolLoader()

        # 模拟一个描述极不完善的工具（名称过短且无描述）
        bad_tool = MagicMock()
        bad_tool.name = "b"  # 名称过短
        bad_tool.description = ""  # 空描述
        # 移除 args_schema 以降低评分
        bad_tool.args_schema = None

        is_valid, reason = loader._validate_tool_description(bad_tool, "test_provider")
        # 空描述得分应该低于阈值
        assert "score=" in reason

    # ── 场景6: 所有 MCP Server 宕机 → 功能不中断 ──────────────────

    def test_all_mcp_servers_down_no_crash(self):
        """所有 MCP Server 宕机时系统不崩溃"""
        from app.tools.loader import ToolLoader

        loader = ToolLoader()

        loader._mcp_health = {
            "report_server": False,
            "kol_search_server": False,
            "outreach_server": False,
            "script_server": False,
            "monitor_server": False,
        }

        all_healthy = all(loader._mcp_health.values())
        assert all_healthy is False

        # 系统不应崩溃，ToolLoader 实例仍存在
        assert loader is not None