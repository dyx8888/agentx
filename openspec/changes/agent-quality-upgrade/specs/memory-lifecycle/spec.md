## ADDED Requirements

### Requirement: 短期记忆智能截断
SessionStore SHALL在截断历史消息时，基于token数量而非消息条数进行判断，默认阈值为模型上下文窗口的80%。

#### Scenario: Token超过阈值触发截断
- **WHEN** 会话历史累计token数超过阈值（默认 80% × 模型context_window）
- **THEN** 系统保留最近N条消息使token数降至阈值以下，并生成早期消息的摘要注入

#### Scenario: 摘要压缩保留关键信息
- **WHEN** 截断发生时
- **THEN** 系统调用LLM将被截断的消息压缩为摘要（不超过200 tokens），注入到保留消息之前

### Requirement: 长期记忆LRU淘汰
ThreeLayerMemoryManager的语义记忆存储SHALL实现LRU淘汰策略，当存储量超过阈值时，自动淘汰最久未访问的记忆条目。

#### Scenario: 存储量超限触发淘汰
- **WHEN** 语义记忆存储条目数超过MAX_SEMANTIC_MEMORIES（默认10000）
- **THEN** 系统按LRU策略淘汰最久未访问的条目，直到降至阈值的80%

#### Scenario: 高置信度记忆保护
- **WHEN** LRU淘汰时遇到confidence >= 0.9的记忆条目
- **THEN** 系统跳过该条目，优先淘汰低置信度条目

### Requirement: 工作记忆结构化
AgentRuntime SHALL使用 `WorkingMemory` 数据类统一管理运行时记忆，包含：`task_context`、`intermediate_results`、`tool_call_history`、`decision_log`。

#### Scenario: 工作记忆初始化
- **WHEN** AgentRuntime开始新任务
- **THEN** 系统创建新的WorkingMemory实例，关联到当前thread_id

#### Scenario: 工作记忆用于checkpoint
- **WHEN** 系统保存checkpoint
- **THEN** WorkingMemory的完整状态被序列化到checkpoint中

### Requirement: 睡眠巩固混合触发
睡眠巩固SHALL支持两种触发方式：时间触发（每N小时）和数据量触发（情景记忆超过阈值），以先到者为准。

#### Scenario: 时间触发
- **WHEN** 距离上次巩固超过 CONSOLIDATION_INTERVAL_HOURS（默认6小时）
- **THEN** 系统自动触发睡眠巩固流程

#### Scenario: 数据量触发
- **WHEN** 情景记忆条目数超过 CONSOLIDATION_THRESHOLD（默认50条）
- **THEN** 系统自动触发睡眠巩固流程

#### Scenario: 去重保护
- **WHEN** 睡眠巩固正在执行中
- **THEN** 新的触发请求被忽略，避免并发巩固