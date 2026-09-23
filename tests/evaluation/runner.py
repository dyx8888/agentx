"""
Evaluation Runner - 评测执行器
支持 CLI 入口和 CI 模式，批量执行评测用例并生成报告
"""

import argparse
import json
import os
import sys
import time

from tests.evaluation.metrics import AggregateMetrics, EvalMetrics, MetricsCalculator
from tests.evaluation.report import ReportGenerator
from tests.evaluation.root_cause import RootCauseAnalyzer


class EvaluationRunner:
    """评测执行器"""

    def __init__(self, agent_runtime=None):
        self._runtime = agent_runtime
        self.calculator = MetricsCalculator()
        self.report_generator = ReportGenerator()
        self.root_cause_analyzer = RootCauseAnalyzer()

    def load_cases(self, agent_name: str = None) -> list[dict]:
        """加载评测用例"""
        cases_dir = os.path.join(os.path.dirname(__file__), "cases")
        all_cases = []

        if not os.path.isdir(cases_dir):
            print(f"Warning: cases directory not found: {cases_dir}")
            return all_cases

        for filename in os.listdir(cases_dir):
            if not filename.endswith(".json"):
                continue
            if agent_name and not filename.startswith(agent_name):
                continue

            filepath = os.path.join(cases_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    all_cases.extend(data)
                elif isinstance(data, dict) and "cases" in data:
                    all_cases.extend(data["cases"])
            except Exception as e:
                print(f"Error loading {filename}: {e}")

        return all_cases

    def validate_case_files(self) -> tuple[int, list[str]]:
        """Validate every case file without initializing the live Agent runtime."""
        cases_dir = os.path.join(os.path.dirname(__file__), "cases")
        errors: list[str] = []
        case_count = 0

        for filename in sorted(os.listdir(cases_dir)):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(cases_dir, filename)
            try:
                with open(filepath, encoding="utf-8") as file:
                    data = json.load(file)
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"{filename}: {exc}")
                continue

            if isinstance(data, list):
                cases = data
            elif isinstance(data, dict):
                cases = data.get("cases")
            else:
                errors.append(
                    f"{filename}: expected a list or an object containing 'cases'"
                )
                continue
            if not isinstance(cases, list):
                errors.append(
                    f"{filename}: expected a list or an object containing 'cases'"
                )
                continue

            for index, case in enumerate(cases):
                if not isinstance(case, dict):
                    errors.append(f"{filename}[{index}]: expected an object")
                    continue
                if not isinstance(case.get("message"), str):
                    errors.append(f"{filename}[{index}]: message must be a string")
                repeat = case.get("message_repeat", 1)
                if (
                    not isinstance(repeat, int)
                    or isinstance(repeat, bool)
                    or repeat < 1
                ):
                    errors.append(
                        f"{filename}[{index}]: message_repeat must be a positive integer"
                    )
                case_count += 1

        return case_count, errors

    @staticmethod
    def expand_message(case: dict) -> str:
        repeat = case.get("message_repeat", 1)
        return case.get("message", "") * repeat

    async def run_case(self, case: dict) -> EvalMetrics:
        """执行单个评测用例"""
        agent_name = case.get("agent", "unknown")
        scenario = case.get("scenario", "general")
        user_message = self.expand_message(case)
        expected_tools = case.get("expected_tools", [])
        expected_output_contains = case.get("expected_output_contains", [])

        start_time = time.time()
        errors = []
        actual_tool_calls = []
        total_steps = 0
        token_consumed = 0
        success = False

        try:
            if self._runtime:
                result = await self._runtime.run(
                    message=user_message,
                    agent_name=agent_name,
                )

                response = result.get("response", "")
                step_results = result.get("step_results", [])
                total_steps = len(step_results)
                actual_tool_calls = [
                    sr.get("tool_used", "")
                    for sr in step_results
                    if sr.get("tool_used")
                ]

                if result.get("success", False):
                    success = True
                elif response:
                    success = True

                if expected_output_contains:
                    for expected in expected_output_contains:
                        if expected.lower() not in response.lower():
                            success = False
                            errors.append(f"Expected output not found: '{expected}'")

                if expected_tools and not actual_tool_calls:
                    success = False
                    errors.append(
                        f"Expected tools {expected_tools} but no tools were called"
                    )
            else:
                errors.append("AgentRuntime not available for evaluation")

        except Exception as e:
            errors.append(f"Execution error: {str(e)}")

        execution_time_ms = (time.time() - start_time) * 1000

        return MetricsCalculator.compute_single(
            agent_name=agent_name,
            scenario=scenario,
            expected_tools=expected_tools,
            actual_tool_calls=actual_tool_calls,
            total_steps=total_steps,
            token_consumed=token_consumed,
            execution_time_ms=execution_time_ms,
            success=success,
            errors=errors,
        )

    async def run_all(
        self, agent_name: str = None
    ) -> tuple[AggregateMetrics, list[EvalMetrics]]:
        """执行所有评测用例"""
        cases = self.load_cases(agent_name)
        if not cases:
            print("No test cases found.")
            return AggregateMetrics(), []

        print(f"Running {len(cases)} test cases...")
        results: list[EvalMetrics] = []

        for i, case in enumerate(cases):
            agent = case.get("agent", "unknown")
            scenario = case.get("scenario", "general")
            print(f"  [{i + 1}/{len(cases)}] {agent} - {scenario} ...", end=" ")
            result = await self.run_case(case)
            results.append(result)
            status = "PASS" if result.success else "FAIL"
            print(status)

        agg = self.calculator.compute(results)
        return agg, results

    def generate_report(
        self, agg: AggregateMetrics, results: list[EvalMetrics]
    ) -> dict:
        """生成评测报告"""
        return self.report_generator.generate(agg, results)

    def generate_root_cause_report(
        self, agg: AggregateMetrics, results: list[EvalMetrics]
    ) -> dict:
        """生成根因分析报告"""
        return self.root_cause_analyzer.analyze(agg, results)

    def check_ci(self, agg: AggregateMetrics) -> bool:
        """CI 模式：检查是否通过阈值"""
        thresholds = self.calculator.check_thresholds(agg)
        all_passed = all(thresholds.values())
        if not all_passed:
            failed = [k for k, v in thresholds.items() if not v]
            print(f"CI thresholds not met: {failed}")
        return all_passed


