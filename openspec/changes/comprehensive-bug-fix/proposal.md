## Why

经过全面代码审查，项目存在 36 个代码缺陷，其中 7 个严重问题直接导致核心功能瘫痪（路由 404、SQL 执行失败、前后端无法通信），14 个高/中级别问题导致功能异常或数据错误。这些问题使当前系统无法正常启动和运行，必须立即修复。

## What Changes

- **BREAKING**: 统一路由前缀策略，消除 APIRouter 与 include_router 双重前缀导致的所有 API 404 错误
- **BREAKING**: 修复 SQL 占位符从 SQLite 风格（`?`）迁移到 PostgreSQL 风格（`%s`），覆盖 chat、feedback、evolution、model_gateway_extensions 四个模块
- 修复数据库连接泄漏问题，确保所有连接路径都正确关闭
- 统一前后端 API 前缀，确保前端请求能正确路由到后端
- 修复 ModelGateway 和 SessionStore 的线程安全问题（双重单例 + 无锁）
- 修复 Token 用量归属逻辑错误（company_id 取数使用错误 key 类型）
- 修复进化引擎 `interval_hours=0` 的 falsy 值覆盖问题
- 修复 `_get_agent_runtime` 不存在的模块导入
- 修复反馈数据库表结构与 INSERT 语句不匹配
- 修复进化日志表名与 ORM 模型不一致
- 修复前端 SSE 事件协议与后端返回格式不匹配
- 替换 Dashboard 和 Agent Chat 假数据为真实数据源
- 修复限流中间件端点路径与实际 API 不匹配
- 实现 token 刷新机制或调整前端 token 过期处理逻辑
- 修复多个静默异常吞并问题，添加适当的日志和错误处理
- 修复 `create_agent_sync` 中嵌套事件循环风险
- 修复 `MemoryAutoWriter` 直接访问私有属性的问题
- 修复公司上下文总线 O(n²) 去重逻辑
- 消除数据库 `__init__.py` 中 Pydantic 与 SQLAlchemy 模型命名冲突
- 修复加密模块和 auth 模块的模块级异常导致启动崩溃

## Capabilities

### New Capabilities
- `api-routing`: 统一 API 路由前缀管理，消除双重前缀问题
- `database-compatibility`: SQL 占位符与 PostgreSQL 兼容性修复
- `frontend-backend-alignment`: 前后端 API 通信协议对齐
- `thread-safety`: 核心服务单例的线程安全实现
- `data-integrity`: Token 用量、反馈、进化日志等数据正确性修复
- `evolution-engine-fix`: 进化引擎运行时错误修复
- `error-handling`: 异常处理与日志规范化
- `startup-stability`: 启动阶段稳定性修复

### Modified Capabilities
<!-- 无现有 spec 需要修改 -->

## Impact

- **后端 API 层**: chat.py, tasks.py, evolution.py, dashboard.py, agents.py, feedback.py, auth_router.py, main.py — 路由定义、SQL 执行、连接管理
- **后端服务层**: model_gateway.py, model_gateway_extensions.py, evolution.py, session_store.py — 单例模式、线程安全、数据持久化
- **数据库层**: database/__init__.py, database/core.py — 模型命名冲突、连接管理
- **RAG 层**: company_context_bus.py — 去重性能优化
- **中间件**: rate_limiter.py — 端点路径修正
- **前端**: api.js, AgentChat.jsx, Dashboard.jsx, AuthContext.jsx, login-form.jsx — API 通信、状态管理、SSE 协议
- **配置**: auth.py, encryption.py — 模块级异常处理