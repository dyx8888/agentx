## ADDED Requirements

### Requirement: API 路由前缀由 include_router 统一管理
系统 SHALL 在 `APIRouter()` 定义中不设置 `prefix` 参数，所有路由前缀由 `main.py` 中的 `app.include_router()` 统一指定。

#### Scenario: 聊天 API 路由可访问
- **WHEN** 客户端发送 POST 请求到 `/chat/`
- **THEN** 请求成功路由到 `chat.py` 的处理函数，返回 200 或业务响应

#### Scenario: 任务 API 路由可访问
- **WHEN** 客户端发送请求到 `/tasks/` 及其子路径
- **THEN** 请求成功路由到 `tasks.py` 的处理函数

#### Scenario: 进化引擎 API 路由可访问
- **WHEN** 客户端发送请求到 `/admin/evolution/` 及其子路径
- **THEN** 请求成功路由到 `evolution.py` 的处理函数

#### Scenario: 仪表盘 API 路由可访问
- **WHEN** 客户端发送请求到 `/dashboard/` 及其子路径
- **THEN** 请求成功路由到 `dashboard.py` 的处理函数

### Requirement: 多路径注册的 Router 不设 prefix
系统 SHALL 确保被多次 `include_router` 注册的 `APIRouter`（如 `agents_router`）不设置 `prefix`，避免路径冲突。

#### Scenario: Agent 管理路由同时存在于 /agents 和 /admin/agents
- **WHEN** 客户端分别请求 `/agents/` 和 `/admin/agents/`
- **THEN** 两个路径均能正确路由到对应的处理函数