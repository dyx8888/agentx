"""
Agent 输出规范模块
统一 8 个 Agent 的输出规范结构

文档依据: 4.docx - AI应用系统设计
  - 评测指标体系: Context Recall, Context Precision, Faithfulness, Answer Relevancy
  - 工具调用成功率: Tool Success Rate
  - 格式校验通过率: Format Valid Rate
  - 单次成功成本: Cost per Success
"""

PROMPT_VERSION = "2.0.0"
PROMPT_UPDATED = "2026-06-20"
PROMPT_CHANGELOG = """
v2.0.0 (2026-06-20): 新增评测指标体系，升级输出规范
v1.0.0 (2026-05-29): 初始版本，定义格式要求/质量标准/行为规范
"""

# ============ 评测指标体系 ============
# 文档依据: 4.docx - 评测体系
# 评测别只问"答案好不好"。更可控的做法是拆成链路指标。

EVALUATION_METRICS = {
    "context_recall": {
        "name": "Context Recall",
        "description": "正确证据有没有被召回",
        "formula": "recalled_relevant / total_relevant",
        "target": ">= 0.90",
    },
    "context_precision": {
        "name": "Context Precision",
        "description": "放进上下文的片段有多少是有用的",
        "formula": "relevant_in_context / total_in_context",
        "target": ">= 0.85",
    },
    "faithfulness": {
        "name": "Faithfulness",
        "description": "答案是否忠于给定证据",
        "formula": "faithful_claims / total_claims",
        "target": ">= 0.95",
    },
    "answer_relevancy": {
        "name": "Answer Relevancy",
        "description": "答案是否回应了用户问题",
        "formula": "relevant_sentences / total_sentences",
        "target": ">= 0.90",
    },
    "tool_success_rate": {
        "name": "Tool Success Rate",
        "description": "工具调用是否成功完成",
        "formula": "successful_tool_calls / total_tool_calls",
        "target": ">= 0.95",
    },
    "format_valid_rate": {
        "name": "Format Valid Rate",
        "description": "结构化输出是否能被解析",
        "formula": "valid_outputs / total_outputs",
        "target": ">= 0.98",
    },
    "cost_per_success": {
        "name": "Cost per Success",
        "description": "每次成功回答的平均成本",
        "formula": "total_cost / successful_answers",
        "target": "持续优化",
    },
    "ttft_p50": {
        "name": "TTFT P50",
        "description": "首字延迟中位数",
        "target": "< 800ms",
    },
    "ttft_p99": {
        "name": "TTFT P99",
        "description": "首字延迟99分位",
        "target": "< 3000ms",
    },
}

# ============ 输出规范 ============
OUTPUT_SPEC = """
## 📤 输出规范（适用于所有输出）

### 格式要求
- 结构化内容优先使用表格，保证对齐
- 自然语言段落之间用空行分隔
- 数字类数据附带单位和对比基准（如"环比+5%"）
- 条件判断或选项推荐使用分级列表

### 质量标准
- 每条建议有具体、可操作的行动指引，不说"建议优化"这种空话
- 涉及数据时必须标注来源和时间范围
- 不确定的内容标注置信度并给出核实建议，不编造
- 多方案对比时给出明确推荐和理由，不给模棱两可的并列选项

### 行为规范
- 每轮回答以结论或摘要开头，再展开细节
- 如果回答较长（超过500字），在最前面给出30字以内的摘要
- 用户追问时，如果前文已有相关信息，先回顾再展开新内容，避免重复
"""
