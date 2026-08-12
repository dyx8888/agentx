"""
感知管道 - 工具结果解析器
将工具执行结果解析为结构化格式，提取关键信息并生成摘要
"""
# 解析器独立于管线运行，因为工具调用发生在管线之后，仍需要统一的解析入口

from dataclasses import dataclass, field  # dataclass 承载解析结果

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ParsedToolResult:  # 独立数据类，让下游 Agent 只依赖此结构而不关心原始工具输出格式
    """解析后的工具结果"""

    tool_name: str = ""  # 工具名称，用于日志和路由
    status: str = "unknown"  # 统一状态：ok / error / empty / pending_approval / unknown
    summary: str = ""  # 简短摘要，用于快速展示或决策
    key_data: dict = field(default_factory=dict)  # 关键数据，提取最有用的字段
    error_message: str = ""  # 错误信息，非空时表示执行失败
    raw_output: str = ""  # 原始输出截断到 4000 字符，用于调试追溯


class ToolResultParser:
    """解析工具执行结果，提取关键信息并生成摘要"""

    def parse(self, tool_name: str, output: object) -> ParsedToolResult:
        """
        解析工具执行结果

        Args:
            tool_name: 工具名称
            output: 工具原始输出（可以是 str, dict, ToolResult 等）

        Returns:
            ParsedToolResult 结构化结果
        """
        raw_output = self._extract_text(output)  # 先统一提取文本表示，后续所有解析路径都基于此

        result = ParsedToolResult(
            tool_name=tool_name,
            raw_output=str(raw_output)[:4000],  # 截断到 4000 字符，防止超大输出撑爆上下文
        )

        if output is None:  # None 优先处理，避免后续 isinstance 检查报错
            result.status = "empty"
            result.summary = "工具返回空结果"
            return result

        try:  # 尝试匹配项目内部的 ToolResult 包装类
            from app.tools.result import ToolResult as TR

            if isinstance(output, TR):  # 如果是 ToolResult，走专用解析路径
                return self._parse_tool_result(output, tool_name, raw_output)
        except ImportError:  # 如果项目没有 ToolResult 类，静默跳过
            pass

        if isinstance(output, dict):  # 字典是最常见的工具输出格式，优先匹配
            result = self._parse_dict_result(output, tool_name, raw_output)
        elif isinstance(output, (list, tuple)):  # 列表/元组统一处理，因为两种都是有序集合
            result = self._parse_list_result(output, tool_name, raw_output)
        elif isinstance(output, str):  # 字符串输出可能内部是 JSON，尝试反序列化
            result = self._parse_string_result(output, tool_name, raw_output)
        else:  # 兜底处理任意类型，确保不崩溃
            result = self._parse_other_result(output, tool_name, raw_output)

        logger.debug(
            "tool_result_parsed",
            tool_name=tool_name,
            status=result.status,
            summary_length=len(result.summary),
        )

        return result

    def _parse_tool_result(self, output, tool_name: str, raw_output: str) -> ParsedToolResult:
        """解析 ToolResult 包装对象"""
        if output.is_ok():  # 成功状态：提取数据和摘要
            data = output.data
            summary = self._generate_summary_from_data(data, tool_name)
            key_data = self._extract_key_data(data)
            return ParsedToolResult(
                tool_name=tool_name,
                status="ok",
                summary=summary,
                key_data=key_data,
                raw_output=raw_output,
            )
        elif output.is_error():  # 错误状态：提取错误消息
            return ParsedToolResult(
                tool_name=tool_name,
                status="error",
                summary=f"工具执行失败: {output.message}",
                error_message=output.message,
                raw_output=raw_output,
            )
        elif output.needs_approval():  # 审批状态：需要人工介入，标记为 pending
            return ParsedToolResult(
                tool_name=tool_name,
                status="pending_approval",
                summary=f"工具 '{tool_name}' 需要审批: {output.message}",
                raw_output=raw_output,
            )
        return ParsedToolResult(  # 未知状态兜底，不抛异常
            tool_name=tool_name,
            status="unknown",
            summary="工具执行完成",
            raw_output=raw_output,
        )

    def _parse_dict_result(self, output: dict, tool_name: str, raw_output: str) -> ParsedToolResult:
        status = output.get("status", "ok")  # 字典格式工具通常包含 status 字段
        if status == "error":  # 错误状态单独处理，提取 error message
            return ParsedToolResult(
                tool_name=tool_name,
                status="error",
                summary=output.get("message", "工具执行失败"),
                error_message=output.get("message", ""),
                key_data=output.get("data", {}),
                raw_output=raw_output,
            )
        return ParsedToolResult(  # 非错误状态，统一取 data 字段作为关键数据
            tool_name=tool_name,
            status=status,
            summary=self._generate_summary_from_data(
                output.get("data", output), tool_name
            ),  # 无 data 时降级用整个 dict
            key_data=output.get("data", output),
            raw_output=raw_output,
        )

    def _parse_list_result(self, output: list, tool_name: str, raw_output: str) -> ParsedToolResult:
        return ParsedToolResult(  # 列表结果主要关注数量，前 5 项作为预览
            tool_name=tool_name,
            status="ok",
            summary=f"返回 {len(output)} 条结果",  # 数量摘要即足够决策
            key_data={"count": len(output), "items": output[:5]},  # 只取前 5 条防止超大 payload
            raw_output=raw_output,
        )

    def _parse_string_result(
        self, output: str, tool_name: str, raw_output: str
    ) -> ParsedToolResult:
        try:  # 字符串可能内嵌 JSON，尝试反序列化以获得更丰富的解析
            import json

            data = json.loads(output)
            return self._parse_dict_result(data, tool_name, raw_output)  # 成功则委托给 dict 解析器
        except (json.JSONDecodeError, ValueError):  # 非 JSON 字符串，走普通字符串处理
            pass

        return ParsedToolResult(  # 纯文本取前 200 字符作为摘要
            tool_name=tool_name,
            status="ok",
            summary=output[:200] if len(output) > 200 else output,
            key_data={"content": output[:1000]},  # 保留前 1000 字符供后续分析
            raw_output=raw_output,
        )

    def _parse_other_result(self, output, tool_name: str, raw_output: str) -> ParsedToolResult:
        return ParsedToolResult(  # 未知类型直接转字符串，用前 200 字符做摘要
            tool_name=tool_name,
            status="ok",
            summary=str(output)[:200],
            key_data={"content": str(output)[:1000]},
            raw_output=raw_output,
        )

    def _extract_text(self, output) -> str:  # 统一文本提取入口，所有类型都走同一方法
        """从任意输出中提取文本"""
        if output is None:  # None 返回空字符串，调用方自行处理
            return ""
        if hasattr(output, "content"):  # LangChain 响应对象，优先取 .content
            return str(output.content)
        if hasattr(output, "to_json"):  # 支持自定义序列化接口
            return output.to_json()
        if hasattr(output, "to_dict"):  # to_dict 后手动 json.dumps，因为返回的是 Python 对象
            import json

            return json.dumps(
                output.to_dict(), ensure_ascii=False, default=str
            )  # ensure_ascii=False 保留中文
        return str(output)  # 终极兜底：转字符串

    def _generate_summary_from_data(
        self, data, tool_name: str
    ) -> str:  # 独立方法便于测试和自定义摘要策略
        """从数据中生成简短摘要"""
        if data is None:
            return "工具执行完成，返回空数据"
        if isinstance(data, list):  # 列表摘要 = 数量
            return f"返回 {len(data)} 条结果"
        if isinstance(data, dict):  # 字典摘要 = message 字段 或 字段名列表
            if "message" in data:  # message 优先，因为它是人类可读的描述
                return str(data["message"])[:200]
            keys = list(data.keys())  # 无 message 时展示字段名列表，帮助判断数据结构
            return f"返回数据包含 {len(keys)} 个字段: {', '.join(keys[:5])}"  # 最多展示 5 个字段名
        if isinstance(data, str):  # 字符串直接截断
            return data[:200] if len(data) > 200 else data
        return "工具执行完成"  # 其他类型不强行摘要

    def _extract_key_data(self, data) -> dict:  # 统一返回 dict，保证下游调用一致性
        """提取关键数据字段"""
        if data is None:
            return {}
        if isinstance(data, dict):  # 已经是 dict 直接返回
            return data
        if isinstance(data, list):  # 列表取 count + 前 5 条
            return {"count": len(data), "items": data[:5]}
        if isinstance(data, str):  # 字符串截断存储
            return {"content": data[:1000]}
        return {"content": str(data)[:1000]}  # 其他类型统一转字符串截断
