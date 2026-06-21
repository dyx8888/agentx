## ADDED Requirements

### Requirement: API 通用约定

所有 API 端点 MUST 遵循以下统一约定，确保前后端对接一致性。

```
┌─────────────────────────────────────────────────────────────┐
│                     API 通用约定                              │
├─────────────────────────────────────────────────────────────┤
│  Base URL       /api/v1                                     │
│  认证方式        Bearer Token (JWT Access Token)             │
│  Content-Type   application/json (REST)                      │
│                  text/event-stream (SSE 流式)                  │
│  日期格式        ISO 8601 (UTC): 2026-05-27T10:30:00Z        │
│  分页参数        ?page=1&page_size=20                        │
│  分页响应格式    { "data": [...], "total": 100,               │
│                   "page": 1, "page_size": 20 }               │
└─────────────────────────────────────────────────────────────┘
```

#### 统一错误响应格式

```json
{
  "error": {
    "code": "AGENT_001",
    "message": "LLM 调用失败，请稍后重试",
    "detail": "模型网关返回 503 Service Unavailable"
  }
}
```

**错误码枚举**:

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `AUTH_001` | 401 | Access Token 过期或无效 |
| `AUTH_002` | 401 | Refresh Token 已吊销 |
| `AUTH_003` | 423 | 账号因多次失败尝试被锁定 |
| `COMPANY_001` | 403 | 无权访问该公司数据 |
| `AGENT_001` | 502 | LLM 调用失败 |
| `AGENT_002` | 400 | Agent 未配置 API Key |
| `AGENT_003` | 404 | Agent 不存在 |
| `TASK_001` | 404 | 任务不存在 |
| `TASK_002` | 400 | 任务状态不允许该操作 |
| `TASK_003` | 400 | 审核操作无效（已审核或非审核状态） |
| `CRED_001` | 400 | 平台凭证配置无效 |
| `CRED_002` | 400 | 加密密钥未初始化 |
| `RATE_001` | 429 | 请求频率超限 |
| `VALID_001` | 422 | 请求参数校验失败 |

#### Scenario: 前端统一处理错误
- **WHEN** 任何 API 返回非 2xx 状态码
- **THEN** 前端解析 `error.code` 展示用户友好提示→`error.message` 作为默认提示→`error.detail` 仅在开发模式显示

---

### Requirement: 认证相关 API

认证 API MUST 支持双 Token 机制（Access Token + Refresh Token），确保与 platform-security spec 一致。

#### POST /api/v1/auth/token（已有，需扩展）

**功能**: 用户登录，返回 Access Token + Refresh Token。

**Request** (OAuth2 表单):
```
POST /api/v1/auth/token
Content-Type: application/x-www-form-urlencoded

username=<string>&password=<string>
```

