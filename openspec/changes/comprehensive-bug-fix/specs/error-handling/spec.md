## ADDED Requirements

### Requirement: 异常处理中记录日志
系统 SHALL 在所有 `except` 块中至少记录日志，不得使用裸 `except: pass` 静默吞异常。

#### Scenario: 数据库操作异常被记录
- **WHEN** 数据库操作抛出异常
- **THEN** 异常信息被记录到日志，包含足够的上下文用于排查

#### Scenario: 前端 API 调用异常被记录
- **WHEN** 前端 API 调用失败
- **THEN** 错误信息被记录到控制台，用户看到友好的错误提示

### Requirement: 登录 API 检查响应状态码
系统 SHALL 在 `loginApi()` 中检查 HTTP 响应状态码，登录失败时返回明确的错误信息。

#### Scenario: 登录失败返回明确错误
- **WHEN** 后端返回 401 Unauthorized
- **THEN** 前端显示"用户名或密码错误"等明确提示，而非 JSON 解析错误

### Requirement: 输入过滤器的错误以友好格式返回
系统 SHALL 确保 `InputFilter.validate_message()` 抛出的异常以用户友好的格式（而非 Pydantic ValidationError 原始格式）返回给前端。

#### Scenario: 不支持的指令被拒绝
- **WHEN** 用户输入包含被过滤的指令
- **THEN** 返回 400 状态码和中文错误提示"请求包含不支持的指令"