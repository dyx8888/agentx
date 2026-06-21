## ADDED Requirements

### Requirement: 统一感知管道
系统SHALL提供 `PerceptionPipeline` 类，按序编排 InputFilter → QueryRewriter → IntentExtractor → RagRetriever → ToolResultParser 五个感知阶段。

#### Scenario: 正常感知流程
- **WHEN** 用户消息进入感知管道
- **THEN** 系统依次执行安全过滤、Query改写、意图提炼、知识检索、上下文聚合，最终输出结构化 `PerceptionContext`

#### Scenario: 某阶段失败不影响后续
- **WHEN** RAG检索阶段因连接问题失败
- **THEN** 系统记录WARNING日志，跳过该阶段，继续后续处理，RAG字段标记为空

### Requirement: Query改写
系统SHALL在用户消息进入Agent前，通过LLM进行Query改写，包括：补全省略信息、纠正拼写错误、将口语化表达转为结构化查询。

#### Scenario: 补全上下文
- **WHEN** 用户输入 "上次那个达人表现怎么样"
- **THEN** QueryRewriter查询短期记忆，将 "上次那个达人" 改写为具体达人名称

#### Scenario: 口语化转结构化
- **WHEN** 用户输入 "帮我看看最近抖音上美妆类的数据咋样"
- **THEN** QueryRewriter输出结构化查询：`{platform: "抖音", category: "美妆", metric: "performance", period: "最近7天"}`

### Requirement: 意图提炼
系统SHALL在Query改写后，通过LLM提炼用户意图，输出结构化意图对象，包含：意图类型（如content_creation、data_analysis、task_delegation）、优先级、紧急程度。

#### Scenario: 意图分类
- **WHEN** 用户输入 "帮我写一个抖音短视频脚本"
- **THEN** IntentExtractor输出 `{type: "content_creation", platform: "抖音", format: "短视频脚本", priority: "normal"}`

### Requirement: 感知结果结构化
`PerceptionContext` SHALL包含以下结构化字段：`original_query`、`rewritten_query`、`intent`、`rag_context`（含来源和置信度）、`safety_check`（通过/拒绝/可疑）、`tool_results_summary`。

#### Scenario: 完整感知上下文
- **WHEN** 感知管道完成所有阶段
- **THEN** 输出包含所有字段的PerceptionContext，每个RAG结果附带source_file和score