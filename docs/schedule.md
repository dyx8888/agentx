# AgentX Platform 任务拆解与排期

> **版本**: v1.0
> **日期**: 2026-06-20
> **总工期**: 6 周（含 20% 缓冲）
> **团队配置**: 2 后端 + 1 前端 + 0.5 测试
> **缓冲策略**: 每项任务时间 × 1.2，总工期预留 20% 缓冲

---

## 1. 排期总览

```
Week 1 ──── Week 2 ──── Week 3 ──── Week 4 ──── Week 5 ──── Week 6
[████████████████████████████████████████████████████████████████]
[←── Phase 1: 基础设施 ──→][←─ Phase 2: 核心对话 ─→][← Phase 3: Agent 能力 →]
                          [←─ Phase 4: 审核与优化 ──→][← 缓冲 →]
```

| 阶段 | 内容 | 工期 | 依赖 |
|------|------|------|------|
| Phase 1 | 基础设施搭建 | 第 1-2 周 | 无 |
| Phase 2 | 核心对话能力 | 第 2-3 周 | Phase 1 |
| Phase 3 | Agent 能力激活 | 第 3-4 周 | Phase 2 |
| Phase 4 | 审核确认与优化 | 第 4-5 周 | Phase 3 |
| Buffer | 缓冲与联调 | 第 5-6 周 | Phase 4 |

---

## 2. Phase 1: 基础设施搭建（第 1-2 周）

### 任务 1.1: 数据库表创建与迁移

**负责人**: 后端 A
**工期**: 2 天（含缓冲 2.4 天）
**依赖**: 无

- [ ] 在 `backend/app/database/models.py` 中新增 7 张表的 SQLAlchemy ORM 模型
  - `Conversation`, `Message`, `KolProfile`, `KolSearchHistory`
  - `ContentScript`, `LogisticsTracking`, `ReviewApproval`
- [ ] 创建 Alembic 迁移脚本
- [ ] 执行 `alembic upgrade head` 验证建表成功
- [ ] 插入演示种子数据（5 条示例达人）

**验收标准**:
- `python -c "from app.database.models import Conversation, Message, KolProfile"` 无报错
- 数据库中 7 张新表存在且结构正确

---

### 任务 1.2: 对话管理 API

**负责人**: 后端 A
**工期**: 2 天（含缓冲 2.4 天）
**依赖**: 任务 1.1

- [ ] 创建 `backend/app/api/conversations.py`
- [ ] 实现 CRUD 接口:
  - `GET /api/conversations` — 获取对话列表
  - `POST /api/conversations` — 创建新对话
  - `GET /api/conversations/{id}` — 获取对话详情（含消息列表）
  - `DELETE /api/conversations/{id}` — 删除对话
- [ ] 在 `backend/app/main.py` 注册路由
- [ ] 编写单元测试

**验收标准**:
- `pytest tests/api/test_conversations.py` 全部通过
- Swagger `/docs` 可看到新增接口

---

### 任务 1.3: 前端路由与页面骨架

**负责人**: 前端
**工期**: 3 天（含缓冲 3.6 天）
**依赖**: 无（可与后端并行）

- [ ] 创建页面路由结构:
  - `/login` → LoginPage
  - `/chat` → ChatPage（ProtectedRoute）
  - `/chat/:id` → ChatPage（带 conversation_id）
- [ ] 实现 AuthContext（JWT 存储、自动刷新、登录状态判断）
- [ ] 实现 ProtectedRoute 组件（未登录跳转登录页）
- [ ] 搭建 ChatPage 骨架:
  - Sidebar（历史列表占位）
  - ChatArea（消息区 + 输入框）
  - ChatInput（文本输入 + 发送按钮）
- [ ] 搭建 LoginPage 骨架（表单 + 演示账号按钮）

**验收标准**:
- 未登录访问 `/chat` → 跳转到 `/login`
- 登录后访问 `/chat` → 正常渲染 ChatPage 骨架
- 前端 `npm run dev` 正常启动

---

### 任务 1.4: 前端 API 客户端封装

**负责人**: 前端
**工期**: 1 天（含缓冲 1.2 天）
**依赖**: 任务 1.3

- [ ] 创建 `frontend/src/api/client.js` — Axios 实例（baseURL、拦截器、Token 自动注入）
- [ ] 创建 `frontend/src/api/auth.js` — 登录/注册/刷新 Token API
- [ ] 创建 `frontend/src/api/chat.js` — SSE 流式聊天 API（EventSource 封装）
- [ ] 创建 `frontend/src/api/conversations.js` — 对话管理 API

