## Context

Agent电商项目经过全面代码审查，发现 36 个跨越多层的代码缺陷。当前系统处于开发阶段，后端使用 FastAPI + PostgreSQL，前端使用 React + Ant Design。问题涉及路由层、服务层、数据库层、中间件层和前端通信层的系统性缺陷，修复需要协调多个模块的变更。

## Goals / Non-Goals

**Goals:**
- 消除所有导致运行时崩溃的严重缺陷（路由 404、SQL 语法错误、连接泄漏）
- 修复前后端通信协议，确保 API 调用正常
- 解决核心服务的线程安全问题
- 修复数据完整性问题（Token 用量、反馈、进化日志）
- 修复进化引擎运行时错误
- 替换假数据为真实数据源或明确标注为占位
- 规范化异常处理，添加适当的日志

**Non-Goals:**
- 不引入新的功能特性
- 不重构现有架构模式（如单例模式改为依赖注入的完整重构）
- 不修改数据库 Schema 设计
- 不优化性能（除 O(n²) 去重外）

## Decisions

### 1. 路由前缀统一策略

**决策**: 将所有 `prefix` 从 `APIRouter()` 定义中移除，仅保留在 `app.include_router()` 中。

**理由**: 单一来源原则（Single Source of Truth）。当前 `APIRouter(prefix="/chat")` + `include_router(prefix="/chat")` 导致双重前缀。移除 APIRouter 中的 prefix 后，所有路由路径由 main.py 中的 include_router 统一管理，便于维护和审计。

**替代方案**: 保留 APIRouter 中的 prefix，移除 include_router 中的 prefix。此方案的问题是 `agents_router` 被注册到两个路径（`/agents` 和 `/admin/agents`），必须在 APIRouter 中不设 prefix 才能实现。因此选择方案一。

**涉及文件**:
- `chat.py`: 移除 `prefix="/chat"`
- `tasks.py`: 移除 `prefix="/tasks"`
- `evolution.py`: 移除 `prefix="/admin/evolution"`
- `dashboard.py`: 移除 `prefix="/api/v1/dashboard"`
- `agents.py`: 移除 `prefix="/admin/agents"`
- `main.py`: 确保所有 include_router 的 prefix 正确

### 2. SQL 占位符迁移

**决策**: 将所有原始 SQL 字符串中的 `?` 占位符替换为 `%s`，统一使用 `psycopg2` 兼容格式。

**理由**: 项目已迁移到 PostgreSQL，但部分代码仍保留 SQLite 风格的 `?` 占位符。`psycopg2` 的 `execute()` 使用 `%s` 作为占位符。受影响的代码位置数量有限（约 4-5 处），批量替换即可。

**替代方案**: 将这些原始 SQL 全部改为 SQLAlchemy ORM 调用。此方案更彻底但改动范围大，增加风险。当前阶段采用最小改动原则。

**涉及文件**:
- `chat.py`: `_lookup_company_api_key`, `_build_company_context_from_db`
- `model_gateway_extensions.py`: `TokenUsagePersistence.record()`
- `evolution.py`: `EvolutionLogger._persist_log()`

### 3. 前端 API 前缀对齐

**决策**: 后端在 `main.py` 中为所有路由添加统一的 `/api` 前缀，前端 `api.js` 保持 `API_BASE = '/api'`。

**理由**: 这是最标准的 SPA 前后端分离架构实践。所有 API 请求统一走 `/api/*`，前端静态资源走其他路径，避免路由冲突。

**替代方案**: 前端去掉 `/api` 前缀。此方案会导致未来添加其他非 API 路由（如静态资源、健康检查）时容易冲突。

**注意**: 需同时更新 `rate_limiter.py` 中的 `LLM_ENDPOINTS` 路径以匹配新的 `/api` 前缀。

### 4. 线程安全单例实现

**决策**: 在 `get_global_model_gateway()` 和 `get_session_store()` 中添加 `threading.Lock()`，实现双重检查锁定（Double-Checked Locking）模式。

**理由**: 当前 `if _instance is None: _instance = Class()` 在并发场景下可能创建多个实例。双重检查锁定是最小改动的线程安全方案。

**替代方案**: 使用 `@functools.lru_cache` 或模块级单例（Python 模块 import 天然线程安全）。但 `functools.lru_cache` 无法处理初始化参数，模块级单例不适合需要延迟初始化的场景。

**同时**: 合并 `agent.py` 和 `model_gateway.py` 中的两个独立 `_global_model_gateway`，统一使用 `app.services.model_gateway.get_global_model_gateway()`。

### 5. 进化引擎修复策略

**决策**:
- `interval_hours` 使用 `is None` 检查替代 `or` 短路: `self.interval_hours = interval_hours if interval_hours is not None else self.DEFAULT_INTERVAL_HOURS`
- `_get_agent_runtime` 修正导入路径为 `app.runtime.orchestrator`
- `MemoryAutoWriter._cache_to_redis` 使用 SessionStore 的公共 API 替代直接访问 `_redis` 属性

**理由**: 这些问题都是代码逻辑错误，修复简单直接，不需要架构变更。

### 6. 假数据替换策略

**决策**: Dashboard 和 Agent Chat 的假数据 API 端点标注 `# TODO: 接入真实数据源`，返回明确的占位数据结构（而非随机数据），前端在数据为空时显示"暂无数据"。

**理由**: 接入真实数据源需要完整的业务逻辑和数据管道，超出本次 bug 修复范围。但当前返回随机假数据会误导用户，改为返回明确的空/占位数据更诚实。

## Risks / Trade-offs

- **[路由前缀修改] → 影响范围较大**: 所有 API 端点路径变更，需要同步更新前端 `api.js` 中的所有请求路径、限流中间件的端点列表、以及任何硬编码的 API URL。缓解：逐文件审核所有 API 路径引用。
- **[SQL 占位符修改] → 可能遗漏**: 项目中使用原始 SQL 的位置较为分散。缓解：全局搜索 `" ?"` 和 `' ?'` 模式确认所有受影响位置。
- **[线程安全修复] → 锁竞争**: 添加 Lock 可能在高并发下引起轻微性能下降。缓解：双重检查锁定模式中，锁只在初始化阶段持有，正常运行时无竞争。
- **[前端 SSE 协议修改] → 需要前后端联调**: 事件类型对齐需要确保前后端字段名完全一致。缓解：定义明确的 SSE 事件类型枚举，前后端共享。

## Migration Plan

1. 按优先级分批修复：严重 → 高 → 中 → 低
2. 每批修复后运行单元测试和 E2E 测试验证
3. 前端修改后手动验证关键用户流程（登录 → 聊天 → 仪表盘）
4. 无数据库迁移需求，无需回滚策略

## Open Questions

- 是否需要引入 `httpx` 或 `aiohttp` 替代部分 `requests` 同步调用，以支持 FastAPI 的异步特性？（当前 scope 外，后续优化）
- Token 刷新机制：是否需要引入 refresh token 机制，还是仅延长 access token 有效期？（需产品确认）