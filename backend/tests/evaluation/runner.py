"""
评测运行器
加载 YAML 用例 → 调用 Agent → 评判 → JSON 报告 + 终端摘要
"""

import json
import os
import sys
from datetime import datetime

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.evaluation.judge import EvalResult, LLMJudge


def load_test_cases(yaml_path: str) -> list[dict]:
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("test_cases", [])


async def run_single_test(test_case: dict, agent, judge: LLMJudge) -> EvalResult:
    from langchain_core.messages import HumanMessage

    test_id = test_case["id"]
    test_name = test_case["name"]
    user_input = test_case["input"]
    expected = test_case.get("expected_behaviors", [])
    unacceptable = test_case.get("unacceptable_behaviors", [])

    try:
        result = await agent.ainvoke({"messages": [HumanMessage(content=user_input)]})
        messages = result.get("messages", [])
        agent_output = messages[-1].content if messages else ""
    except Exception as e:
        return EvalResult(
            test_id=test_id,
            test_name=test_name,
            task_completion=0,
            format_quality=0,
            safety_compliance=0,
            actionability=0,
            overall_score=0,
            is_unacceptable=True,
            unacceptable_reason=f"Agent 调用失败: {str(e)}",
        )

    return judge.evaluate(
        test_id=test_id,
        test_name=test_name,
        user_input=user_input,
        agent_output=agent_output,
        expected_behaviors=expected,
        unacceptable_behaviors=unacceptable,
    )


async def run_evaluation(yaml_path: str = None, agent_name: str = "brand_bd",
                          output_path: str = None):
    if yaml_path is None:
        yaml_path = os.path.join(os.path.dirname(__file__), "cases", "brand_bd.yaml")

    if output_path is None:
        output_path = os.path.join(
            os.path.dirname(__file__),
            f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )

    test_cases = load_test_cases(yaml_path)
    if not test_cases:
        print("未加载到任何测试用例")
        return

    judge = LLMJudge()

    try:
        from app.agent import create_agent
        from app.services.model_gateway import ModelGateway
        from app.agent import AgentMode
        import importlib

        model_gateway = ModelGateway()
        llm = model_gateway.get_llm()

        agent_mod = importlib.import_module(f"app.agents.{agent_name}")
        system_prompt = agent_mod.get_system_prompt()

        agent = await create_agent(
            llm=llm,
            system_prompt=system_prompt,
            mode=AgentMode.REACT,
        )
    except Exception as e:
        print(f"Agent 初始化失败: {e}")
        return

    results: list[EvalResult] = []
    for tc in test_cases:
        print(f"\n{'='*60}")
        print(f"运行: [{tc['id']}] {tc['name']}")
        print(f"分类: {tc.get('category', 'N/A')}")
        print(f"输入: {tc['input'][:80]}...")
        print(f"{'='*60}")

        result = await run_single_test(tc, agent, judge)
        results.append(result)

        status = "[FAIL] 不可接受" if result.is_unacceptable else "[PASS] 通过"
        print(f"  任务完成度: {result.task_completion}/10")
        print(f"  格式规范度: {result.format_quality}/10")
        print(f"  安全合规度: {result.safety_compliance}/10")
        print(f"  可执行性:   {result.actionability}/10")
        print(f"  总评:       {result.overall_score}/10  [{status}]")

        if result.strengths:
            print(f"  优点: {', '.join(result.strengths[:3])}")
        if result.weaknesses:
            print(f"  不足: {', '.join(result.weaknesses[:3])}")
        if result.is_unacceptable:
            print(f"  原因: {result.unacceptable_reason}")

    report = _build_report(results)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    _print_summary(report)
    print(f"\n报告已保存至: {output_path}")


def _build_report(results: list[EvalResult]) -> dict:
    total = len(results)
    passed = sum(1 for r in results if not r.is_unacceptable)
    failed = total - passed
    avg_score = sum(r.overall_score for r in results) / total if total > 0 else 0

    return {
        "timestamp": datetime.now().isoformat(),
        "total_cases": total,
        "passed": passed,
        "failed": failed,
        "average_overall_score": round(avg_score, 2),
        "details": [
            {
                "test_id": r.test_id,
                "test_name": r.test_name,
                "task_completion": r.task_completion,
                "format_quality": r.format_quality,
                "safety_compliance": r.safety_compliance,
                "actionability": r.actionability,
                "overall_score": r.overall_score,
                "is_unacceptable": r.is_unacceptable,
                "unacceptable_reason": r.unacceptable_reason,
                "strengths": r.strengths,
                "weaknesses": r.weaknesses,
                "suggestions": r.suggestions,
            }
            for r in results
        ],
    }


def _print_summary(report: dict):
    print(f"\n{'='*60}")
    print("评测总结")
    print(f"{'='*60}")
    print(f"  总用例数: {report['total_cases']}")
    print(f"  通过:     {report['passed']}")
    print(f"  失败:     {report['failed']}")
    print(f"  平均分:   {report['average_overall_score']}/10")
    print(f"{'='*60}")


if __name__ == "__main__":
    import asyncio
    agent_name = sys.argv[1] if len(sys.argv) > 1 else "brand_bd"
    yaml_path = sys.argv[2] if len(sys.argv) > 2 else None
    asyncio.run(run_evaluation(yaml_path=yaml_path, agent_name=agent_name))
