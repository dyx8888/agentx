# AgentX Platform 技术方案文档

> **版本**: v1.0
> **日期**: 2026-06-20
> **状态**: Draft
> **对应阶段**: 第四阶段「技术方案设计」
> **依据**: PRD v3.4 / Scope v3.4 / AC v3.4

---

## 1. 架构总览

### 1.1 架构决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 架构模式 | **单体应用** | 现有代码已是单体 FastAPI，Scope 明确"推倒重写"为 Out of Scope；增量建设 |
| 前后端模式 | **前后端分离** | 现有 React SPA + FastAPI REST API，SSE 流式已实现 |
| 后端框架 | **FastAPI + LangGraph** | 沿用现有技术栈，Agent 编排引擎已基于 LangGraph StateGraph 实现 |
| 前端框架 | **React 18 + Vite 5** | 沿用现有技术栈，Tailwind CSS 4 + Ant Design 5 |
| 数据库 | **PostgreSQL** (生产) / SQLite (开发) | 已有 SQLAlchemy 2.0 ORM 双适配层 |
| 向量数据库 | **ChromaDB** (本地模式) | 已在用，Scope 明确 Milvus 为 Out of Scope |
| 缓存 | **Redis 5.0** | 已在用，用于会话缓存、checkpoint、限流计数器 |
| 模型网关 | **LLMGateway** (最小可行版) | 已实现统一入口 + 日志 + usage + fallback |
| Agent 引擎 | **LangGraph Plan-Execute-Reflect** | 已实现三层架构，含安全兜底（最大 10 轮 / Token 阈值） |

### 1.2 系统架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                         前端层 (React SPA)                        │
│  ┌─────────┐  ┌──────────────────────────────────────────────┐  │
│  │ 登录页   │  │              对话页（唯一核心页面）             │  │
│  │         │  │  ┌──────────┐  ┌──────────────────────────┐  │  │
│  │         │  │  │ 对话历史  │  │  Master 对话区            │  │  │
│  │         │  │  │          │  │  · SSE 流式展示           │  │  │
│  │         │  │  │          │  │  · 内联产出物卡片          │  │  │
│  │         │  │  │          │  │  · 审核确认按钮            │  │  │
│  │         │  │  └──────────┘  └──────────────────────────┘  │  │
│  └─────────┘  └──────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────────────┤
│                       HTTP/SSE/WebSocket                          │
├──────────────────────────────────────────────────────────────────┤
│                       后端层 (FastAPI)                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ ┌───────────────┐  │
│  │ 认证模块  │ │ 聊天 API │ │ 知识库 API    │ │ 管理 API      │  │
│  │ /api/auth│ │ /api/chat│ │ /api/knowledge│ │ /api/admin    │  │
│  └──────────┘ └────┬─────┘ └──────────────┘ └───────────────┘  │
│                     │                                             │
│  ┌──────────────────┼──────────────────────────────────────┐    │
│  │            感知管道 (Perception Pipeline)                  │    │
│  │  输入过滤 → 查询改写 → 意图识别 → RAG 检索                 │    │
│  └──────────────────┼──────────────────────────────────────┘    │
│                     │                                             │
│  ┌──────────────────┼──────────────────────────────────────┐    │
│  │          AgentRuntime (Plan-Execute-Reflect)              │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐               │    │
│  │  │ Planner  │→ │ Executor │→ │Reflector │               │    │
│  │  └──────────┘  └────┬─────┘  └──────────┘               │    │
│  │                      │                                     │    │
│  │  ┌───────────────────┼───────────────────────────┐       │    │
│  │  │          隐形 Agent 能力池                      │       │    │
│  │  │  达人搜索 │ 数据分析 │ 内容策划 │ 物流跟踪     │       │    │
│  │  └───────────────────────────────────────────────┘       │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐       │
│  │ 模型网关  │ │Context   │ │ 三层记忆  │ │ Prompt 管理  │       │
│  │LLMGateway│ │Assembler │ │ 系统     │ │ 版本化       │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘       │
├──────────────────────────────────────────────────────────────────┤
│                       数据层                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐       │
│  │PostgreSQL│ │  Redis   │ │ChromaDB  │ │  文件存储     │       │
│  │(主数据库) │ │(缓存/队列)│ │(向量检索) │ │  (文档)      │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘       │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. 技术栈详情