**验收标准**:
- Token 过期自动刷新（401 → refresh → 重试）
- SSE 事件流正确解析各类型事件

---

## 3. Phase 2: 核心对话能力（第 2-3 周）

### 任务 2.1: 登录注册页面前端实现

**负责人**: 前端
**工期**: 2 天（含缓冲 2.4 天）
**依赖**: 任务 1.3, 1.4

- [ ] LoginForm: 用户名/密码输入、表单校验、错误提示
- [ ] DemoLoginButton: 一键演示账号登录
- [ ] 注册页面: 用户名/密码/公司名/品牌名/行业分类
- [ ] 登录成功 → 存储 JWT → 跳转 `/chat`

**验收标准**:
- AC-03.1.1 ~ AC-03.2.5 全部通过
- 错误密码 → 显示"用户名或密码错误"

---

### 任务 2.2: 对话页面前端实现

**负责人**: 前端
**工期**: 4 天（含缓冲 4.8 天）
**依赖**: 任务 1.3, 1.4, 2.1

- [ ] WelcomeMessage: 首次进入显示能力介绍（Master 问候语 + 能力列表）
- [ ] MessageList: 消息列表渲染
  - UserMessage: 用户消息气泡（右对齐）
  - MasterMessage: Master 消息气泡（左对齐，Markdown 渲染）
- [ ] ChatInput: 输入框 + Enter 发送 + Shift+Enter 换行
- [ ] SSE 流式集成:
  - ThinkingIndicator: 流式加载动画
  - 逐字追加内容到消息区
  - done 事件 → 关闭加载状态
- [ ] QuickActions: 输入框下方快捷指令按钮
- [ ] 自动滚动到最新消息

**验收标准**:
- AC-01.1.1 ~ AC-01.3.2 全部通过
- 发送"你好" → Master 回复出现在对话区
- 流式逐字显示

---

### 任务 2.3: 对话历史前端实现

**负责人**: 前端
**工期**: 2 天（含缓冲 2.4 天）
**依赖**: 任务 2.2

- [ ] ConversationList: 左侧历史列表（标题 + 时间）
- [ ] 点击历史项 → 切换对话内容
- [ ] NewChatButton: 新建对话
- [ ] 删除对话（确认弹窗 + 软删除）

**验收标准**:
- AC-04.1.1 ~ AC-04.1.4 全部通过
- 新建对话 → 清空对话区

---

### 任务 2.4: Master Orchestrator Agent 创建

**负责人**: 后端 B
**工期**: 3 天（含缓冲 3.6 天）
**依赖**: 任务 1.1

- [ ] 创建 `backend/app/agents/master.py`
  - Master System Prompt 设计（角色定位、能力声明、路由规则）
  - 意图识别：从用户消息中提取目标 Agent
  - 任务拆解：复杂任务拆为子任务
  - 结果汇总：收集子 Agent 结果并格式化输出
- [ ] 在 AgentRuntime 中注册 Master 为默认 Agent
- [ ] 集成到 `/api/chat` 流式管道

**验收标准**:
- 发送"帮我找美妆达人" → Master 识别意图并路由到达人搜索 Agent
- 发送"帮我分析数据并策划脚本" → Master 拆解为多个子任务

---

### 任务 2.5: 对话消息持久化

**负责人**: 后端 A
**工期**: 2 天（含缓冲 2.4 天）
**依赖**: 任务 1.1, 2.4

- [ ] 在 `/api/chat` 流式处理中：
  - 对话开始时自动创建或复用 conversation
  - 每条用户消息和 Master 回复写入 messages 表
  - 自动更新 conversation 的 message_count 和 last_message
- [ ] 消息 metadata_json 存储结构化数据（达人列表、报告等）
- [ ] 消息 references_json 存储 RAG 引用

**验收标准**:
- 发送消息后 → 数据库中 messages 表有新记录
- 对话结束后 → conversations 表 message_count 正确

---

## 4. Phase 3: Agent 能力激活（第 3-4 周）

### 任务 3.1: 达人搜索 Agent 实现

**负责人**: 后端 B
**工期**: 3 天（含缓冲 3.6 天）
**依赖**: 任务 2.4

- [ ] 创建 `backend/app/agents/kol_search.py`
  - 达人搜索 System Prompt
  - 调用 `search_kols` 工具（从 kol_profiles 表查询）
  - 结果格式化（达人列表卡片）
