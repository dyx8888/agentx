"""
MetricsCalculator - 评测指标计算器
计算工具调用准确率、平均步数、Token消耗、完成率等
"""
from dataclasses import dataclass, field


@dataclass
class EvalMetrics:
    """单次评测的指标"""
    agent_name: str = ""
    scenario: str = ""
    success: bool = False
    completion_rate: float = 0.0
    tool_accuracy: float = 0.0
    avg_steps: float = 0.0
    token_consumed: int = 0
    total_steps: int = 0
    correct_tool_calls: int = 0
    total_tool_calls: int = 0
    execution_time_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


@dataclass
class AggregateMetrics:
    """聚合评测指标"""
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    completion_rate: float = 0.0
    tool_accuracy: float = 0.0
    avg_steps_per_case: float = 0.0
    total_tokens: int = 0
    avg_execution_time_ms: float = 0.0
    per_agent: dict[str, EvalMetrics] = field(default_factory=dict)
    per_scenario: dict[str, list[EvalMetrics]] = field(default_factory=dict)


class MetricsCalculator:
    """评测指标计算器"""

    def compute(self, results: list[EvalMetrics]) -> AggregateMetrics:
        """计算聚合指标"""
        agg = AggregateMetrics(total_cases=len(results))

        if not results:
            return agg

        agg.passed = sum(1 for r in results if r.success)
        agg.failed = agg.total_cases - agg.passed
        agg.completion_rate = agg.passed / agg.total_cases if agg.total_cases > 0 else 0.0

        success_results = [r for r in results if r.success]
        if success_results:
            agg.tool_accuracy = (
                sum(r.tool_accuracy for r in success_results) / len(success_results)
            )
            agg.avg_steps_per_case = (
                sum(r.total_steps for r in success_results) / len(success_results)
            )
        else:
            agg.tool_accuracy = 0.0
            agg.avg_steps_per_case = 0.0

        agg.total_tokens = sum(r.token_consumed for r in results)
        agg.avg_execution_time_ms = (
            sum(r.execution_time_ms for r in results) / agg.total_cases
            if agg.total_cases > 0 else 0.0
        )

        # Per-agent aggregation
        agent_results: dict[str, list[EvalMetrics]] = {}
        for r in results:
            agent_results.setdefault(r.agent_name, []).append(r)
        for agent_name, agent_list in agent_results.items():
            agent_passed = sum(1 for r in agent_list if r.success)
            agg.per_agent[agent_name] = EvalMetrics(
                agent_name=agent_name,
                success=agent_passed == len(agent_list),
                completion_rate=agent_passed / len(agent_list) if agent_list else 0,
                tool_accuracy=(
                    sum(r.tool_accuracy for r in agent_list if r.success)
                    / max(len([r for r in agent_list if r.success]), 1)
                ),
                avg_steps=(
                    sum(r.total_steps for r in agent_list) / len(agent_list)
                    if agent_list else 0
                ),
                token_consumed=sum(r.token_consumed for r in agent_list),
                total_steps=sum(r.total_steps for r in agent_list),
                execution_time_ms=(
                    sum(r.execution_time_ms for r in agent_list) / len(agent_list)
                    if agent_list else 0
                ),
            )

        # Per-scenario aggregation
        scenario_results: dict[str, list[EvalMetrics]] = {}
        for r in results:
            scenario_results.setdefault(r.scenario, []).append(r)
        for scenario, scenario_list in scenario_results.items():
            agg.per_scenario[scenario] = scenario_list

        return agg

    def check_thresholds(self, agg: AggregateMetrics) -> dict[str, bool]:
        """检查是否通过评测阈值"""
        thresholds = {
            "completion_rate": agg.completion_rate >= 0.80,
            "tool_accuracy": agg.tool_accuracy >= 0.70,
        }
        return thresholds

    @staticmethod
    def compute_single(
        agent_name: str,
        scenario: str,
        expected_tools: list[str],
        actual_tool_calls: list[str],
        total_steps: int,
        token_consumed: int,
        execution_time_ms: float,
        success: bool,
        errors: list[str] = None,
    ) -> EvalMetrics:
        """计算单次评测指标"""
        total_tool_calls = len(actual_tool_calls)
        if total_tool_calls > 0 and expected_tools:
            expected_set = set(expected_tools)
            correct = sum(1 for t in actual_tool_calls if t in expected_set)
            tool_accuracy = correct / total_tool_calls
        elif total_tool_calls == 0 and not expected_tools:
            tool_accuracy = 1.0
        else:
            tool_accuracy = 0.0

        return EvalMetrics(
            agent_name=agent_name,
            scenario=scenario,
            success=success,
            completion_rate=1.0 if success else 0.0,
            tool_accuracy=tool_accuracy,
            avg_steps=float(total_steps) if total_steps > 0 else 0.0,
            token_consumed=token_consumed,
            total_steps=total_steps,
            correct_tool_calls=sum(1 for t in actual_tool_calls if t in expected_tools),
            total_tool_calls=total_tool_calls,
            execution_time_ms=execution_time_ms,
            errors=errors or [],
        )