### 2.1 后端技术栈

| 类别 | 技术 | 版本 | 用途 |
|------|------|------|------|
| 语言 | Python | 3.11+ | 主开发语言 |
| Web 框架 | FastAPI | 0.68+ | REST API + SSE 流式 |
| ASGI 服务器 | Uvicorn | 0.15+ | 开发/生产服务器 |
| Agent 框架 | LangGraph | 0.2+ | Agent 编排（StateGraph + Checkpoint） |
| LLM 调用 | LangChain | 0.2+ | 统一 LLM 接口抽象 |
| ORM | SQLAlchemy | 2.0+ | 数据库 ORM |
| 数据库 | PostgreSQL | 14+ | 主数据库（生产） |
| 向量数据库 | ChromaDB | 0.4+ | 向量检索（本地模式） |
| 缓存 | Redis | 5.0+ | 会话缓存、checkpoint、限流 |
| 嵌入模型 | Sentence-Transformers | 2.2+ | 文本向量化（BGE/M3E） |
| 认证 | python-jose + bcrypt | 3.3+ / 4.0+ | JWT 令牌 + 密码哈希 |
| 结构化日志 | structlog | 23.0+ | 结构化日志输出 |
| 流式协议 | sse-starlette | 1.6+ | SSE 服务端推送 |
| MCP 协议 | fastmcp + mcp | 2.0+ / 1.0+ | 工具标准化接入 |
| 代码质量 | ruff | 0.15+ | Lint + 格式化 |

### 2.2 前端技术栈

| 类别 | 技术 | 版本 | 用途 |
|------|------|------|------|
| 语言 | JavaScript (JSX) | ES2022+ | 主开发语言 |
| UI 框架 | React | 18.2+ | 组件化 UI |
| 构建工具 | Vite | 5.2+ | 开发服务器 + 打包 |
| CSS 框架 | Tailwind CSS | 4.3+ | 原子化 CSS |
| 组件库 | Ant Design | 5.17+ | 企业级 UI 组件 |
| 图标 | Ant Design Icons | 5.3+ | 图标库 |
| 路由 | React Router DOM | 6.23+ | 客户端路由 |
| HTTP 客户端 | Axios | 1.7+ | API 请求 |
| 工具 | tailwind-merge + clsx | 3.5+ / 2.1+ | 样式合并 |
| 测试 | Vitest + Testing Library | 4.1+ / 16.3+ | 单元/组件测试 |

### 2.3 DevOps

| 类别 | 技术 | 用途 |
|------|------|------|
| 容器化 | Docker | 标准化部署 |
| CI/CD | GitHub Actions | 自动化测试与部署 |
| 代码质量 | pre-commit hooks | 提交前检查 |
| 反向代理 | Nginx | 生产环境代理（含 SSE 缓冲关闭） |

---

## 3. 前端架构设计

### 3.1 页面路由

```
/login          → 登录页
/chat           → 对话页（唯一核心页面，需登录）
/chat/:id       → 特定对话（从历史列表进入）
```

### 3.2 组件树

