# Changelog

## v1.0.0 (2026-06-21)

### AgentX MVP 初始版本

**核心功能**
- 用户认证：支持演示账号登录、JWT Token 认证
- 智能对话：基于 Master Agent 的多轮对话，支持 SSE 流式响应
- Agent 管理：支持多 Agent 配置与路由
- 记忆管理：三层记忆架构（短期/长期/工作记忆）
- 知识库：RAG 检索增强生成，支持上下文注入
- 模型网关：Failover 模型切换，支持多模型供应商

**技术栈**
- 后端：FastAPI + LangChain + LangGraph
- 前端：React 18 + Vite 5 + Ant Design 5
- 数据库：PostgreSQL（生产）/ SQLite（开发）
- 实时通信：SSE（Server-Sent Events）

**验收通过**
- 前后端联调通过，核心用户流程跑通
- 健康检查正常响应
- 演示登录功能正常
- 对话流式输出正常
- 所有 AC 验收标准通过