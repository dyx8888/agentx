## ADDED Requirements

### Requirement: 并行任务分派
系统SHALL支持通过 `a2a_delegate_parallel` 工具同时向多个Agent分派独立任务，并汇总结果。

#### Scenario: 并行分派多个独立任务
- **WHEN** 用户请求同时需要品牌分析和内容创作
- **THEN** 系统并行调用brand_bd Agent和cc Agent，等待两者完成后汇总

#### Scenario: 部分任务失败不影响其他
- **WHEN** 并行分派的3个任务中1个失败
- **THEN** 系统仍返回2个成功任务的结果，并在汇总中标注失败任务

### Requirement: 超时协调
并行任务执行SHALL有全局超时时间（默认60秒），超时后返回已完成的结果并标注未完成的任务。

#### Scenario: 并行任务超时
- **WHEN** 并行任务中某个Agent超过60秒未返回
- **THEN** 系统终止等待，返回已完成任务的结果，标注超时任务

### Requirement: Agent Card标准化
A2AAdapter SHALL生成符合Google A2A规范的Agent Card，包含name、description、capabilities、url、version字段。

#### Scenario: Agent Card格式
- **WHEN** 调用 `get_agent_card("cc")`
- **THEN** 返回的card包含 `protocol: "a2a"`, `version: "1.0.0"`, `capabilities: [...]` 等标准字段

### Requirement: 分层Agent架构（金字塔模式）
系统SHALL支持多层嵌套的Agent协作架构，总指挥→组长→组员，最大3层。

#### Scenario: 三层架构任务分解
- **WHEN** 用户请求一个超大规模任务（如"为公司制定全年度营销计划"）
- **THEN** 第1层总指挥Agent分解为多个领域目标（品牌、内容、渠道），第2层组长Agent分配到具体Agent，第3层组员Agent执行详细任务

#### Scenario: 层级深度限制
- **WHEN** 任务分解尝试超过3层
- **THEN** 系统在第3层自动合并子任务，拒绝进一步分解，日志记录"max_depth_reached"

#### Scenario: 层级间结构化通信
- **WHEN** 第3层组员完成子任务
- **THEN** 向上汇报结构化摘要 `{task_id, status, result_summary, confidence, issues}`，而非仅自然语言

### Requirement: 串行流水线上下文传递
串行Agent流水线中，前一个Agent的输出SHALL以结构化格式传递给下一个Agent。

#### Scenario: 流水线上下文传递
- **WHEN** Agent A完成内容创作，Agent B需要翻译
- **THEN** Agent A的输出以 `{content, format, tone, target_audience}` 结构化格式传递给Agent B，而非仅raw文本

#### Scenario: 流水线进度追踪
- **WHEN** 串行流水线执行中
- **THEN** 系统记录每个Agent的实时状态：`[{agent: "A", status: "COMPLETED"}, {agent: "B", status: "RUNNING"}, {agent: "C", status: "PENDING"}]`

### Requirement: 协作模式自动选择
系统SHALL基于任务特征自动推荐协作模式。

#### Scenario: 独立任务推荐并行模式
- **WHEN** 用户请求包含3个彼此独立的子任务（如"查天气、查股票、查新闻"）
- **THEN** 系统自动选择并行模式，同时分派3个Agent

#### Scenario: 固定接力推荐串行模式
- **WHEN** 用户请求包含明确的工序依赖（如"写→翻译→校对"）
- **THEN** 系统自动选择串行流水线模式

#### Scenario: 动态调度推荐主从模式
- **WHEN** 用户请求需要动态选择专家（如"帮我处理这个客户问题"）
- **THEN** 系统自动选择主从模式，由Orchestrator动态调度专家Agent