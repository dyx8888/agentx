"""
RootCauseAnalyzer - 评测根因分析器
从低分案例中自动归纳失败模式，输出优化建议
"""
from dataclasses import dataclass, field
from enum import StrEnum

from tests.evaluation.metrics import AggregateMetrics, EvalMetrics


class FailureMode(StrEnum):
    PLAN_ERROR = "规划错误"
    TOOL_MISMATCH = "工具误选"
    PARAM_ERROR = "参数错误"
    HALLUCINATION = "幻觉"
    SECURITY_BYPASS = "安全绕过"
    POOR_ERROR_HANDLING = "异常处理差"


FAILURE_MODE_SUGGESTIONS = {
    FailureMode.PLAN_ERROR: "改进提示词 + 增加示例 (few-shot)；检查 Plan-and-Solve 模式是否启用",
    FailureMode.TOOL_MISMATCH: "优化工具描述，确保 LLM 能准确理解工具用途；考虑增加工具选择验证步骤",
    FailureMode.PARAM_ERROR: "增加参数校验逻辑；在工具描述中明确参数格式和约束",
    FailureMode.HALLUCINATION: "强化 RAG 检索注入；限制 Agent 输出范围；增加事实核查步骤",
    FailureMode.SECURITY_BYPASS: "增加输入护栏 (InputFilter)；强化 System Prompt 中的安全约束",
    FailureMode.POOR_ERROR_HANDLING: "完善工具错误返回格式；在 Agent 提示词中增加错误处理指导",
}


@dataclass
class FailurePattern:
    """失败模式分析结果"""
    mode: FailureMode
    cases: list[EvalMetrics] = field(default_factory=list)
    suggestion: str = ""
    affected_count: int = 0

    @property
    def severity(self) -> str:
        """基于受影响案例数判断严重程度"""
        if self.affected_count >= 5:
            return "high"
        elif self.affected_count >= 3:
            return "medium"
        return "low"


class RootCauseAnalyzer:
    """评测根因分析器 - 从失败案例中归纳失败模式"""

    def analyze(self, agg: AggregateMetrics, results: list[EvalMetrics]) -> dict:
        """分析失败案例，归纳根因"""
        failed = [r for r in results if not r.success]
        if not failed:
            return {
                "status": "all_passed",
                "message": "所有用例通过，无需根因分析",
                "patterns": [],
            }

        patterns = self._classify_failures(failed)

        # Sort by severity
        patterns.sort(key=lambda p: p.affected_count, reverse=True)

        top_patterns = patterns[:3]

        return {
            "status": "analysis_complete",
            "total_failed": len(failed),
            "total_cases": len(results),
            "patterns": [
                {
                    "mode": p.mode.value,
                    "severity": p.severity,
                    "affected_count": p.affected_count,
                    "suggestion": p.suggestion,
                    "example_cases": [
                        f"{c.agent_name} - {c.scenario}" for c in p.cases[:3]
                    ],
                }
                for p in patterns
            ],
            "top_3_patterns": [
                {
                    "mode": p.mode.value,
                    "affected_count": p.affected_count,
                    "suggestion": p.suggestion,
                }
                for p in top_patterns
            ],
            "summary": self._generate_summary(patterns),
        }

    def _classify_failures(self, failed: list[EvalMetrics]) -> list[FailurePattern]:
        """将失败案例按失败模式分类"""
        patterns: dict[FailureMode, FailurePattern] = {}

        for r in failed:
            mode = self._detect_failure_mode(r)
            if mode not in patterns:
                patterns[mode] = FailurePattern(
                    mode=mode,
                    suggestion=FAILURE_MODE_SUGGESTIONS.get(mode, ""),
                )
            patterns[mode].cases.append(r)
            patterns[mode].affected_count += 1

        return list(patterns.values())

    def _detect_failure_mode(self, result: EvalMetrics) -> FailureMode:
        """检测单个失败案例的失败模式"""
        errors = " ".join(result.errors).lower()

        if "tool" in errors and ("not found" in errors or "unavailable" in errors or "not in" in errors):
            return FailureMode.TOOL_MISMATCH

        if "tool" in errors and ("mismatch" in errors or "wrong" in errors or "expected" in errors):
            return FailureMode.TOOL_MISMATCH

        if "param" in errors or "argument" in errors or "invalid" in errors:
            return FailureMode.PARAM_ERROR

        if "plan" in errors or "step" in errors or "coverage" in errors:
            return FailureMode.PLAN_ERROR

        if "hallucinat" in errors or "made up" in errors or "fabricat" in errors:
            return FailureMode.HALLUCINATION

        if "security" in errors or "malicious" in errors or "bypass" in errors or "injection" in errors:
            return FailureMode.SECURITY_BYPASS

        if "error" in errors or "exception" in errors or "fail" in errors or "timeout" in errors:
            return FailureMode.POOR_ERROR_HANDLING

        # Heuristic: if tool_accuracy is 0 but tools were expected, it's tool mismatch
        if result.total_tool_calls > 0 and result.tool_accuracy == 0:
            return FailureMode.TOOL_MISMATCH

        # Heuristic: if no tools called but expected tools, it's plan error
        if result.total_tool_calls == 0 and result.errors:
            return FailureMode.PLAN_ERROR

        return FailureMode.POOR_ERROR_HANDLING

    def _generate_summary(self, patterns: list[FailurePattern]) -> str:
        """生成根因分析摘要"""
        if not patterns:
            return "无失败模式"

        top = max(patterns, key=lambda p: p.affected_count)
        total_affected = sum(p.affected_count for p in patterns)

        parts = [f"共发现 {len(patterns)} 种失败模式，影响 {total_affected} 个案例。"]
        parts.append(f"最主要失败模式: {top.mode.value}（{top.affected_count} 个案例）。")
        parts.append(f"建议: {top.suggestion}")

        return " ".join(parts)