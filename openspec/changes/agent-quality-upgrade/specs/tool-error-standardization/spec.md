## ADDED Requirements

### Requirement: 统一错误码
所有工具调用SHALL返回结构化ToolResult，包含标准错误码、错误消息、重试建议。

#### Scenario: 工具超时返回标准错误
- **WHEN** 工具调用超过timeout_ms配置的时间
- **THEN** 系统返回 `ToolResult.error(ErrorCode.TOOL_TIMEOUT, ...)` 包含建议 "请重试或简化查询参数"

#### Scenario: 工具成功返回标准结果
- **WHEN** 工具调用正常完成
- **THEN** 系统返回 `ToolResult.ok(data=result, message="Execution completed")`

### Requirement: LLM可读的错误消息
错误消息SHALL使用自然语言描述，包含失败原因和具体操作建议，使LLM能理解并自动重试或降级。

#### Scenario: 连接错误消息
- **WHEN** 工具调用因网络问题失败
- **THEN** 错误消息包含 "连接失败: [具体原因]。建议: 切换到备用数据源或稍后重试"

### Requirement: 审批门集成
需要审批的工具（metadata.requires_approval=true）SHALL在调用前返回 `ToolResult.pending_approval()`，等待人工确认。

#### Scenario: 高风险操作需要审批
- **WHEN** Agent尝试调用标记为requires_approval的工具
- **THEN** 系统返回pending_approval状态，包含提议的参数，等待外部确认

### Requirement: 工具Schema五原则校验
ToolLoader SHALL在加载工具时对每个工具的Schema进行五原则评分，低于60分的工具自动调用LLM增强描述。

#### Scenario: 工具Schema评分达标
- **WHEN** 工具Schema五原则评分 >= 60分
- **THEN** 系统直接注册该工具，日志记录评分详情

#### Scenario: 工具Schema评分不达标
- **WHEN** 工具Schema五原则评分 < 60分
- **THEN** 系统调用LLM增强工具描述，记录增强前后对比，然后注册增强后的工具

#### Scenario: 副作用标注缺失
- **WHEN** 工具为写操作但未标注 `side_effect: true`
- **THEN** 系统在Schema校验中扣分，并建议添加副作用标注

### Requirement: MCP资源暴露
MCP Server SHALL支持暴露资源(resources)和数据提示(prompts)，不仅限于工具(tools)。

#### Scenario: 资源列表暴露
- **WHEN** Agent需要获取知识库文档内容
- **THEN** MCP Server通过 `list_resources()` 返回可用资源列表，Agent通过 `read_resource(uri)` 获取内容

#### Scenario: 数据提示暴露
- **WHEN** Agent需要预定义的提示词模板
- **THEN** MCP Server通过 `list_prompts()` 返回可用提示词模板列表

### Requirement: MCP Server健康检查
ToolLoader SHALL在启动时验证所有MCP Server连接状态，不健康时降级处理。

#### Scenario: MCP Server连接正常
- **WHEN** ToolLoader启动时检查MCP Server
- **THEN** 所有Server状态为healthy，正常注册工具

#### Scenario: MCP Server连接失败
- **WHEN** MCP Server无法连接（超时或进程退出）
- **THEN** 系统记录WARNING日志，跳过该Server的工具注册，标注该Server状态为unhealthy

### Requirement: A2A任务状态追踪
A2A委托任务SHALL支持状态轮询，主Agent可查询子Agent任务执行状态。

#### Scenario: 查询任务状态
- **WHEN** 主Agent调用 `a2a_task_status(task_id)`
- **THEN** 系统返回 `{status: "RUNNING", progress: "步骤2/5", started_at: "..."}`

#### Scenario: 任务状态流转
- **WHEN** 子Agent完成或失败
- **THEN** 任务状态从RUNNING变为COMPLETED或FAILED，主Agent轮询获取最终结果

### Requirement: Skills组合封装
Skill定义SHALL包含工具链、提示词模板和知识库关联，实现完整的能力封装。

#### Scenario: Skill完整定义
- **WHEN** 加载一个品牌分析Skill
- **THEN** Skill定义包含 `tools: ["search_kols", "analyze_trend"]`, `prompt_template: "你是品牌分析专家..."`, `knowledge_base_ids: ["kol_db", "brand_db"]`

### Requirement: 四级降级策略
工具调用失败时，系统SHALL按四级降级策略依次尝试：缓存数据 → 备用数据源 → 跳过非关键步骤 → 转人工工单。

#### Scenario: 使用缓存数据降级
- **WHEN** 工具调用因网络超时失败，且存在有效缓存数据
- **THEN** 系统返回缓存数据，标注 `source: "cache"`, `cached_at: "..."`, `warning: "数据可能延迟"`

#### Scenario: 切换备用数据源
- **WHEN** 主数据源不可用，且配置了 `fallback_url`
- **THEN** 系统自动切换到备用数据源，记录降级日志

#### Scenario: 跳过非关键步骤
- **WHEN** 工具失败且标记为 `critical: false`
- **THEN** 系统跳过该步骤，继续执行后续任务，告知用户"部分结果非完整"

#### Scenario: 转人工工单
- **WHEN** 关键步骤(`critical: true`)的所有降级策略均失败
- **THEN** 系统生成人工工单，暂停Agent，通知用户"已转接人工处理，工单号：XXX"