## ADDED Requirements

### Requirement: Audience definition in every agent's role description

Every agent's system prompt SHALL include an audience definition immediately following the role description, specifying the target audience and the expected communication style.

#### Scenario: brand_bd agent addresses brand managers
- **WHEN** the brand_bd agent generates output
- **THEN** its tone is professional, data-driven, and conclusion-first
- **AND** the output addresses the perspective of brand owners and operations managers

#### Scenario: customer_service agent addresses end consumers
- **WHEN** the customer_service agent generates output
- **THEN** its tone is friendly, natural, and problem-solving oriented
- **AND** the output addresses the perspective of end consumers

### Requirement: Few-shot examples in every agent's system prompt

Every agent's system prompt SHALL include at least one complete example demonstrating the full execution chain: user input → analysis → tool calls → formatted output.

#### Scenario: Agent produces output consistent with example format
- **WHEN** brand_bd processes a KOL screening request
- **THEN** its output follows the structure demonstrated in the Few-shot example (table format with ranking, metrics, recommendation rationale)
- **AND** risk notes and alternative suggestions are included when applicable

#### Scenario: Few-shot examples do not hallucinate data
- **WHEN** an agent references the Few-shot example format
- **THEN** all data in the actual output is derived from real tool calls or user-provided information
- **AND** example data (e.g., example KOL names) is NOT copied into actual responses

### Requirement: Chain-of-Thought instruction for Plan-and-Solve mode

The Plan-and-Solve working mode SHALL include an explicit "let's think step by step" instruction that requires the agent to output its analysis process before execution.

#### Scenario: Plan-and-Solve decomposition
- **WHEN** a user query triggers Plan-and-Solve mode (contains keywords like "计划", "策划", "方案")
- **THEN** the agent first outputs an analysis section identifying the core need and decomposing it into steps
- **AND** each step specifies what will be done and what result is expected
- **AND** execution proceeds step by step with intermediate results reported

### Requirement: Reflection mode with three-stage output

The Reflection working mode SHALL require a three-stage output format: Initial Result → Self-Review → Final Version, with explicit review criteria.

#### Scenario: Reflection self-review catches format error
- **WHEN** a user query triggers Reflection mode (contains keywords like "优化", "改进", "高质量")
- **THEN** the agent first generates a complete draft
- **THEN** the agent self-reviews against at least: completeness, factual accuracy, format compliance, and expression quality
- **THEN** the agent outputs the corrected final version with review notes
- **AND** if no issues found, the agent states "初稿审查通过" and re-outputs the draft

### Requirement: Unified output specification

A shared output specification SHALL define minimum formatting, quality, and behavioral standards applicable to all agent outputs.

#### Scenario: Structured data uses tables
- **WHEN** an agent presents multi-record data (e.g., KOL list, metrics report)
- **THEN** the agent uses aligned tables as primary presentation format

#### Scenario: Actionable recommendations
- **WHEN** an agent provides improvement suggestions
- **THEN** each suggestion includes a specific, executable action — not generic phrases like "建议优化"
- **AND** data-backed suggestions reference their source and time range

#### Scenario: Long-form response summary
- **WHEN** an agent response exceeds 500 characters
- **THEN** a 30-character-or-fewer summary is provided at the beginning before detailed content

### Requirement: Positive-first phrasing

Agent system prompts SHALL use affirmative "what to do" phrasing instead of negative "do not do" phrasing wherever the meaning is equivalent.

#### Scenario: Tool usage requirement rephrased
- **WHEN** the system prompt instructs about tool usage
- **THEN** "所有任务必须通过调用工具来完成" is used instead of "不能只回答问题"

#### Scenario: Personalized outreach requirement rephrased
- **WHEN** the system prompt instructs about outreach personalization
- **THEN** "邀约话术需针对每个达人的内容风格进行个性化定制" is used instead of "不能千篇一律"