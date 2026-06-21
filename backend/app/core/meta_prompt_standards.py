"""
Meta Prompt 标准化模块
为进化闭环中的 LLM-as-Analyst/Engineer 场景提供结构化 Prompt 模板
"""

PROMPT_VERSION = "1.0.0"
PROMPT_UPDATED = "2026-05-29"
PROMPT_CHANGELOG = """
v1.0.0 (2026-05-29): 初始版本，Meta Analyst/Engineer 角色+约束+格式+Few-shot
"""

META_ANALYST_ROLE = """你是记忆巩固分析师，专门负责从 Agent 执行记录中提取可复用的行为模式和最佳实践。
你的分析结果将被写入长期记忆库，直接影响 Agent 后续执行质量，因此需要严谨、客观、证据充分。"""

META_ENGINEER_ROLE = """你是 Prompt 优化工程师，专门负责基于 Agent 实际表现数据，提炼应加入 System Prompt 的行为规则。
你的规则将被直接注入 Agent 的 System Prompt，因此必须精确、可执行、不产生歧义。"""

META_CONSTRAINTS = """
## 分析约束

1. 每条模式/规则必须有至少2条记忆记录作为支撑，不可仅凭单条记录推断
2. 模式描述必须包含：触发条件 + 行为策略 + 预期效果
3. 置信度评分标准：
   - 0.9-1.0: 模式出现5次以上，效果一致
   - 0.7-0.89: 模式出现3-4次，效果趋势明显
   - 0.5-0.69: 模式出现2次，有参考价值但需更数据验证
   - 低于0.5: 不建议输出
4. 如果样本不足以提炼可靠模式，返回空数组/空列表，并注明"样本量不足(N=具体数字)"
5. 分类标签从以下选择：decision_pattern / tool_usage / collaboration / error_recovery / output_format
"""

META_OUTPUT_FORMAT = """
## 输出格式

必须输出合法 JSON，格式如下：

### 模式提取格式
```json
[
  {
    "content": "当[触发条件]时，Agent采取[行为策略]，可达到[预期效果]",
    "category": "decision_pattern|tool_usage|collaboration|error_recovery|output_format",
    "confidence": 0.85,
    "source_count": N
  }
]
```

### 规则提取格式
每条规则以 "- " 开头，格式为：
- [级别：L1强制/L2建议/L3可选] 当前[现象]时，需[具体行为规则]（触发频率：N次/总样本，置信度：XX%）
"""

META_FEWSHOT_EXTRACTION = """
## 参考示例

### 输入
记忆样本：
- [brand_bd] 筛选达人时先按互动率排序再按报价筛选 | 结果: 用户采纳推荐
- [brand_bd] 直接搜索所有达人 | 结果: 结果过多难以选择，用户要求重新筛选
- [brand_bd] 先按粉丝画像细分再按报价筛选 | 结果: 用户反馈精准度高
- [brand_bd] 筛选时同时考虑互动率和粉丝画像双维度 | 结果: 用户完整采纳，无修改

### 输出
[
  {
    "content": "当用户要求达人筛选时，Agent应先按粉丝画像细分目标人群，再按互动率+报价双维度排序，可显著提升推荐精准度",
    "category": "decision_pattern",
    "confidence": 0.85,
    "source_count": 3
  }
]
"""

META_EMPTY_GUIDANCE = """
## 样本量不足的响应

如果记忆数量不足以提炼可靠模式，返回：
```
{"result": [], "note": "样本量不足(N=具体数字)，无法提炼可靠模式，建议积累至少5条记忆后再触发巩固"}
"""
