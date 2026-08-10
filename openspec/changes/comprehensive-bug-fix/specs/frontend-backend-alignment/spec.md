## ADDED Requirements

### Requirement: 后端 API 统一使用 /api 前缀
系统 SHALL 在 `main.py` 中为所有业务路由添加 `/api` 前缀，前端 `API_BASE` 保持 `/api`。

#### Scenario: 前端认证请求正确路由
- **WHEN** 前端发送 POST 请求到 `/api/auth/token`
- **THEN** 后端 `auth_router` 处理该请求

#### Scenario: 前端聊天请求正确路由
- **WHEN** 前端发送 POST 请求到 `/api/chat/`
- **THEN** 后端 `chat_router` 处理该请求

#### Scenario: 前端仪表盘请求正确路由
- **WHEN** 前端发送 GET 请求到 `/api/dashboard/overview`
- **THEN** 后端 `dashboard_router` 处理该请求

### Requirement: 限流中间件端点路径与 API 路由一致
系统 SHALL 确保 `rate_limiter.py` 中 `LLM_ENDPOINTS` 集合中的路径与实际 API 路由匹配。

#### Scenario: LLM 端点被限流中间件正确拦截
- **WHEN** 客户端发送请求到 `/api/chat/stream`
- **THEN** 限流中间件正确计数并执行限流策略

### Requirement: 前端 SSE 事件类型与后端一致
系统 SHALL 确保前端 `AgentChat.jsx` 处理的 SSE 事件类型（`tool_call`, `tool_output`, `text`, `review_required`, `done`）与后端 `chat.py` 返回的事件类型完全匹配。

#### Scenario: 工具调用事件正确显示
- **WHEN** 后端返回 `type: "tool_call"` 事件
- **THEN** 前端正确渲染工具调用面板

#### Scenario: 工具执行结果正确显示
- **WHEN** 后端返回 `type: "tool_result"` 事件
- **THEN** 前端正确渲染工具输出内容

#### Scenario: 思考过程事件被处理
- **WHEN** 后端返回 `type: "thinking"` 事件
- **THEN** 前端正确处理该事件（如显示折叠的思考过程）