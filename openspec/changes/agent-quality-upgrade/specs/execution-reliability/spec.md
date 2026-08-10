## ADDED Requirements

### Requirement: 工具调用超时控制
系统SHALL在executor_node中为每次工具调用设置超时，超时时间从tool_providers.yaml的timeout_ms配置读取，默认30秒。

#### Scenario: 工具在超时内完成
- **WHEN** 工具调用在timeout_ms内正常返回
- **THEN** 系统正常处理返回结果

#### Scenario: 工具超时
- **WHEN** 工具调用超过timeout_ms未返回
- **THEN** 系统返回 `ToolResult.error(ErrorCode.TOOL_TIMEOUT, "Tool execution timed out after {timeout_ms}ms", suggestion="Try reducing the scope of your request or retry later.")`

### Requirement: 自动重试机制
工具调用失败时，系统SHALL自动重试，最多3次，使用指数退避策略（1s/2s/4s）。

#### Scenario: 首次失败后重试成功
- **WHEN** 工具调用第1次失败（CONNECTION_ERROR），第2次重试成功
- **THEN** 系统返回第2次成功的结果，日志记录 "tool_retry_success, attempt=2"

#### Scenario: 全部重试失败
- **WHEN** 工具调用连续3次失败
- **THEN** 系统返回最后一次失败的错误信息，日志记录 "tool_all_retries_failed"

#### Scenario: 不可重试错误不重试
- **WHEN** 工具失败原因为 INVALID_PARAMS 或 PERMISSION_DENIED
- **THEN** 系统不重试，直接返回错误

### Requirement: 工具调用追踪
系统SHALL在每次工具调用时记录：工具名称、调用参数、开始时间、结束时间、耗时（ms）、是否成功、错误信息（如有）。

#### Scenario: 成功调用追踪
- **WHEN** 工具调用成功完成
- **THEN** 系统记录tool_call trace，包含 `tool_name`、`args_preview`（参数摘要）、`duration_ms`、`status: "success"`

#### Scenario: 失败调用追踪
- **WHEN** 工具调用失败
- **THEN** 系统记录tool_call trace，包含 `tool_name`、`args_preview`、`duration_ms`、`status: "error"`、`error_code`、`error_message`

### Requirement: 不可重试错误码定义
系统SHALL定义不可重试的错误码列表：INVALID_PARAMS、PERMISSION_DENIED、MAX_CALLS_EXCEEDED。这些错误码不应触发自动重试。

#### Scenario: 参数错误不重试
- **WHEN** 工具调用因 INVALID_PARAMS 失败
- **THEN** 系统不重试，直接返回错误并建议 "Check your parameters and try again with corrected values."