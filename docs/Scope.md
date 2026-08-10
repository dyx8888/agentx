# Scope — AgentX Platform 项目范围

> **版本**: v3.4  
> **日期**: 2026-06-20  
> **架构**: 单一对话界面 — Master Orchestrator + 隐形 Worker Agent 协作  
> **设计哲学**: 对话即界面，Agent 是工具不是页面  
> **新增**: LLM API 调用工程化（Token 预算 / 流式输出 / 重试幂等 / 限流 / 结构化输出）+ 生产级架构（模型网关 / Prompt 版本管理 / 评测体系）+ Agent 架构选型 + 记忆系统优化 + 上下文工程（Context Assembler / 工具上下文 / 动态上下文 / Few-shot / 信噪比）

---

## 1. 本期范围总则

**本期目标**: 搭建以对话为核心的 AI 工作助手。用户打开一个聊天窗口，对 Master 说一句话，Master 自动调度背后专业 Agent 完成工作，结果直接呈现在对话中。

**核心原则**：
- 用户只和 Master 对话，Agent 对用户完全隐形
- 所有功能通过对话触发，不做独立功能页面
- 子 Agent 返回结构化摘要，防止 Master 上下文爆炸
- 不删除现有功能模块

---

## 2. 做什么（In Scope）

### 2.1 Must Have — 必须完成