- [ ] 实现 `POST /api/kol/search` 接口
  - 支持多条件筛选（平台、分类、粉丝数、互动率）
  - 支持排序（粉丝数 / 互动率 / 相关性）
- [ ] 实现 `GET /api/kol/{id}` 达人详情接口
- [ ] 搜索历史记录（写入 kol_search_history 表）

**验收标准**:
- AC-02.1.1 ~ AC-02.1.5 全部通过
- 发送"帮我找美妆达人" → 返回达人列表

---

### 任务 3.2: 内联产出物卡片前端实现

**负责人**: 前端
**工期**: 3 天（含缓冲 3.6 天）
**依赖**: 任务 2.2, 3.1

- [ ] KolListCard: 达人列表卡片
  - 达人姓名、平台、粉丝数、互动率
  - "查看全部"展开按钮
  - 点击达人 → 查看详情弹窗
- [ ] AnalysisReportCard: 分析报告卡片
- [ ] ScriptCard: 脚本卡片（含审核通过/驳回按钮）
- [ ] LogisticsCard: 物流状态卡片
- [ ] 根据 SSE 事件中的 content_type 自动选择卡片类型渲染

**验收标准**:
- 达人搜索结果以内联卡片形式展示
- 卡片内容完整可读

---

### 任务 3.3: 数据分析 Agent 实现

**负责人**: 后端 A
**工期**: 2 天（含缓冲 2.4 天）
**依赖**: 任务 2.4

- [ ] 创建 `backend/app/agents/data_analysis.py`
  - 数据分析 System Prompt
  - 数据质量分析、ROI 计算、竞品分析能力
- [ ] 集成到 Master 路由

**验收标准**:
- AC-02.2.1 ~ AC-02.2.2 全部通过
- 发送"帮我分析达人数据" → 返回分析报告

---

### 任务 3.4: 内容策划 Agent 实现

**负责人**: 后端 B
**工期**: 2 天（含缓冲 2.4 天）
**依赖**: 任务 2.4

- [ ] 创建 `backend/app/agents/content_planning.py`
  - 脚本策划 System Prompt
  - 直播脚本 / 种草文案 / 短视频脚本生成
- [ ] 脚本产出写入 content_scripts 表（status=draft）
- [ ] 集成到 Master 路由

**验收标准**:
- AC-02.3.1 ~ AC-02.3.2 全部通过
- 发送"帮我策划一期直播脚本" → 返回脚本内容

---

### 任务 3.5: 物流跟踪 Agent 实现

**负责人**: 后端 A
**工期**: 1.5 天（含缓冲 1.8 天）
**依赖**: 任务 2.4

- [ ] 创建 `backend/app/agents/logistics.py`
  - 物流跟踪 System Prompt
  - 物流查询能力（写入 logistics_tracking 表）
- [ ] 集成到 Master 路由

**验收标准**:
- AC-02.4.1 ~ AC-02.4.2 全部通过
- 发送"帮我查一下样品物流" → 返回物流状态

---

## 5. Phase 4: 审核确认与优化（第 4-5 周）

### 任务 4.1: 审核确认功能

**负责人**: 后端 A + 前端
**工期**: 2 天（含缓冲 2.4 天）
**依赖**: 任务 3.2, 3.4

**后端**:
- [ ] 实现 `POST /api/review/{id}/approve` — 审核通过
- [ ] 实现 `POST /api/review/{id}/reject` — 审核驳回
- [ ] 审核记录写入 review_approvals 表
- [ ] 驳回后 Master 自动追问修改方向

**前端**:
- [ ] ScriptCard 中通过/驳回按钮交互
- [ ] 驳回弹窗（填写驳回意见）
- [ ] Toast 提示审核结果

**验收标准**:
- AC-05.1.1 ~ AC-05.1.4 全部通过
- 点击"通过" → 按钮消失，Toast 提示"已通过"

---

### 任务 4.2: 计划确认功能

**负责人**: 后端 B + 前端
**工期**: 1.5 天（含缓冲 1.8 天）
**依赖**: 任务 2.4

**后端**:
- [ ] 复杂任务（3+ 步骤）拆解后，Master 先输出计划
- [ ] 等待用户确认后才执行

**前端**:
- [ ] PlanConfirmationModal: 展示执行计划，用户确认/取消

**验收标准**:
- 发送复杂任务 → 先展示计划 → 确认后执行

---

### 任务 4.3: 知识库文档上传