```
App
├── LoginPage
│   ├── LoginForm (用户名/密码)
│   └── DemoLoginButton (演示账号登录)
│
├── ChatPage (ProtectedRoute)
│   ├── Sidebar
│   │   ├── NewChatButton
│   │   ├── ConversationList
│   │   │   └── ConversationItem (标题 + 时间 + 删除)
│   │   └── UserMenu (设置/退出)
│   │
│   ├── ChatArea
│   │   ├── WelcomeMessage (首次进入，能力介绍)
│   │   ├── MessageList
│   │   │   ├── UserMessage (用户消息气泡)
│   │   │   └── MasterMessage
│   │   │       ├── ThinkingIndicator (流式加载中)
│   │   │       ├── TextContent (Markdown 渲染)
│   │   │       ├── InlineCard (内联产出物卡片)
│   │   │       │   ├── KolListCard (达人列表)
│   │   │       │   ├── AnalysisReportCard (分析报告)
│   │   │       │   ├── ScriptCard (脚本，含审核按钮)
│   │   │       │   └── LogisticsCard (物流状态)
│   │   │       └── SourceReferences (RAG 引用标注)
│   │   │
│   │   └── ChatInput
│   │       ├── TextArea (输入框)
│   │       ├── QuickActions (能力引导快捷指令)
│   │       └── SendButton
│   │
│   └── PlanConfirmationModal (复杂任务计划确认弹窗)
```

### 3.3 数据流

```
用户输入 → ChatInput → POST /api/chat (SSE)
  → 前端接收 SSE 事件流:
    ├── {type: "thinking"}   → 显示"AI 正在思考..."
    ├── {type: "intent"}     → 记录意图分类（用于统计）
    ├── {type: "plan"}       → 显示执行计划（可选）
    ├── {type: "sources"}    → 显示 RAG 引用来源
    ├── {type: "tool_result"} → 显示工具执行结果
    ├── {type: "reflection"}  → 显示质量检查结果
    ├── {type: "content"}     → 逐字追加到消息区
    ├── {type: "retry"}       → 显示重试状态
    └── {type: "done"}        → 关闭加载状态，消息完成
```

### 3.4 状态管理

采用 React 内置状态管理（useState + useReducer + Context），不引入 Redux/MobX：

| 状态 | 存储位置 | 说明 |
|------|---------|------|
| 用户认证 | AuthContext | JWT token, 用户信息 |
| 当前对话 | ChatPage state | 当前消息列表 |
| 对话历史 | ChatPage state | 侧边栏历史列表 |
| 流式状态 | ChatArea state | 是否正在流式接收 |
| UI 状态 | 各组件 state | 弹窗显示/隐藏等 |

---

## 4. 后端架构设计

### 4.1 模块分层

```
backend/
├── app/
│   ├── main.py                    # FastAPI 入口，生命周期管理
│   ├── api/                       # API 路由层
│   │   ├── chat.py                # 核心聊天 API（SSE 流式）
│   │   ├── auth_router.py         # 认证 API
│   │   ├── conversations.py       # 🆕 对话管理 API
│   │   ├── knowledge.py           # 知识库 API
│   │   ├── feedback.py            # 反馈 API
│   │   └── admin/                 # 管理 API
│   │
│   ├── agents/                    # Agent 定义
│   │   ├── master.py              # 🆕 Master Orchestrator
│   │   ├── kol_search.py         # 达人搜索 Agent
│   │   ├── data_analysis.py      # 数据分析 Agent
│   │   ├── content_planning.py   # 内容策划 Agent
│   │   └── logistics.py          # 物流跟踪 Agent
│   │
│   ├── runtime/                   # Agent 运行时
│   │   ├── orchestrator.py       # AgentRuntime (Plan-Execute-Reflect)
│   │   ├── memory.py             # 三层记忆系统
│   │   ├── nodes.py              # LangGraph 节点函数
│   │   └── validator.py          # 动态校验器
│   │
│   ├── core/                      # 核心模块
│   │   ├── context_assembler.py  # 上下文组装器
│   │   ├── prompt_loader.py      # Prompt 版本管理
│   │   ├── logging.py            # 结构化日志
│   │   ├── checkpoint.py         # Redis checkpoint
│   │   └── working_memory.py     # 工作记忆
│   │
│   ├── services/                  # 服务层
│   │   ├── model_gateway.py      # 模型网关（LLMGateway）
│   │   └── evolution.py          # 进化引擎
│   │
│   ├── perception/                # 感知管道
│   │   └── pipeline.py           # 感知管道（过滤→改写→意图→RAG）
│   │
│   ├── rag/                       # RAG 检索
│   │   ├── hybrid_retriever.py   # 混合检索器（BM25+向量+RRF）
│   │   ├── reranker.py           # Cross-Encoder 精排
│   │   ├── query_rewriter.py     # 查询改写
│   │   ├── chunker.py            # 自适应 Chunk 策略
│   │   └── agentic_rag.py        # AgenticRAG 编排
│   │
│   ├── database/                  # 数据库
│   │   ├── models.py             # SQLAlchemy ORM 模型
│   │   ├── core.py               # 数据库初始化
│   │   └── postgres_adapter.py   # PostgreSQL 适配器
│   │
│   ├── middleware/                # 中间件
│   │   ├── rate_limiter.py       # 多层级限流
│   │   ├── input_filter.py       # 输入过滤
│   │   └── logging.py            # 请求日志中间件
│   │
│   ├── tools/                     # 工具管理
│   │   ├── registry.py           # 工具注册表
│   │   └── loader.py             # MCP 工具加载器
│   │
│   ├── skills/                    # 技能管理
│   │   └── registry.py           # 技能注册表
│   │
│   ├── tracking/                  # 追踪
│   │   └── tracer.py             # 分布式追踪
│   │
│   └── ws/                        # WebSocket
│       └── router.py             # WebSocket 路由
```

