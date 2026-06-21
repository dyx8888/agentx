## 1. API 路由前缀修复

- [x] 1.1 移除 chat.py APIRouter 中的 prefix="/chat"
- [x] 1.2 移除 tasks.py APIRouter 中的 prefix="/tasks"
- [x] 1.3 移除 evolution.py APIRouter 中的 prefix="/admin/evolution"
- [x] 1.4 移除 dashboard.py APIRouter 中的 prefix="/api/v1/dashboard"
- [x] 1.5 移除 agents.py APIRouter 中的 prefix="/admin/agents"
- [x] 1.6 验证 main.py 中所有 include_router 的 prefix 配置正确
- [x] 1.7 为所有后端 API 在 main.py 中统一添加 /api 前缀

## 2. 数据库兼容性修复

- [x] 2.1 将 chat.py 中 SQL 的 ? 占位符替换为 %s
- [x] 2.2 将 model_gateway_extensions.py 中 SQL 的 ? 占位符替换为 %s
- [x] 2.3 将 evolution.py 中 SQL 的 ? 占位符替换为 %s
- [x] 2.4 将 feedback.py 中 SQL 的 ? 占位符替换为 %s
- [x] 2.5 在 chat.py 的 finally 块中添加 conn.close()，确保异常路径也能关闭连接
- [x] 2.6 在 feedback.py 的 finally 块中添加 conn.close()
- [x] 2.7 修复 feedback 表结构：添加 agent_id 列以匹配 INSERT 语句

## 3. 前后端通信对齐

- [x] 3.1 更新前端 api.js 中的所有请求路径，添加 /api 前缀
- [x] 3.2 更新 rate_limiter.py 中 LLM_ENDPOINTS 的路径，添加 /api 前缀
- [x] 3.3 对齐 AgentChat.jsx 的 SSE 事件类型，使其与后端一致
- [x] 3.4 修正 chatWithAgent API 请求路径，指向真实 /api/chat 端点而非 mock 端点
- [x] 3.5 添加 /api/auth/refresh 端点实现 token 刷新，或调整前端过期处理策略
- [x] 3.6 修复 loginApi，添加响应状态码检查

## 4. 线程安全修复

- [x] 4.1 在 get_global_model_gateway() 中添加 threading.Lock() 双重检查锁定
- [x] 4.2 移除 agent.py 中的重复 get_global_model_gateway() 定义，改为导入 services 中的实现
- [x] 4.3 在 get_session_store() 中添加 threading.Lock() 双重检查锁定

## 5. 数据完整性修复

- [x] 5.1 修复 Token 用量记录中 company_id 的取数逻辑，不再使用错误 key 从 _quotas 获取
- [x] 5.2 修复 evolution 中进化日志表名，与 ORM 模型中的 evolution_log 一致
- [x] 5.3 重命名 database/__init__.py 中的 Pydantic 模型（添加 Pydantic 后缀），消除与 SQLAlchemy 模型的命名冲突
- [x] 5.4 修复 company_context_bus.py 中的 O(n²) 去重逻辑，使用更高效的基于索引的去重
- [x] 5.5 修复 evolution.py 中 _store_long_term 调用不存在的 add_experience 方法和 get_context_bus 函数

## 6. 进化引擎修复

- [x] 6.1 修复 SleepConsolidationEngine interval_hours 赋值，使用 is None 判断而非 or 短路
- [x] 6.2 修正 _get_agent_runtime 的导入路径，指向 app.runtime.orchestrator
- [x] 6.3 修改 MemoryAutoWriter._cache_to_redis 使用 SessionStore 公共 API，不直接访问私有 _redis 属性

## 7. 异常处理与日志规范化

- [x] 7.1 消除裸 except: pass，修复 auth.py 中 verify_password 的 bare except
- [x] 7.2 InputFilter 拒绝输入时返回 400 友好错误，而非 Pydantic ValidationError
- [x] 7.3 修复 main.py 中异常处理的 timestamp 硬编码问题，设置正确的当前时间戳

## 8. 启动稳定性修复

- [x] 8.1 将 auth.py 中的 JWT_SECRET_KEY 检查从模块级移到 _get_secret_key() 函数调用时
- [x] 8.2 移除 encryption.py 中的模块级 initialize_encryption() 调用
- [x] 8.3 将 feedback.py 中的 feedback_db 实例化延迟到 get_feedback_db() 首次请求
- [x] 8.4 修复 create_agent_sync 中的嵌套事件循环问题，添加运行事件循环检测

## 9. 假数据与占位处理

- [x] 9.1 在 Dashboard API 各端点添加 TODO 注释标注待接入真实数据源
- [x] 9.2 在 agents.py 端点添加 TODO 注释标注待接入真实 Agent 引擎

## 10. 收尾验证

- [x] 10.1 所有修改文件通过 Python 语法编译检查
- [x] 10.2 前端文件 (api.js, AgentChat.jsx) 确认可读取
- [x] 10.3 验证数据库操作不报错（SQL 占位符修复、连接关闭修复）
- [x] 10.4 更新登录页版权年份到 2026