**负责人**: 后端 A
**工期**: 2 天（含缓冲 2.4 天）
**依赖**: 任务 1.1

- [ ] 实现 `POST /api/knowledge/upload` — 文件上传
- [ ] 支持 PDF / DOCX / HTML / TXT / MD 格式
- [ ] 文档解析 → 自适应 Chunk 策略 → 向量化 → 写入 ChromaDB
- [ ] 实现 `GET /api/knowledge/documents` — 文档列表

**验收标准**:
- 上传 PDF → 解析成功 → 可通过 RAG 检索到相关内容

---

### 任务 4.4: 集成测试与 Bug 修复

**负责人**: 全员
**工期**: 3 天（含缓冲 3.6 天）
**依赖**: 所有 Phase 1-4 任务

- [ ] 端到端测试：登录 → 对话 → 达人搜索 → 数据分析 → 审核
- [ ] 按 AC.md 验收标准逐项检查
- [ ] 修复发现的 Bug
- [ ] 性能验证（TTFT < 2s, API 响应 < 200ms）
- [ ] 前端 lint 检查 `npm run lint`
- [ ] 后端 ruff 检查 `ruff check backend/`

**验收标准**:
- 所有 AC 验收项通过
- 无 P0/P1 Bug

---

## 6. 缓冲周（第 5-6 周）

### 任务 5.1: 缓冲与联调

**工期**: 5 天

- [ ] 前后端联调
- [ ] 未完成任务的收尾
- [ ] 性能优化
- [ ] 文档完善
- [ ] 演示环境部署

---

## 7. 任务依赖关系图

```
Phase 1: 基础设施
  1.1 数据库表 ──┬── 1.2 对话管理 API ──┬── 2.5 消息持久化
                 │                      │
  1.3 前端骨架 ──┼── 1.4 API 客户端     │
                 │                      │
                 │                      │
Phase 2: 核心对话                       │
  2.1 登录注册页 ←── 1.3, 1.4           │
  2.2 对话页     ←── 1.3, 1.4, 2.1     │
  2.3 对话历史   ←── 2.2               │
  2.4 Master     ←── 1.1 ──────────────┤
                                       │
Phase 3: Agent 能力                     │
  3.1 达人搜索   ←── 2.4               │
  3.2 内联卡片   ←── 2.2, 3.1          │
  3.3 数据分析   ←── 2.4               │
  3.4 内容策划   ←── 2.4               │
  3.5 物流跟踪   ←── 2.4               │
                                       │
Phase 4: 审核优化                       │
  4.1 审核确认   ←── 3.2, 3.4          │
  4.2 计划确认   ←── 2.4               │
  4.3 知识库     ←── 1.1               │
  4.4 集成测试   ←── 全部 ─────────────┘
```

---

## 8. 工时估算

| 阶段 | 任务数 | 原始工时 | 含缓冲 (×1.2) |
|------|--------|---------|---------------|
| Phase 1 | 4 | 8 天 | 9.6 天 |
| Phase 2 | 5 | 13 天 | 15.6 天 |
| Phase 3 | 5 | 11.5 天 | 13.8 天 |
| Phase 4 | 4 | 8.5 天 | 10.2 天 |
| Buffer | 1 | 5 天 | 5 天 |
| **合计** | **19** | **46 天** | **54.2 天 ≈ 6 周** |

---

## 9. 风险与应对

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| LLM 响应不稳定导致流式体验差 | 中 | 高 | 模型 fallback + 超时兜底 |
| 达人数据源不可用 | 中 | 中 | 本地 kol_profiles 表兜底 + 种子数据 |
| 前后端接口联调延期 | 低 | 中 | api-spec.yaml 先行，Mock 并行开发 |
| SSE 连接在复杂网络环境下中断 | 低 | 中 | 断流重连机制 + messageId 幂等 |
| 上下文爆炸导致 Agent 推理质量下降 | 中 | 中 | ContextAssembler 裁剪 + Token 预算控制 |

---

## 10. 文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 技术方案 | `docs/tech-spec.md` | 架构与技术选型 |
| API 定义 | `docs/api-spec.yaml` | OpenAPI 3.0 接口 |
| 数据库设计 | `docs/db-schema.sql` | 建表语句 |
| 产品需求 | `docs/PRD.md` | PRD v3.4 |
| 项目范围 | `docs/Scope.md` | Scope v3.4 |
| 验收标准 | `docs/AC.md` | AC v3.4 |