| 编号 | 功能 | 可交付物 |
|------|------|----------|
| S-IN-01 | **单一对话界面** | 前端：登录页 + 对话页（唯一两个页面）。后端：Master 入口 `/api/chat` |
| S-IN-02 | **Master Orchestrator** | 新建 Master Agent，Plan-Solve 拆任务 + Reflection 汇总 |
| S-IN-03 | **达人搜索 Agent 激活** | 隐形 Agent，含 search_kols 工具，Master 自动路由触发 |
| S-IN-04 | **SSE 流式响应** | 前端打字机效果，实时展示 Master 思考和执行过程 |
| S-IN-05 | **内联产出物展示** | 达人列表、分析报告等以卡片形式嵌入对话流 |
| S-IN-06 | **用户注册与登录** | POST /api/auth/* 正常响应，JWT + bcrypt |
| S-IN-07 | **对话历史** | 左侧历史列表，支持切换和删除 |
| S-IN-08 | **RAG 检索增强生成** | HybridRetriever（BM25+向量+RRF+Reranker）、DataInjector 三层数据注入、EmbeddingService（BGE/M3E）、文档解析（PDF/Word/HTML/TXT） |
| S-IN-09 | **三层记忆系统** | 工作记忆（WorkingMemory，单次任务状态）、短期记忆（EpisodicMemory，PostgreSQL+Redis）、长期记忆（SemanticMemory，Milvus 向量库 + 睡眠巩固引擎） |
| S-IN-10 | **Query Rewrite 查询改写** | `QueryRewriter` 模块，4 种策略（MultiQuery / Decompose / HyDE / Self-Query），原始 query 始终参与召回，改写延迟 < 200ms |
| S-IN-11 | **自适应 Chunk 策略** | 按文档类型选择切分策略（标题层级 / Page-Level / 固定 / 结构 / Parent-Child），Chunk 质量校验（最小 ≥ 50T，最大 ≤ 5000T，标准差 ≤ 均值 50%） |
| S-IN-12 | **Top-K 三段式分层管理** | `recall_top_k`（30-100）→ `rerank_top_n`（5-10）→ `context_top_n`（3-6）独立控制，降低 Token 消耗和噪声 |
| S-IN-13 | **Token 预算管理** | 请求前估算 `input_tokens + reserved_output_tokens`，超预算按降级顺序（删除低相关片段 → 压缩历史 → 减少工具 Schema → 降低输出 → 切换模型 → 拒绝）处理 |
| S-IN-14 | **模型网关（最小可行版）** | `LLMGateway` 统一收口：统一入口 + 日志 + usage + fallback，后续补充路由/限流/审计 |
| S-IN-15 | **Context Assembler 上下文组装器** | 八步组装流程：加载约束 → 提取目标 → RAG 检索 → 记忆召回 → 工具选择 → 历史压缩 → 上下文排序 → Token 预算适配，为 Master Orchestrator 每次 LLM 调用组装高质量上下文 |

### 2.2 Should Have — 应该完成

| 编号 | 功能 | 可交付物 |
|------|------|----------|
| S-IN-16 | 数据分析 Agent 激活 | 隐形 Agent，用户说"分析数据"时自动触发 |
| S-IN-17 | 内容策划 Agent 激活 | 隐形 Agent，用户说"策划脚本"时自动触发 |
| S-IN-18 | 物流跟踪 Agent 激活 | 隐形 Agent，用户说"查物流"时自动触发 |
| S-IN-19 | 关键步骤审核确认 | Master 拆解复杂任务后展示计划，等待用户确认 |
| S-IN-20 | 能力引导快捷指令 | 输入框下方展示可点击的快捷指令 |
| S-IN-21 | **RAG 质量评估** | RAGEvaluator：Hit Rate@k、MRR、NDCG、MAP + ragas 生成评估 |
| S-IN-22 | **上下文工程** | `ContextEngineer` 模块：去重/相邻合并/压缩/排序/结构化组织，证据质量判断 |
| S-IN-23 | **证据边界生成约束** | Prompt 4 条规则（只基于上下文/不足时拒答/附来源标注/注意版本号），拒答/追问/升级人工机制 |
| S-IN-24 | **最小评估集建立** | 50-100 条高价值问题，覆盖 7 种类型，含 golden_answer + golden_context |
| S-IN-25 | **重试与幂等机制** | 指数退避 + 抖动，幂等 Key `tenantId:userId:conversationId:messageId:attemptGroup`，同一 message 只保留一个 final attempt |
| S-IN-26 | **限流分层策略** | 用户级（滑动窗口+日上限）、租户级（令牌桶+月预算）、模型级（并发信号量）、供应商级（全局令牌桶+熔断器） |
| S-IN-27 | **结构化输出校验** | JSON Schema 校验 + 4 级失败兜底（本地校验 → 轻量修复 → 降级 Schema → 人工兜底） |
| S-IN-28 | **结构化输出上线检查清单** | Schema 层/模型调用层/服务端执行层/降级层四层检查 + 5 大常见误区规避 |
| S-IN-29 | **记忆遗忘机制** | 权重衰减 `score = relevance × importance × e^(-λt)` + 冲突解决 + 定期 Vacuum 清理 |
| S-IN-30 | **CLAUDE.md 项目记忆** | 项目级 CLAUDE.md 记录技术栈、常用命令、架构决策、团队约定，Git 版本控制 |
| S-IN-31 | **Prompt 版本管理** | 5 对象模型（prompt_template / prompt_version / prompt_release / prompt_run / prompt_eval_result），支持灰度发布和快速回滚 |
| S-IN-32 | **评测体系** | 7 项指标（Context Recall / Precision / Faithfulness / Answer Relevancy / Tool Success Rate / Format Valid Rate / Cost per Success），评测闭环流程 |
| S-IN-33 | **System Prompt 持续校准** | 先最小 Prompt 测基线，再根据 failure case 逐条补规则，结构化 Markdown 组织，固化到文件 |
| S-IN-34 | **工具上下文设计规范** | 一个工具只做一件事，描述先讲边界（什么时候不该调用），参数描述给格式示例 |

### 2.3 Could Have — 可延后

| 编号 | 功能 | 说明 |
|------|------|------|
| S-IN-35 | 品牌商务 Agent 激活 | 内容审核 + 效果复盘 |
| S-IN-36 | 产出物导出（CSV/PDF） | 达人列表、报告导出 |
| S-IN-37 | / 命令快捷指令 | `/达人` `/分析` 等 |
| S-IN-38 | 多模态检索（CLIP） | 以图搜图，视觉设计 Agent 专用 |
| S-IN-39 | 程序性记忆 | Few-shot 缓存 + Prompt 优化 + LoRA 微调 |
| S-IN-40 | **AgenticRAG 智能检索编排** ⚠️ | 按 Agent 角色自动选择检索策略。**降级说明**：5 个 Agent 检索需求趋同，统一 Hybrid Search 管线已足够。仅在特定 Agent 检索失败率显著高于其他时评估引入 |
| S-IN-41 | **知识图谱 GraphRAG** ⚠️ | NetworkX 实体关系推理。**降级说明**：AgentX 核心场景以局部事实问答为主，不涉及多跳关系推理。GraphRAG 构建和维护成本极高。仅在 badcase 明确指向跨文档关系推理失败时评估引入 |
| S-IN-42 | **完整模型网关** | 在最小可行版基础上增加：多模型路由、智能 fallback、成本归因、审计日志、语义缓存 |

### 2.4 RAG 落地优先级（v3.3 新增）

> 基于 JavaGuide RAG 系列参考资料的生产调优优先级，结合 AgentX 实际场景

| 阶段 | 优先级 | 内容 | 触发条件 |
|------|--------|------|----------|
| **Phase 1** | P0 立即落地 | 数据治理 → 最小评估集 → Hybrid Search → Query Rewrite → Top-K 分层 → Rerank → 证据边界约束 | 基线能力，必须实现 |
| **Phase 2** | P1 验证后引入 | 自适应 Chunk → 上下文工程 → 版本追踪 → 评估集扩充 | Phase 1 稳定运行 2 周后 |
| **Phase 3** | P2 按需评估 | AgenticRAG / GraphRAG / 多模态检索 | 仅当 badcase 明确指向该技术要解决的问题 |

### 2.5 工程化能力落地优先级（v3.4 新增）

> 基于 LLM 运行机制 + API 调用工程实践 + AI 应用系统设计 + 大模型网关详解

| 阶段 | 优先级 | 内容 | 触发条件 |
|------|--------|------|----------|
| **Phase 1** | P0 立即落地 | Token 预算管理 → 模型网关最小可行版 → 结构化输出校验 → 流式输出基础配置 → **Context Assembler 上下文组装器** | 基线能力，必须实现 |
| **Phase 2** | P1 验证后引入 | 重试与幂等 → 限流分层 → 记忆遗忘机制 → CLAUDE.md 项目记忆 → Prompt 版本管理 → 评测体系 → **结构化输出上线检查清单** → **System Prompt 持续校准** → **工具上下文设计规范** | Phase 1 稳定后 |
| **Phase 3** | P2 按需扩展 | 完整模型网关（多模型路由/智能 fallback/成本归因/语义缓存） | 多模型/多供应商引入后 |

---

## 3. 不做什么（Out of Scope）

| 编号 | 功能 | 原因 |
|------|------|------|
| S-OUT-01 | **独立 Agent 面板/仪表盘** | 违背对话优先哲学，用户不需要 |
| S-OUT-02 | **推倒重写** | 现有代码架构质量高，增量建设 |
| S-OUT-03 | **单 Agent 聚焦模式** | 用户不需要知道谁是 Amy/Ben |
| S-OUT-04 | product_selector / visual_designer / ad_delivery 激活 | 第二/三期 |
| S-OUT-05 | Redis 集群 | SQLite + 内存缓存 MVP 足够 |
| S-OUT-06 | Milvus 向量数据库 | ChromaDB 本地模式 |
| S-OUT-07 | 移动端适配 | MVP 只做 Web |
| S-OUT-08 | 多语言/国际化 | 中文优先 |
| S-OUT-09 | 支付/计费系统 | 先验证价值 |
| S-OUT-10 | 删除任何现有文件 | 不删代码 |

---

## 4. 范围边界图

```
┌──────────────────────────────────────────────────────────────┐
│                    IN SCOPE（本期 MVP）                        │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  💬 单一对话界面（登录 → 对话）                             │ │
│  │                                                          │ │
│  │  ┌──────────────┬────────────────────────────────────┐  │ │
│  │  │  对话历史     │  Master 对话区                      │  │ │
│  │  │  · 达人搜索   │                                    │  │ │
│  │  │  · 数据分析   │  [内联产出物：达人列表/报告/脚本]     │  │ │
│  │  │  · 618 复盘   │                                    │  │ │
│  │  │              │  [输入框 + 能力引导]                 │  │ │
│  │  └──────────────┴────────────────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  🎯 隐形 Agent 能力池（用户不可见，Master 自动路由）        │ │
│  │                                                          │ │
│  │  达人搜索 · 数据分析 · 内容策划 · 物流跟踪 · 品牌商务       │ │
│  │                                                          │ │
│  │  每个 Agent 含：技能 + MCP 工具                            │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  👤 注册登录  │  💬 SSE 流式  │  ✅ 审核确认  │  📋 历史   │ │
│  └─────────────────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────────────────┤
│            OUT OF SCOPE（本期不做，代码保留）                    │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 独立 Agent 面板 · 仪表盘 · 任务管理页 · 报告中心页         │ │
│  │ product_selector · visual_designer · ad_delivery         │ │
│  │ 推倒重写 · 移动端 · 支付 · OAuth · CI/CD · 国际化         │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

---

## 5. 模块清单与本期状态

### 5.1 后端模块

| 模块 | 本期动作 |
|------|----------|
| **app/agents/master.py** | 🆕 新建 Master Orchestrator |
| app/agents/amy.py | ✏️ 替换为达人搜索 Agent prompt |
| app/agents/ben.py | ✅ 保留不变，本期激活（隐形） |
| app/agents/cc.py | ✅ 保留不变，本期激活（隐形） |
| app/agents/warehouse_logistics.py | ✅ 保留不变，本期激活（隐形） |
| app/agents/brand_bd.py | ✅ 保留不变（隐形） |
| app/tools/registry.py | ✏️ 注册 search_kols |
| app/api/chat.py | ✏️ Master 为唯一入口 |
| 其余后端模块 | ✅ 保留不变 |

### 5.2 前端模块

| 页面 | 本期动作 |
|------|----------|
| 登录页 | ✏️ 简化，保持现有 |
| 对话页 | 🆕 新建，唯一核心页面 |
| 其余页面 | ✅ 保留不变（代码不删，但导航中不展示） |

---

## 6. 成功标准

- [ ] Master Orchestrator Agent 创建成功
- [ ] 用户对 Master 说"帮我找美妆达人" → 达人列表出现在对话中
- [ ] 用户说"分析数据" → 分析报告出现在对话中
- [ ] 用户说"策划脚本" → 脚本出现在对话中，支持审核通过/驳回
- [ ] 用户说"查物流" → 物流状态出现在对话中
- [ ] 对话历史可切换、可删除
- [ ] 后端服务在 Windows 下正常启动
- [ ] 前端页面正常渲染