### 4.2 核心流程

#### 4.2.1 用户对话流程

```
1. 用户发送消息 → POST /api/chat (SSE)
2. 输入过滤 (InputFilter)
3. 感知管道 (PerceptionPipeline):
   a. 查询改写 (QueryRewriter)
   b. 意图识别 (IntentClassifier)
   c. RAG 检索 (HybridRetriever → Reranker)
   d. 上下文组装 (ContextAssembler)
4. AgentRuntime 执行:
   a. Planner → 生成执行计划
   b. Executor → 逐步执行（调用隐形 Agent）
   c. Reflector → 质量审查
   d. 未通过则回到 Executor（最多 10 轮）
5. 结果通过 SSE 流式推送到前端
6. 对话记录持久化到 PostgreSQL
7. 关键经验提取写入长期记忆
```

#### 4.2.2 Agent 隐形路由逻辑

```
用户输入 → Master Orchestrator 意图识别 →
  ├── "找达人" / "搜索达人" / "达人推荐"
  │     → 达
  │     → 达人搜索 Agent
  ├── "分析" / "数据" / "ROI" / "竞品"
  │     → 数据分析 Agent
  ├── "脚本" / "文案" / "策划" / "种草"
  │     → 内容策划 Agent
  ├── "物流" / "快递" / "发货" / "样品"
  │     → 物流跟踪 Agent
  └── 复杂/多意图
        → Master 拆解为多个子任务，分别路由
```

---

## 5. 数据库设计

### 5.1 现有表（保留不变）

| 表名 | 用途 | 本期动作 |
|------|------|----------|
| `users` | 用户信息 | 保留 |
| `companies` | 公司信息 | 保留 |
| `agents` | Agent 配置 | 保留 |
| `tasks` | 任务记录 | 保留 |
| `feedback` | 反馈记录 | 保留 |
| `evolution_log` | 进化日志 | 保留 |
| `subscription_plans` | 订阅套餐 | 保留 |
| `company_subscriptions` | 公司订阅 | 保留 |
| `company_agent_tools` | 工具开关 | 保留 |
| `company_agent_skills` | 技能开关 | 保留 |
| `task_board` | 任务看板 | 保留 |
| `result_cache` | 结果缓存 | 保留 |
| `decision_log` | 决策日志 | 保留 |
| `feedback_log` | 反馈日志 | 保留 |
| `skill_evolution_log` | 技能进化 | 保留 |
| `user_behavior` | 用户行为 | 保留 |
| `user_lora` | LoRA 适配器 | 保留 |
| `a2a_messages` | Agent 消息 | 保留 |
| `workflows` | 工作流 | 保留 |

