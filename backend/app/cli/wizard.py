"""
Role Assignment Wizard - 交互式角色划分向导
根据任务特征推荐单Agent vs 多Agent架构
"""
from app.core.logging import get_logger

logger = get_logger(__name__)


def run_wizard():
    """交互式角色划分向导"""
    print("=" * 60)
    print("AgentX 角色划分向导")
    print("=" * 60)
    print("\n本向导将帮助你根据任务特征选择最合适的Agent架构。\n")

    # Step 1: 收集任务信息
    questions = [
        ("任务领域", "你的任务涉及几个不同的业务领域？（如：营销、供应链、客服等）", "1"),
        ("工具数量", "总共需要多少个不同的工具/API？", "1-5"),
        ("任务复杂度", "任务复杂度评分（1-10）：1=简单查询，10=复杂跨领域任务", "5"),
        ("并发需求", "是否有可以同时执行的独立子任务？(y/n)", "n"),
        ("动态调度", "是否需要根据中间结果动态调整计划？(y/n)", "n"),
    ]

    answers = {}
    for label, question, default in questions:
        answer = input(f"[{label}] {question} [{default}]: ").strip()
        answers[label] = answer or default

    # Step 2: 分析推荐
    domains = answers["任务领域"]
    tools = answers["工具数量"]
    complexity = answers["任务复杂度"]
    can_parallel = answers["并发需求"].lower() == "y"
    needs_dynamic = answers["动态调度"].lower() == "y"

    try:
        complexity_num = int(complexity)
    except ValueError:
        complexity_num = 5

    try:
        domain_count = int(domains)
    except ValueError:
        domain_count = 1

    try:
        if "-" in tools:
            parts = tools.split("-")
            tool_count = int(parts[-1])
        else:
            tool_count = int(tools)
    except ValueError:
        tool_count = 5

    # Step 3: 输出推荐
    print("\n" + "=" * 60)
    print("推荐结果")
    print("=" * 60)

    if complexity_num <= 4 and tool_count <= 5 and domain_count <= 1:
        recommendation = "单Agent多工具"
        reason = "任务集中、工具少，结构简单，推荐初期使用单Agent多工具模式"
        architecture = """
┌─────────────────┐
│   Single Agent  │
│  (brand_bd etc) │
│                 │
│  ┌───┐ ┌───┐   │
│  │T1 │ │T2 │   │
│  └───┘ └───┘   │
│  ┌───┐ ┌───┐   │
│  │T3 │ │T4 │   │
│  └───┘ └───┘   │
└─────────────────┘"""
    elif domain_count >= 3 or complexity_num >= 7:
        recommendation = "多Agent分层（金字塔模式）"
        reason = "任务跨领域、复杂度高，推荐使用分层架构，总指挥调度组长Agent，组长调度组员"
        architecture = """
┌──────────────────────────┐
│    Orchestrator Agent    │ (总指挥)
└──────────┬───────────────┘
     ┌─────┼─────┐
┌────▼──┐ ┌▼────┐ ┌▼────┐
│Group A│ │Grp B│ │Grp C│ (组长)
└───┬───┘ └──┬──┘ └──┬──┘
  ┌─▼──┐  ┌─▼──┐  ┌─▼──┐
  │Agent│  │Agent│  │Agent│ (组员)
  └────┘  └────┘  └────┘"""
    elif can_parallel:
        recommendation = "多Agent并行（主从模式）"
        reason = "有独立可并行的子任务，推荐使用主从模式，Master统一调度，Worker并行执行"
        architecture = """
┌──────────────────┐
│  Master Agent    │
└──────┬───────────┘
  ┌────┼────┬────┐
┌▼──┐ ┌▼──┐┌▼──┐┌▼──┐
│W1 │ │W2 ││W3 ││W4 │
└───┘ └───┘└───┘└───┘"""
    else:
        recommendation = "多Agent串行（流水线模式）"
        reason = "任务有固定流程，前一步的输出是后一步的输入，推荐使用串行流水线"
        architecture = """
┌────┐   ┌────┐   ┌────┐   ┌────┐
│Agent│──▶│Agent│──▶│Agent│──▶│Agent│
│  A │   │  B │   │  C │   │  D │
└────┘   └────┘   └────┘   └────┘"""

    print(f"\n推荐架构: {recommendation}")
    print(f"原因: {reason}")
    print(f"\n架构示意图:\n{architecture}")

    print("\n" + "-" * 40)
    print("实施建议")
    print("-" * 40)

    if recommendation == "单Agent多工具":
        print("1. 使用脚手架创建Agent: python -m app.cli create-agent <name>")
        print("2. 在 tool_providers.yaml 中配置工具")
        print("3. 在 SKILL.md 中定义工作流程")
    elif recommendation == "多Agent分层（金字塔模式）":
        print("1. 先创建顶层Orchestrator Agent")
        print("2. 再创建各组组长Agent")
        print("3. 最后创建组员Agent")
        print("4. 使用 HierarchicalOrchestrator 进行层级编排")
        print("5. 注意层级深度不超过3层")
    elif recommendation == "多Agent并行（主从模式）":
        print("1. 创建Master Agent负责调度")
        print("2. 创建各Worker Agent处理具体任务")
        print("3. 使用 a2a_delegate_parallel 进行并行分派")
        print("4. 设置全局超时和部分失败容错策略")
    else:
        print("1. 创建流水线中的每个Agent")
        print("2. 定义Agent间的数据传递格式")
        print("3. 使用串行调用链进行编排")

    print("\n更多信息请参考 openspec/changes/agent-quality-upgrade/rollout-plan.md")