async def main():
    parser = argparse.ArgumentParser(description="Agent Evaluation Runner")
    parser.add_argument("--agent", type=str, help="Filter by agent name")
    parser.add_argument(
        "--ci", action="store_true", help="CI mode (exit code 1 on failure)"
    )
    parser.add_argument(
        "--root-cause", action="store_true", help="Generate root cause analysis"
    )
    parser.add_argument(
        "--validate-cases",
        action="store_true",
        help="Validate evaluation JSON files without running live agents",
    )
    args = parser.parse_args()

    runner = EvaluationRunner()
    if args.validate_cases:
        case_count, errors = runner.validate_case_files()
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            sys.exit(1)
        print(f"Validated {case_count} evaluation cases.")
        return

    try:
        # Try to initialize AgentRuntime
        sys.path.insert(
            0, os.path.join(os.path.dirname(__file__), "..", "..", "backend")
        )
        from app.runtime.orchestrator import AgentRuntime

        runtime = AgentRuntime()
    except Exception as e:
        print(f"Warning: Could not initialize AgentRuntime: {e}")
        runtime = None

    runner = EvaluationRunner(agent_runtime=runtime)
    agg, results = await runner.run_all(agent_name=args.agent)

    report = runner.generate_report(agg, results)
    print(f"\nReport saved to: {report.get('json_path', 'N/A')}")
    print(f"Markdown report: {report.get('md_path', 'N/A')}")

    if args.root_cause:
        rc_report = runner.generate_root_cause_report(agg, results)
        rc_path = os.path.join(
            os.path.dirname(report.get("json_path", ".")),
            "root_cause_analysis.json",
        )
        with open(rc_path, "w", encoding="utf-8") as f:
            json.dump(rc_report, f, ensure_ascii=False, indent=2)
        print(f"\nRoot cause analysis: {rc_path}")

    print(f"\nSummary: {agg.passed}/{agg.total_cases} passed")
    print(f"Completion Rate: {agg.completion_rate:.1%}")
    print(f"Tool Accuracy: {agg.tool_accuracy:.1%}")

    if args.ci:
        if not runner.check_ci(agg):
            sys.exit(1)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