### 5.2 新增表（本期 MVP）

| 表名 | 用途 | 优先级 |
|------|------|--------|
| `conversations` | 对话会话管理 | Must Have |
| `messages` | 对话消息记录 | Must Have |
| `kol_profiles` | 达人档案数据 | Must Have |
| `kol_search_history` | 达人搜索历史 | Should Have |
| `content_scripts` | 内容脚本产出 | Should Have |
| `logistics_tracking` | 物流跟踪记录 | Should Have |
| `review_approvals` | 审核确认记录 | Should Have |

> 详细 CREATE TABLE 语句见 `docs/db-schema.sql`

---

## 6. API 接口设计

### 6.1 接口总览

| 模块 | 方法 | 路径 | 说明 | 优先级 |
|------|------|------|------|--------|
| 认证 | POST | `/api/auth/token` | 登录获取 JWT | Must Have |
| 认证 | POST | `/api/auth/users/register` | 用户注册 | Must Have |
| 认证 | POST | `/api/auth/token/refresh` | 刷新 Token | Must Have |
| 聊天 | POST | `/api/chat` | 流式聊天（SSE） | Must Have |
| 对话 | GET | `/api/conversations` | 获取对话列表 | Must Have |
| 对话 | POST | `/api/conversations` | 创建新对话 | Must Have |
| 对话 | GET | `/api/conversations/{id}` | 获取对话详情 | Must Have |
| 对话 | DELETE | `/api/conversations/{id}` | 删除对话 | Must Have |
| 达人 | POST | `/api/kol/search` | 达人搜索 | Must Have |
| 达人 | GET | `/api/kol/{id}` | 达人详情 | Should Have |
| 达人 | POST | `/api/kol/export` | 导出达人列表 | Could Have |
| 审核 | POST | `/api/review/{id}/approve` | 审核通过 | Should Have |
| 审核 | POST | `/api/review/{id}/reject` | 审核驳回 | Should Have |
| 知识库 | POST | `/api/knowledge/upload` | 上传文档 | Must Have |
| 知识库 | GET | `/api/knowledge/documents` | 文档列表 | Should Have |
| 知识库 | DELETE | `/api/knowledge/documents/{id}` | 删除文档 | Should Have |

> 完整 OpenAPI 定义见 `docs/api-spec.yaml`

---

## 7. 安全设计

### 7.1 认证与授权

- **认证**: JWT (access_token 30min + refresh_token 7d)
- **密码**: bcrypt 哈希, 最低 8 位
- **API Key**: EncryptedText 字段级加密存储
- **多租户**: 所有查询带 `company_id` 隔离

### 7.2 输入安全

- XSS 防护: InputFilter 过滤特殊字符
- SQL 注入: SQLAlchemy 参数化查询
- 限流: 用户级/租户级/模型级/供应商级四层限流

### 7.3 数据安全

- PII 脱敏: 日志中敏感字段自动脱敏
- 敏感字段加密: API Key、平台凭证 EncryptedText 加密存储
- 审计日志: 所有关键操作带 trace_id 可追溯

---

## 8. 非功能性需求

### 8.1 性能

| 指标 | 目标 | 测量方式 |
|------|------|---------|
| 首字延迟 (TTFT) | < 2s | SSE 流式首个 token 到达时间 |
| API 响应 (非流式) | < 200ms | 中间件计时 |
| 并发用户 | 50+ | 压力测试 |
| 数据库连接池 | 20 连接 | PostgreSQL 配置 |

### 8.2 可靠性

- Agent Loop 最大 10 轮 + Token 阈值 100K 安全兜底
- 模型网关 fallback 机制（主模型不可用时自动切换）
- Redis 不可用时降级运行（不影响核心对话）
- 幂等 Key 防止重复请求

### 8.3 可观测性