**Response** (200):
```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "dGhpc2lzYXJlZnJl...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

#### POST /api/v1/auth/refresh（新增，P0）

**功能**: 使用 Refresh Token 换取新的 Access Token。

**Request**:
```json
{
  "refresh_token": "dGhpc2lzYXJlZnJl..."
}
```

**Response** (200):
```json
{
  "access_token": "eyJhbGciOi...",
  "expires_in": 1800
}
```

**错误**: 401 AUTH_002（Token 已吊销或过期）

#### POST /api/v1/auth/logout（新增，P0）

**功能**: 吊销当前 Refresh Token。

**Request**: 无 Body（从 Bearer Token 识别用户，吊销该用户所有 Refresh Token）

**Response** (200):
```json
{
  "message": "已登出"
}
```

#### POST /api/v1/auth/register（扩展，阶段一）

**功能**: 自助注册企业账号。

**Request**:
```json
{
  "username": "zhangsan",
  "password": "SecurePass123!",
  "email": "zhangsan@example.com",
  "company_name": "美尚化妆品",
  "brand_name": "花西子",
  "category": "美妆",
  "platforms": ["抖音", "小红书", "淘宝"]
}
```

**Response** (201):
```json
{
  "user_id": 42,
  "company_id": 15,
  "message": "注册成功，请配置 LLM API Key 后开始使用"
}
```

#### Scenario: 自动刷新 Token
- **WHEN** 前端收到 401 且 Refresh Token 未过期
- **THEN** 前端自动调用 POST /api/v1/auth/refresh→获取新 Access Token→重试原请求→如果 Refresh Token 也失效则跳转登录页

---

### Requirement: 企业管理 API

#### GET /api/v1/companies（已有）

**功能**: 获取公司列表（平台 admin 返回全部，普通用户返回本公司）。

**Response** (200):
```json
{
  "data": [
    {
      "id": 1,
      "name": "美尚化妆品",
      "brand_name": "花西子",
      "category": "美妆",
      "platforms_json": "[\"抖音\",\"小红书\",\"淘宝\"]",
      "subscription_status": "subscribed",
      "created_at": "2026-05-01T08:00:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

#### GET /api/v1/companies/:id（已有）

**功能**: 获取公司详情。只能访问本公司（平台 admin 不受限）。

#### PUT /api/v1/companies/:id（已有）

**功能**: 更新公司信息。

**Request**:
```json
{
  "name": "美尚化妆品有限公司",
  "brand_name": "花西子",
  "category": "美妆",
  "platforms": ["抖音", "小红书", "淘宝", "拼多多"]
}
```

#### POST /api/v1/companies/:id/credentials（已有，需扩展）

**功能**: 配置平台 API 凭证。

**Request**:
```json
{
  "platform": "douyin",
  "app_key": "8251234567890",
  "app_secret": "abcdef1234567890abcdef1234567890",
  "shop_id": "12345678"
}
```

**Response** (200):
```json
{
  "platform": "douyin",
  "configured": true,
  "expires_at": "2027-05-27T00:00:00Z"
}
```

#### PUT /api/v1/companies/:id/llm-key（新增，阶段一）

**功能**: 配置企业自有 LLM API Key。

**Request**:
```json
{
  "provider": "deepseek",
  "api_key": "sk-xxxxxxxxxxxxxxxx",
  "base_url": "https://api.deepseek.com/v1"
}
```

#### GET /api/v1/companies/:id/llm-keys（新增，阶段一）

**功能**: 查看已配置的 LLM Key 列表（脱敏显示）。

**Response** (200):
```json
{
  "keys": [
    {
      "provider": "deepseek",
      "masked_key": "sk-****xxxx",
      "configured_at": "2026-05-20T10:00:00Z"
    },
    {
      "provider": "openai",
      "masked_key": "sk-****yyyy",
      "configured_at": "2026-05-21T14:00:00Z"
    }
  ]
}
```

#### Scenario: 配置平台凭证后验证连通性
- **WHEN** 企业主保存平台 API 凭证
- **THEN** 系统调用平台 API 的健康检查端点→验证凭证有效性→返回验证结果→凭证无效时提示但不阻止保存

---

### Requirement: Agent 管理 API

#### GET /api/v1/agents（已有，需扩展）

**功能**: 获取当前公司的 Agent 列表。

**Query Params**: `?role_type=brand_bd&is_active=true&page=1&page_size=20`

**Response** (200):
```json
{
  "data": [
    {
      "id": 1,
      "company_id": 1,
      "name": "品牌商务",
      "role_type": "brand_bd",
      "description": "负责达人筛选与营销合作",
      "tools": ["search_kols", "generate_outreach", "check_delivery_status"],
      "model_config": {
        "primary": "deepseek-v3",
        "complex": "deepseek-r1"
      },
      "review_level": "mandatory",
      "is_active": true,
      "status": "idle",
      "created_at": "2026-05-01T08:00:00Z"
    }
  ],
  "total": 3,
  "page": 1,
  "page_size": 20
}
```

#### POST /api/v1/agents（已有，需扩展）

**功能**: 创建 Agent（预设职位或自定义）。

**Request**:
```json
{
  "name": "直播运营",
  "role_type": "custom",
  "description": "负责直播全流程策划与执行",
  "tools": ["live_script_generator", "live_data_monitor"],
  "system_prompt": "你是一个专业的直播运营专家...",
  "model_config": {
    "primary": "deepseek-v3",
    "complex": "deepseek-r1"
  },
  "review_level": "mandatory"
}
```

#### PUT /api/v1/agents/:id/model-config（新增，阶段一）

**功能**: 独立配置 Agent 的模型策略。

**Request**:
```json
{
  "primary": "deepseek-v3",
  "fallback": "qwen-turbo",
  "complex": "deepseek-r1",
  "parameters": {
    "temperature": 0.7,
    "max_tokens": 4096
  }
}
```

#### PUT /api/v1/agents/:id/tools（新增，阶段四）

**功能**: 热插拔 Agent 工具集。

**Request**:
```json
{
  "tool_name": "search_kols",
  "enabled": true
}
```

#### PUT /api/v1/agents/:id/skills（新增，阶段四）

**功能**: 热插拔 Agent Skill。

**Request**:
```json
{
  "skill_name": "kol_screening",
  "enabled": false
}
```

#### Scenario: 创建自定义 Agent 后自动注册到 AgentRuntime
- **WHEN** 用户创建自定义 Agent
- **THEN** 系统生成 Agent 实例→注册到 LangGraph AgentRuntime→初始化工具和 Skill→Agent 立即可用

---

### Requirement: 任务管理 API

#### POST /api/v1/tasks（已有，需扩展）

**功能**: 创建任务（用户直接发起或 Agent 间协作）。

**Request**:
```json
{
  "target_agent_name": "品牌商务",
  "task_description": "帮我找美妆品类粉丝量10万以上的达人",
  "source_agent_id": null,
  "review_level": "mandatory",
  "priority": 3
}
```

**Response** (201):
```json
{
  "task_id": 128,
  "status": "pending",
  "review_level": "mandatory"
}
```

#### GET /api/v1/tasks（已有，需扩展）

**功能**: 获取任务列表，支持多维度筛选。

**Query Params**: `?status=pending&agent_name=品牌商务&review_level=mandatory&review_status=pending_review&page=1&page_size=20&sort=-created_at`

**Response** (200):
```json
{
  "data": [
    {
      "id": 128,
      "company_id": 1,
      "source_agent_id": null,
      "target_agent_name": "品牌商务",
      "task_description": "帮我找美妆品类粉丝量10万以上的达人",
      "status": "pending",
      "review_level": "mandatory",
      "review_status": "pending_review",
      "result": null,
      "error_message": null,
      "created_at": "2026-05-27T10:00:00Z",
      "completed_at": null
    }
  ],
  "total": 5,
  "page": 1,
  "page_size": 20
}
```

#### GET /api/v1/tasks/:id/steps（已有）

**功能**: 获取任务的步骤列表。

**Response** (200):
```json
{
  "task_id": 128,
  "steps": [
    {
      "step_id": 1,
      "name": "需求确认与达人搜索",
      "status": "completed",
      "result": "已搜索到 45 位匹配达人",
      "review_level": "auto"
    },
    {
      "step_id": 2,
      "name": "达人深度分析与排序",
      "status": "completed",
      "result": "已深度分析 Top 15 达人",
      "review_level": "auto"
    },
    {
      "step_id": 3,
      "name": "生成邀约话术",
      "status": "waiting_review",
      "result": "尊敬的李佳琦...",
      "review_level": "mandatory"
    }
  ]
}
```

#### POST /api/v1/tasks/:id/confirm（已有，需扩展）

**功能**: 审核任务步骤。

**Request**:
```json
{
  "step_id": 3,
  "action": "approve",
  "modified_content": null,
  "feedback": "话术很好，直接发送"
}
```

**action 枚举**: `approve` | `reject` | `modify`

#### GET /api/v1/tasks/review-queue（新增，阶段九）

**功能**: 获取当前用户的审核队列。

**Query Params**: `?review_level=mandatory&sort=urgency`

**Response** (200):
```json
{
  "mandatory_reviews": [
    {
      "task_id": 128,
      "task_description": "达人邀约话术审核",
      "agent_name": "品牌商务",
      "step_id": 3,
      "content_preview": "尊敬的李佳琦...",
      "waiting_since": "2026-05-27T10:05:00Z",
      "urgency": "normal"
    }
  ],
  "recommended_reviews": [...],
  "mandatory_count": 1,
  "recommended_count": 3,
  "overdue_count": 0
}
```

#### Scenario: 强制审核超时升级
- **WHEN** `mandatory` 审核项在 `created_at + 4h` 后仍为 `pending_review`
- **THEN** 系统自动推送 PWA 通知→Dashboard 红色高亮→`urgency` 字段变为 `overdue`

---

### Requirement: 对话（Chat）API

#### POST /api/v1/chat（已有，需扩展）

**功能**: 与 Agent 进行对话，SSE 流式返回。

**Request**:
```json
{
  "message": "帮我分析上周的GMV数据",
  "agent_id": "1",
  "agent_name": "数据分析",
  "company_id": "1",
  "session_id": "sess_abc123",
  "mode": "react"
}
```

**Response**: `text/event-stream` (SSE)

```
event: thinking
data: {"content": "正在调取上周经营数据..."}

event: tool_call
data: {"tool": "query_gmv_metrics", "params": {"date_range": "last_week"}, "status": "calling"}

event: tool_result
data: {"tool": "query_gmv_metrics", "result": {"total_gmv": 1523400, "trend": "up"}}

event: message
data: {"content": "上周总 GMV 为 152.34 万元，环比增长 12.5%。其中..."}

event: review_required
data: {"step_id": 3, "level": "mandatory", "message": "该分析报告需要您审核后发布"}

event: done
data: {"task_id": 128}
```

**SSE 事件类型**:

| event | 说明 |
|-------|------|
| `thinking` | Agent 正在思考 |
| `tool_call` | Agent 正在调用工具 |
| `tool_result` | 工具调用结果返回 |
| `message` | Agent 输出的文本内容 |
| `error` | 出错（包含 error code） |
| `review_required` | 需要人工审核 |
| `done` | 对话完成 |

#### Scenario: 对话过程中断线重连
- **WHEN** SSE 连接断开
- **THEN** 前端携带 `session_id` 重新请求 POST /api/v1/chat→后端从 Redis 恢复会话历史→继续对话

---

### Requirement: 知识库 API

#### POST /api/v1/knowledge/upload（已有，需扩展）

**功能**: 上传企业知识文档。

**Request** (multipart/form-data):
```
file: <binary>
knowledge_type: "product_info" | "brand_style" | "sop" | "faq"
tags: ["产品", "花西子"]
```

**Response** (201):
```json
{
  "document_id": "doc_456",
  "filename": "产品手册_v3.pdf",
  "knowledge_type": "product_info",
  "chunks_count": 24,
  "status": "indexing"
}
```

#### GET /api/v1/knowledge/search（已有，需扩展）

**功能**: RAG 检索企业知识。

**Query Params**: `?query=退货政策&knowledge_type=faq&top_k=5`

**Response** (200):
```json
{
  "results": [
    {
      "document_id": "doc_456",
      "chunk_id": "chunk_12",
      "content": "支持7天无理由退货，退货邮费由买家承担...",
      "score": 0.92,
      "metadata": {
        "filename": "售后政策手册.pdf",
        "page": 3
      }
    }
  ],
  "query_time_ms": 45
}
```

#### Scenario: 客服 Agent 自动注入知识库
- **WHEN** 客服 Agent 处理客户咨询
- **THEN** 系统自动调用 GET /api/v1/knowledge/search→将检索到的知识块注入 Agent 的 System Prompt→客服 Agent 基于企业实际政策回复

---

### Requirement: 进化与学习 API

#### GET /api/v1/evolution/report（已有）

**功能**: 获取 Agent 进化报告。

**Response** (200):
```json
{
  "agent_id": 1,
  "agent_name": "品牌商务",
  "total_suggestions": 45,
  "applied_suggestions": 32,
  "pending_reviews": 5,
  "evolution_score": 87.5,
  "recent_improvements": [
    {
      "date": "2026-05-25",
      "description": "优化达人筛选话术模板，邀约接受率提升 12%"
    }
  ]
}
```

#### POST /api/v1/evolution/apply（已有）

**功能**: 应用进化建议。

**Request**:
```json
{
  "suggestion_ids": [12, 15, 18],
  "apply_to_skill": "kol_screening"
}
```

#### GET /api/v1/feedback/stats（已有）

**功能**: 获取用户反馈统计。

**Response** (200):
```json
{
  "total_feedback": 230,
  "average_rating": 4.2,
  "approval_rate": 0.85,
  "by_agent": {
    "品牌商务": { "average_rating": 4.5, "count": 60 },
    "内容运营": { "average_rating": 4.0, "count": 55 }
  },
  "trend": [
    { "week": "2026-W20", "average_rating": 3.9 },
    { "week": "2026-W21", "average_rating": 4.2 }
  ]
}
```

#### Scenario: 睡眠巩固自动触发
- **WHEN** 系统检测到低峰时段（凌晨 2:00-5:00）且短期记忆积压超过 100 条
- **THEN** 自动运行睡眠巩固→从 agent_short_term_memory 中筛选高价值记忆→压缩后写入 Milvus 长期记忆→更新 evolution_log

---

### Requirement: 订阅管理 API

#### GET /api/v1/subscription/plans（已有，需扩展）

**功能**: 获取可用订阅计划。

**Response** (200):
```json
{
  "plans": [
    {
      "id": 1,
      "name": "品牌商务专员",
      "role_type": "brand_bd",
      "type": "保障型",
      "description": "达人筛选、邀约管理、样品跟进、效果复盘",
      "price_per_month": 299,
      "capabilities": ["达人搜索", "话术生成", "效果报告"],
      "is_active": true
    }
  ]
}
```

#### POST /api/v1/subscription/hire（已有）

**功能**: 订阅职位（创建 Agent 实例）。

**Request**:
```json
{
  "plan_id": 1,
  "agent_name": "品牌商务",
  "auto_renew": true
}
```

#### POST /api/v1/subscription/cancel（已有）

**功能**: 取消订阅。

**Request**:
```json
{
  "plan_id": 1
}
```

---

### Requirement: Dashboard 数据 API

#### GET /api/v1/dashboard/overview（新增，阶段九）

**功能**: 获取 Dashboard 概览数据。

**Response** (200):
```json
{
  "online_agents": 5,
  "active_tasks": 12,
  "completed_today": 8,
  "pending_reviews": 3,
  "mandatory_reviews": 1,
  "alerts": [
    {
      "type": "sales_anomaly",
      "severity": "high",
      "message": "GMV 较昨日同期下降 35%",
      "agent_name": "数据分析",
      "created_at": "2026-05-27T09:00:00Z"
    }
  ]
}
```

#### GET /api/v1/dashboard/agents-status（新增，阶段九）

**功能**: 获取所有 Agent 实时状态。

**Response** (200):
```json
{
  "agents": [
    {
      "id": 1,
      "name": "品牌商务",
      "role_type": "brand_bd",
      "type": "保障型",
      "status": "working",
      "current_task": "达人筛选：美妆品类 Top 50",
      "token_used_today": 125000,
      "tasks_completed_today": 3,
      "model": "deepseek-v3",
      "health": "healthy"
    }
  ]
}
```

#### GET /api/v1/dashboard/analytics（新增，阶段九）

**功能**: 获取 Dashboard 图表数据。

**Query Params**: `?range=this_month&metric=tasks,gmv,tokens`

**Response** (200):
```json
{
  "tasks_trend": [
    { "date": "2026-05-01", "completed": 12, "failed": 1 },
    { "date": "2026-05-02", "completed": 15, "failed": 0 }
  ],
  "token_usage": [
    { "date": "2026-05-01", "prompt_tokens": 450000, "completion_tokens": 120000 }
  ],
  "agent_workload": [
    { "agent_name": "品牌商务", "tasks_completed": 45, "percentage": 30 },
    { "agent_name": "内容运营", "tasks_completed": 38, "percentage": 25 }
  ],
  "roi_summary": {
    "total_kol_cooperations": 24,
    "total_gmv_generated": 850000,
    "average_roi": 3.2
  }
}
```

#### GET /api/v1/dashboard/alerts（新增，阶段九）

**功能**: 获取告警列表。

**Query Params**: `?severity=high&acknowledged=false&page=1&page_size=20`

**Response** (200):
```json
{
  "alerts": [
    {
      "id": 101,
      "type": "sales_anomaly",
      "sub_type": "gmv_drop",
      "severity": "high",
      "message": "GMV 较昨日同期下降 35%",
      "detail": "当前小时 GMV ¥12,340 vs 昨日 ¥18,980",
      "agent_name": "数据分析",
      "acknowledged": false,
      "created_at": "2026-05-27T09:00:00Z"
    }
  ],
  "total": 3
}
```

#### Scenario: 告警推送到 Dashboard 和相关 Agent
- **WHEN** 数据分析 Agent 检测到库存异常（库存 < 安全阈值）
- **THEN** 生成告警记录→通过 WebSocket 推送到 Dashboard→同时通过 `schedule_task` 推送给品牌商务和仓储物流 Agent→Dashboard 顶部横幅红色闪烁

---

### Requirement: WebSocket 实时通信

系统 MUST 通过 WebSocket 提供实时状态更新和告警推送。

#### WS /api/v1/ws（新增，阶段九）

**功能**: WebSocket 长连接，用于实时推送。

**连接参数**: `?token=<jwt_access_token>`

**服务端推送事件**:

| event | 说明 | Payload |
|-------|------|---------|
| `agent_status_change` | Agent 状态变更 | `{"agent_id": 1, "status": "working", "current_task": "..."}` |
| `task_created` | 新任务创建 | `{"task_id": 128, "agent_name": "品牌商务"}` |
| `task_completed` | 任务完成 | `{"task_id": 128, "status": "completed"}` |
| `review_required` | 需要审核 | `{"task_id": 128, "step_id": 3, "level": "mandatory"}` |
| `alert` | 异常告警 | `{"type": "sales_anomaly", "severity": "high", "message": "..."}` |
| `token_usage_update` | Token 使用更新 | `{"agent_id": 1, "tokens_used": 5000}` |

**客户端心跳**: 每 30 秒发送 `{"type": "ping"}`，服务端回复 `{"type": "pong"}`。60 秒无心跳断开连接。

#### Scenario: 老板在 Dashboard 实时看到 Agent 状态变化
- **WHEN** 品牌商务 Agent 完成达人筛选进入话术生成阶段
- **THEN** WebSocket 推送 `agent_status_change`→Dashboard 中品牌商务卡片状态从"达人筛选"切换为"话术生成"

---

### Requirement: 管理员 API

#### GET /api/v1/admin/costs/summary（已有）

**功能**: 平台 Token 消耗汇总（平台 admin）。

**Response** (200):
```json
{
  "total_prompt_tokens": 12500000,
  "total_completion_tokens": 3200000,
  "total_companies": 12,
  "active_companies": 10,
  "period": "this_month"
}
```

#### GET /api/v1/admin/audit-logs（新增，P0）

**功能**: 查询审计日志（平台 admin）。

**Query Params**: `?company_id=1&action=agent.create&from=2026-05-01&to=2026-05-27&page=1&page_size=50`

**Response** (200):
```json
{
  "data": [
    {
      "id": 5001,
      "company_id": 1,
      "user_id": 5,
      "username": "zhangsan",
      "action": "credential.update",
      "resource_type": "credential",
      "resource_id": "1",
      "detail": {"platform": "douyin", "field": "app_secret"},
      "ip_address": "192.168.1.100",
      "created_at": "2026-05-27T10:30:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 50
}
```

#### Scenario: 安全审计回溯
- **WHEN** 平台管理员需要调查某个敏感操作的时间线
- **THEN** 通过 GET /api/v1/admin/audit-logs 筛选 company_id + action + 时间范围→获取完整操作记录

---

### Requirement: 健康检查与系统状态

#### GET /api/v1/health（已有，需扩展）

**功能**: 系统健康检查。

**Response** (200):
```json
{
  "status": "healthy",
  "timestamp": "2026-05-27T10:30:00Z",
  "version": "1.0.0",
  "dependencies": {
    "database": "ok",
    "redis": "ok",
    "milvus": "ok",
    "model_gateway": "ok"
  }
}
```

**可能的 status 值**: `healthy` | `degraded` | `unhealthy`

---

### Requirement: Agent 间通信 API

#### POST /api/v1/a2a/delegate（已有）

**功能**: Agent 间委托（内部使用）。

**Request**:
```json
{
  "source_agent_name": "品牌商务",
  "target_agent_name": "内容运营",
  "task_description": "达人@李佳琦确认合作，需要定制短视频脚本",
  "context": {
    "product_name": "花西子空气蜜粉",
    "kol_name": "李佳琦",
    "selling_points": ["控油持妆", "轻薄透气"]
  }
}
```

**Response** (201):
```json
{
  "task_id": 129,
  "status": "pending",
  "message": "任务已派发给内容运营"
}
```

#### Scenario: 选品确认触发批量协作
- **WHEN** 企业主批准供应链选品师的新品选品报告
- **THEN** 系统自动调用三次 POST /api/v1/a2a/delegate→分别创建品牌商务（达人规划）、内容运营（新品内容策划）、智能投流（投放策略）三个 Task

---

### Requirement: API 版本与弃用策略

所有 API 路径 MUST 包含版本前缀 `/api/v1/`。当 API 需要不兼容变更时，SHALL 发布新版本 `/api/v2/`，旧版本至少保留 6 个月并标记 `Deprecation` 响应头。

#### Scenario: API 弃用通知
- **WHEN** 客户端调用已弃用的 API 端点
- **THEN** 响应头包含 `Deprecation: true` 和 `Sunset: Sat, 01 Jan 2027 00:00:00 GMT`→每 10 次调用记录一次警告日志

---

### Requirement: 当前端点与目标端点对照

| 端点 | 当前状态 | 目标状态 | 变更说明 |
|------|---------|---------|---------|
| `POST /api/v1/auth/token` | ✅ 已有 | 🔧 扩展 | 增加 refresh_token 返回 |
| `POST /api/v1/auth/register` | ✅ 已有 | 🔧 扩展 | 增加企业自助注册字段 |
| `POST /api/v1/auth/refresh` | ❌ 缺失 | 🆕 新增 | P0：双 Token 机制 |
| `POST /api/v1/auth/logout` | ❌ 缺失 | 🆕 新增 | P0：Token 吊销 |
| `GET/POST /api/v1/companies` | ✅ 已有 | 🔧 扩展 | 增加分页、LLM Key 管理 |
| `PUT /api/v1/companies/:id/llm-key` | ❌ 缺失 | 🆕 新增 | 阶段一 |
| `GET/POST/GET:id/PUT:ID/DEL:id /api/v1/agents` | ✅ 已有 | 🔧 扩展 | 增加 model_config, role_type, skills/tools toggle |
| `POST/GET/GET:id/DEL:id /api/v1/tasks` | ✅ 已有 | 🔧 扩展 | 增加 review_level, review_status, 审核队列 |
| `GET /api/v1/tasks/review-queue` | ❌ 缺失 | 🆕 新增 | 阶段九 |
| `POST /api/v1/chat` | ✅ 已有 | 🔧 扩展 | 增加 SSE 事件类型标准化 |
| `POST/GET /api/v1/knowledge` | ✅ 已有 | 🔧 扩展 | 增加 knowledge_type 分类 |
| `GET/POST /api/v1/evolution/*` | ✅ 已有 | ✅ 保持 | |
| `GET/POST /api/v1/feedback/*` | ✅ 已有 | ✅ 保持 | |
| `GET/POST /api/v1/subscription/*` | ✅ 已有 | ✅ 保持 | |
| `GET /api/v1/dashboard/*` | ❌ 缺失 | 🆕 新增 | 阶段九（3 个端点） |
| `WS /api/v1/ws` | ❌ 缺失 | 🆕 新增 | 阶段九 |
| `GET /api/v1/admin/audit-logs` | ❌ 缺失 | 🆕 新增 | P0 |
| `GET/POST /api/v1/a2a/*` | ✅ 已有 | ✅ 保持 | |
| `GET /api/v1/health` | ✅ 已有 | 🔧 扩展 | 增加依赖健康检查详情 |

**总结**: 已有 ~30 个端点 + 需扩展 10 个 + 新增 9 个 = 总共约 40 个端点。