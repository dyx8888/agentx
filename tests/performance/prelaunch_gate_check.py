"""Prelaunch report gate checker.

This reads the JSON reports produced by run_prelaunch_smoke.ps1 and turns them
into one clear pass/fail decision. It deliberately checks the things that are
easy to miss by eye: Milvus/hybrid evidence, fallback usage, negative-case
hallucination, KOL data-source labeling, and frontend unexpected errors.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = PROJECT_ROOT / "tests" / "reports"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"missing report: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def metric(report: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = report
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def add_gate(gates: list[dict[str, Any]], name: str, passed: bool, detail: str) -> None:
    gates.append({"name": name, "passed": bool(passed), "detail": detail})


def check_positive_rag(report: dict[str, Any], gates: list[dict[str, Any]]) -> None:
    summary = report.get("summary", {})
    timings = summary.get("timings_ms", {})
    health = report.get("health", {}).get("body", {})
    env = health.get("environment", {})

    add_gate(
        gates,
        "rag_health_healthy",
        health.get("overall") == "healthy",
        f"overall={health.get('overall')}",
    )
    add_gate(
        gates,
        "rag_vector_db_milvus",
        env.get("vector_db") == "milvus" and bool(env.get("milvus_configured")),
        f"vector_db={env.get('vector_db')} milvus_configured={env.get('milvus_configured')}",
    )
    add_gate(
        gates,
        "rag_quality_gate_passed",
        metric(report, "summary", "quality_gate", "passed") is True,
        f"quality_gate={summary.get('quality_gate')}",
    )
    add_gate(
        gates,
        "rag_no_fallback",
        float(summary.get("fallback_case_rate", 1.0)) == 0.0,
        f"fallback_case_rate={summary.get('fallback_case_rate')}",
    )
    add_gate(
        gates,
        "rag_has_retrieval_evidence",
        float(summary.get("retrieval_evidence_rate", 0.0)) >= 1.0,
        f"retrieval_evidence_rate={summary.get('retrieval_evidence_rate')}",
    )
    add_gate(
        gates,
        "rag_vector_or_hybrid_hit",
        float(summary.get("vector_or_hybrid_hit_rate", 0.0)) >= 0.8,
        f"vector_or_hybrid_hit_rate={summary.get('vector_or_hybrid_hit_rate')}",
    )
    add_gate(
        gates,
        "rag_search_fast_enough",
        float(timings.get("search_p95", 999999.0)) < 1500.0,
        f"search_p95={timings.get('search_p95')}ms",
    )
    add_gate(
        gates,
        "rag_chat_within_local_threshold",
        float(timings.get("chat_total_p95", 999999.0)) < 45000.0,
        f"chat_total_p95={timings.get('chat_total_p95')}ms",
    )


def check_negative_rag(report: dict[str, Any], gates: list[dict[str, Any]]) -> None:
    summary = report.get("summary", {})
    add_gate(
        gates,
        "rag_negative_cases_present",
        int(summary.get("negative_cases", 0)) > 0,
        f"negative_cases={summary.get('negative_cases')}",
    )
    add_gate(
        gates,
        "rag_negative_no_answer",
        float(summary.get("negative_no_answer_rate", 0.0)) >= 1.0,
        f"negative_no_answer_rate={summary.get('negative_no_answer_rate')}",
    )
    add_gate(
        gates,
        "rag_negative_no_hallucination",
        float(summary.get("negative_hallucination_case_rate", 1.0)) == 0.0,
        f"negative_hallucination_case_rate={summary.get('negative_hallucination_case_rate')}",
    )
    add_gate(
        gates,
        "rag_negative_no_fallback",
        float(summary.get("fallback_case_rate", 1.0)) == 0.0,
        f"fallback_case_rate={summary.get('fallback_case_rate')}",
    )


def check_kol(report: dict[str, Any], gates: list[dict[str, Any]]) -> None:
    quality_gate = report.get("quality_gate", {})
    source_summary = metric(report, "search", "data_source_summary", default={}) or {}
    forbidden_sources = {"mock", "demo", "seed", "sample"}
    expected_sources = {"public_web", "manual_upload", "cached_snapshot"}

    add_gate(
        gates,
        "kol_quality_gate_passed",
        quality_gate.get("passed") is True,
        f"quality_gate={quality_gate}",
    )
    add_gate(
        gates,
        "kol_imported_hits",
        int(metric(report, "search", "imported_hit_count", default=0) or 0) >= 3,
        f"imported_hit_count={metric(report, 'search', 'imported_hit_count')}",
    )
    add_gate(
        gates,
        "kol_sources_labeled",
        expected_sources.issubset(set(source_summary)),
        f"data_source_summary={source_summary}",
    )
    add_gate(
        gates,
        "kol_no_mock_sources",
        forbidden_sources.isdisjoint(set(source_summary)),
        f"data_source_summary={source_summary}",
    )


def check_frontend(report: dict[str, Any], gates: list[dict[str, Any]]) -> None:
    add_gate(
        gates,
        "frontend_quality_gate_passed",
        metric(report, "quality_gate", "passed") is True,
        f"quality_gate={report.get('quality_gate')}",
    )
    add_gate(
        gates,
        "frontend_no_unexpected_http_errors",
        not report.get("unexpected_http_errors"),
        f"unexpected_http_errors={report.get('unexpected_http_errors')}",
    )
    add_gate(
        gates,
        "frontend_no_unexpected_console_errors",
        not report.get("unexpected_console_errors"),
        f"unexpected_console_errors={report.get('unexpected_console_errors')}",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--positive-rag",
        default=str(REPORTS_DIR / "rag_live_quality_prelaunch_smoke.json"),
    )
    parser.add_argument(
        "--negative-rag",
        default=str(REPORTS_DIR / "rag_live_negative_prelaunch_smoke.json"),
    )
    parser.add_argument(
        "--kol",
        default=str(REPORTS_DIR / "kol_import_prelaunch_smoke.json"),
    )
    parser.add_argument(
        "--frontend",
        default=str(REPORTS_DIR / "frontend_docker_smoke.json"),
    )
    parser.add_argument("--skip-ui", action="store_true")
    parser.add_argument(
        "--out",
        default=str(REPORTS_DIR / "prelaunch_gate_summary.json"),
    )
    args = parser.parse_args()

    gates: list[dict[str, Any]] = []
    check_positive_rag(load_json(Path(args.positive_rag)), gates)
    check_negative_rag(load_json(Path(args.negative_rag)), gates)
    check_kol(load_json(Path(args.kol)), gates)
    if not args.skip_ui:
        check_frontend(load_json(Path(args.frontend)), gates)

    passed = all(item["passed"] for item in gates)
    summary = {
        "passed": passed,
        "total_gates": len(gates),
        "failed_gates": [item for item in gates if not item["passed"]],
        "gates": gates,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Prelaunch gate summary")
    print("=" * 80)
    print(f"passed: {passed}")
    print(f"total_gates: {len(gates)}")
    for item in gates:
        status = "PASS" if item["passed"] else "FAIL"
        print(f"{status} {item['name']}: {item['detail']}")
    print(f"JSON report: {out_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