- 结构化日志 (structlog): 含 trace_id, request_id, tenant_id
- 健康检查: `/health` 含 database/redis/chroma 探活
- 指标: Prometheus 格式 `/metrics`
- 评测: 7 项指标 (Context Recall / Precision / Faithfulness / Answer Relevancy / Tool Success Rate / Format Valid Rate / Cost per Success)

---

## 9. 部署架构

### 9.1 开发环境

```
┌─────────────┐    ┌─────────────────┐
│ Vite Dev     │    │ Uvicorn (reload)│
│ localhost:   │───→│ localhost:      │
│ 5173         │    │ 8000            │
└─────────────┘    └───────┬─────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌────────┐ ┌──────────┐
        │PostgreSQL│ │ Redis  │ │ChromaDB  │
        └──────────┘ └────────┘ └──────────┘
```

### 9.2 生产环境

```
┌─────────────┐
│   Nginx     │ (反向代理, SSL 终止, proxy_buffering off)
└──────┬──────┘
       │
┌──────┴──────┐    ┌─────────────────┐
│ 静态文件     │    │ Uvicorn         │
│ (Vite build)│    │ (4 workers)     │
└─────────────┘    └───────┬─────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌────────┐ ┌──────────┐
        │PostgreSQL│ │ Redis  │ │ChromaDB  │
        └──────────┘ └────────┘ └──────────┘
```

---

## 10. 前后端分工

### 10.1 前端负责

- 登录页 + 对话页 UI 实现
- SSE 事件流接收与解析
- 内联产出物卡片渲染（达人列表/分析报告/脚本/物流）
- 对话历史管理（列表/切换/删除）
- 审核确认交互（通过/驳回按钮）
- 能力引导快捷指令
- 流式加载动画与状态管理
- Markdown 渲染 + 引用标注展示

### 10.2 后端负责

- 用户认证（JWT + bcrypt）
- 感知管道（输入过滤 → 查询改写 → 意图识别 → RAG 检索）
- AgentRuntime 编排（Plan-Execute-Reflect）
- 隐形 Agent 能力池（达人搜索/数据分析/内容策划/物流跟踪）
- SSE 流式响应推送
- 对话持久化与历史管理
- RAG 检索增强（HybridRetriever + Reranker）
- 三层记忆系统（工作/短期/长期 + 睡眠巩固）
- 模型网关（路由/fallback/限流/Token 预算）
- Prompt 版本管理
- 上下文组装（ContextAssembler）
- 审核确认逻辑
- 数据导出（CSV/PDF）

### 10.3 接口契约

前后端通过 RESTful API + SSE 通信，接口定义以 `docs/api-spec.yaml` 为准。前端不直接访问数据库或模型网关，所有数据通过后端 API 获取。

---

## 11. 技术风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| LLM 响应不稳定 | 用户体验差 | Agent Loop 安全兜底 + 模型 fallback |
| Token 消耗过高 | 成本失控 | Token 预算管理 + 限流分层 |
| RAG 检索召回低 | 回答质量差 | Hybrid Search + Rerank + 评估集持续优化 |
| SSE 连接中断 | 流式中断 | 断流检测 + 重连机制 + messageId 幂等 |
| 上下文爆炸 | Agent 推理质量下降 | ContextAssembler + Token 预算裁剪 |
| 多租户数据泄露 | 安全事故 | company_id 隔离 + 审计日志 |

---

## 12. 文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 产品需求文档 | `docs/PRD.md` | 产品需求 v3.4 |
| 项目范围 | `docs/Scope.md` | 范围定义 v3.4 |
| 验收标准 | `docs/AC.md` | 验收标准 v3.4 |
| API 接口定义 | `docs/api-spec.yaml` | OpenAPI 3.0 接口定义 |
| 数据库设计 | `docs/db-schema.sql` | 完整建表语句 |
| 任务排期 | `docs/schedule.md` | 任务拆解与排期 |
| RAG 优化分析 | `docs/RAG优化分析报告.md` | RAG 技术评估 |