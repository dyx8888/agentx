"""
ReportGenerator - 评测报告生成器
生成 JSON 和 Markdown 格式的评测报告
"""
import json
import os
from datetime import datetime

from tests.evaluation.metrics import AggregateMetrics, EvalMetrics


class ReportGenerator:
    """评测报告生成器"""

    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "reports",
            "evaluation",
        )
        os.makedirs(self.output_dir, exist_ok=True)

    def generate(self, agg: AggregateMetrics, results: list[EvalMetrics]) -> dict:
        """生成完整评测报告"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        report_data = {
            "meta": {
                "timestamp": datetime.now().isoformat(),
                "total_cases": agg.total_cases,
                "passed": agg.passed,
                "failed": agg.failed,
            },
            "summary": {
                "completion_rate": round(agg.completion_rate * 100, 2),
                "tool_accuracy": round(agg.tool_accuracy * 100, 2),
                "avg_steps_per_case": round(agg.avg_steps_per_case, 2),
                "total_tokens": agg.total_tokens,
                "avg_execution_time_ms": round(agg.avg_execution_time_ms, 2),
            },
            "thresholds": {
                "completion_rate_passed": agg.completion_rate >= 0.80,
                "completion_rate_threshold": 80.0,
                "tool_accuracy_passed": agg.tool_accuracy >= 0.70,
                "tool_accuracy_threshold": 70.0,
            },
            "per_agent": {},
            "per_scenario": {},
            "details": [],
        }

        for agent_name, metrics in agg.per_agent.items():
            report_data["per_agent"][agent_name] = {
                "completion_rate": round(metrics.completion_rate * 100, 2),
                "tool_accuracy": round(metrics.tool_accuracy * 100, 2),
                "avg_steps": round(metrics.avg_steps, 2),
                "total_tokens": metrics.token_consumed,
                "avg_execution_time_ms": round(metrics.execution_time_ms, 2),
            }

        for scenario, scenario_results in agg.per_scenario.items():
            report_data["per_scenario"][scenario] = {
                "total": len(scenario_results),
                "passed": sum(1 for r in scenario_results if r.success),
                "failed": sum(1 for r in scenario_results if not r.success),
            }

        for r in results:
            report_data["details"].append({
                "agent": r.agent_name,
                "scenario": r.scenario,
                "success": r.success,
                "tool_accuracy": round(r.tool_accuracy * 100, 2),
                "steps": r.total_steps,
                "tokens": r.token_consumed,
                "execution_time_ms": round(r.execution_time_ms, 2),
                "errors": r.errors,
            })

        # Save JSON
        json_path = os.path.join(self.output_dir, f"report_{timestamp}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        # Save Markdown
        md_path = os.path.join(self.output_dir, f"report_{timestamp}.md")
        md_content = self._generate_markdown(report_data)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        report_data["json_path"] = json_path
        report_data["md_path"] = md_path

        return report_data

    def _generate_markdown(self, report: dict) -> str:
        """生成 Markdown 格式报告"""
        summary = report["summary"]
        thresholds = report["thresholds"]

        lines = [
            "# Agent 评测报告",
            f"\n**生成时间:** {report['meta']['timestamp']}",
            f"\n**总用例数:** {report['meta']['total_cases']} | **通过:** {report['meta']['passed']} | **失败:** {report['meta']['failed']}",
            "\n## 总体指标",
            f"\n| 指标 | 值 | 阈值 | 通过 |",
            f"|------|-----|------|------|",
            f"| 完成率 | {summary['completion_rate']}% | >= 80% | {'✅' if thresholds['completion_rate_passed'] else '❌'} |",
            f"| 工具准确率 | {summary['tool_accuracy']}% | >= 70% | {'✅' if thresholds['tool_accuracy_passed'] else '❌'} |",
            f"| 平均步数 | {summary['avg_steps_per_case']} | - | - |",
            f"| 总Token消耗 | {summary['total_tokens']} | - | - |",
            f"| 平均执行时间 | {summary['avg_execution_time_ms']}ms | - | - |",
            "\n## 各Agent表现",
        ]

        if report["per_agent"]:
            lines.append("\n| Agent | 完成率 | 工具准确率 | 平均步数 | Token消耗 | 平均耗时 |")
            lines.append("|-------|--------|-----------|---------|----------|---------|")
            for agent_name, metrics in report["per_agent"].items():
                lines.append(
                    f"| {agent_name} | {metrics['completion_rate']}% | {metrics['tool_accuracy']}% | "
                    f"{metrics['avg_steps']} | {metrics['total_tokens']} | {metrics['avg_execution_time_ms']}ms |"
                )

        lines.append("\n## 各场景表现")
        if report["per_scenario"]:
            lines.append("\n| 场景 | 总数 | 通过 | 失败 |")
            lines.append("|------|------|------|------|")
            for scenario, stats in report["per_scenario"].items():
                lines.append(f"| {scenario} | {stats['total']} | {stats['passed']} | {stats['failed']} |")

        lines.append("\n## 详细结果")
        lines.append("\n| Agent | 场景 | 结果 | 工具准确率 | 步数 | Token | 耗时(ms) |")
        lines.append("|-------|------|------|-----------|------|-------|---------|")
        for d in report["details"]:
            status = "✅" if d["success"] else "❌"
            lines.append(
                f"| {d['agent']} | {d['scenario']} | {status} | {d['tool_accuracy']}% | "
                f"{d['steps']} | {d['tokens']} | {d['execution_time_ms']} |"
            )

        if any(d["errors"] for d in report["details"]):
            lines.append("\n## 错误详情")
            for d in report["details"]:
                if d["errors"]:
                    lines.append(f"\n### {d['agent']} - {d['scenario']}")
                    for err in d["errors"]:
                        lines.append(f"- {err}")

        return "\n".join(lines)