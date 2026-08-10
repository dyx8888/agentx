## ADDED Requirements

### Requirement: auth 模块不因配置缺失导致 import 崩溃
系统 SHALL 确保 `auth.py` 中 JWT 配置检查在函数调用时执行，而非在模块 import 时通过 `raise ValueError` 崩溃。

#### Scenario: 缺少 JWT_SECRET_KEY 时应用启动但给出明确日志
- **WHEN** JWT_SECRET_KEY 环境变量未设置
- **THEN** 应用正常启动，但在首次认证请求时返回明确的配置错误

### Requirement: 加密模块不因配置缺失导致 import 崩溃
系统 SHALL 确保 `encryption.py` 中 `initialize_encryption()` 的配置检查在 `ENVIRONMENT != "development"` 时延迟执行，而非在模块 import 时崩溃。

#### Scenario: 开发环境缺密钥可正常启动
- **WHEN** `ENVIRONMENT == "development"` 且 `ENCRYPTION_KEY` 未设置
- **THEN** 应用正常启动，使用开发模式的默认密钥

### Requirement: 反馈模块初始化延迟到首次请求
系统 SHALL 确保 `feedback_db = FeedbackDB()` 的实例化延迟到首次 API 请求时，而非在模块 import 时执行。

#### Scenario: 模块导入不因目录权限失败
- **WHEN** 反馈数据库目录无法创建
- **THEN** 应用正常启动，仅在首次反馈请求时返回错误

### Requirement: create_agent_sync 兼容运行中的事件循环
系统 SHALL 确保 `create_agent_sync()` 在已有运行事件循环的上下文中不抛出 `RuntimeError`。

#### Scenario: 在 FastAPI 请求中调用不崩溃
- **WHEN** 在 FastAPI 请求处理器中调用 `create_agent_sync()`
- **THEN** 函数正常执行，不抛出 `asyncio.run() cannot be called from a running event loop`