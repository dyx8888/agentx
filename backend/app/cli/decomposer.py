"""
Task Decomposer - 任务分解工具
调用LLM自动分解任务为依赖树，生成Mermaid格式的依赖图
"""
import json
import re

from app.core.logging import get_logger

logger = get_logger(__name__)

DECOMPOSE_SYSTEM_PROMPT = """你是一个任务分解专家。请将用户的任务描述分解为子任务依赖树。

## 分解原则
1. **单一职责**：每个子任务只做一件事
2. **输入输出明确**：每个子任务有明确的输入和输出
3. **成功标准**：每个子任务有可验证的完成标准
4. **串并行区分**：标注哪些子任务可以并行执行，哪些必须串行

## 输出格式
返回JSON格式：
{
  "task_name": "任务名称",
  "task_summary": "任务概述",
  "subtasks": [
    {
      "id": "1",
      "name": "子任务名称",
      "description": "具体描述",
      "input": "需要的输入",
      "output": "预期的输出",
      "success_criteria": "完成标准",
      "can_parallel": true/false,
      "depends_on": [],
      "estimated_agent": "建议的Agent类型"
    }
  ],
  "execution_order": ["1", "2", "3"],
  "parallel_groups": [["1", "2"], ["3"]],
  "mermaid_diagram": "graph TD\\n  A[Start] --> B[Step1]\\n  ..."
}

## 串并行区分规则
- 如果子任务B需要子任务A的输出，则B依赖A（串行）
- 如果子任务之间没有数据依赖，则可以并行
- 标注 depends_on 字段表示依赖关系
"""


def decompose_task(task_description: str) -> str:
    """
    分解任务为子任务依赖树

    Args:
        task_description: 任务描述

    Returns:
        格式化的任务分解结果
    """
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from app.services.model_gateway import get_global_model_gateway

        model_gateway = get_global_model_gateway()
        llm = model_gateway.get_llm()

        response = llm.invoke([
            SystemMessage(content=DECOMPOSE_SYSTEM_PROMPT),
            HumanMessage(content=task_description),
        ])

        content = response.content if hasattr(response, 'content') else str(response)

        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            data = json.loads(json_match.group(0))
            return _format_decomposition(data, task_description)
        else:
            return f"Task decomposition failed. Raw response:\n{content}"

    except Exception as e:
        logger.error("task_decomposition_error", error=str(e))
        return f"Task decomposition error: {str(e)}"


def _format_decomposition(data: dict, original_task: str) -> str:
    """格式化任务分解结果"""
    lines = [
        "=" * 60,
        "任务分解结果",
        "=" * 60,
        f"\n原始任务: {original_task}",
        f"任务名称: {data.get('task_name', 'N/A')}",
        f"任务概述: {data.get('task_summary', 'N/A')}",
        "\n" + "-" * 40,
        "子任务列表",
        "-" * 40,
    ]

    for subtask in data.get("subtasks", []):
        can_parallel = "并行" if subtask.get("can_parallel") else "串行"
        depends = ", ".join(subtask.get("depends_on", [])) or "无"
        lines.append(f"\n[{subtask.get('id')}] {subtask.get('name')} ({can_parallel})")
        lines.append(f"  描述: {subtask.get('description', '')}")
        lines.append(f"  输入: {subtask.get('input', '')}")
        lines.append(f"  输出: {subtask.get('output', '')}")
        lines.append(f"  成功标准: {subtask.get('success_criteria', '')}")
        lines.append(f"  依赖: {depends}")
        lines.append(f"  建议Agent: {subtask.get('estimated_agent', '通用')}")

    lines.append("\n" + "-" * 40)
    lines.append("执行顺序")
    lines.append("-" * 40)
    lines.append(f"顺序: {' → '.join(data.get('execution_order', []))}")

    parallel_groups = data.get("parallel_groups", [])
    if parallel_groups:
        lines.append(f"\n并行组: {' | '.join(' + '.join(g) for g in parallel_groups)}")

    lines.append("\n" + "-" * 40)
    lines.append("依赖图 (Mermaid)")
    lines.append("-" * 40)
    lines.append(f"\n```mermaid\n{data.get('mermaid_diagram', 'graph TD\\n  A[Start] --> B[End]')}\n```")

    return "\n".join(lines)