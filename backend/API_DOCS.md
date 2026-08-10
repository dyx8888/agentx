# AgentX 前端对接接口文档

## 概述

AgentX 后端提供完整的数字员工管理系统，包括用户认证、公司管理、数字员工创建、聊天交互、反馈收集和进化分析等功能。

**基础 URL**: `http://localhost:8000`
**认证方式**: JWT Bearer Token
**数据格式**: JSON

---

## 认证接口

### 用户注册
```http
POST /auth/users/register
```

**请求体**:
```json
{
  "username": "admin",
  "password": "password123",
  "company_name": "示例公司",
  "brand_name": "示例品牌",
  "category": "美妆",
  "platforms": ["抖音", "小红书"]
}
```

**响应**:
```json
{
  "message": "User registered successfully",
  "user_id": 1,
  "company_id": 1
}
```

### 用户登录
```http
POST /auth/token
```

**请求体**:
```json
{
  "username": "admin",
  "password": "password123"
}
```

**响应**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

### 获取当前用户信息
```http
GET /auth/users/me
Authorization: Bearer {token}
```

**响应**:
```json
{
  "id": 1,
  "username": "admin",
  "company_id": 1,
  "is_admin": true,
  "created_at": "2024-01-01T00:00:00"
}
```

---

## 公司管理接口

### 创建公司
```http
POST /admin/companies
Authorization: Bearer {token}
```

**请求体**:
```json
{
  "name": "新公司",
  "brand_name": "品牌名称",
  "category": "美妆",
  "platforms": ["抖音", "小红书"]
}
```

### 查看公司列表
```http
GET /admin/companies
Authorization: Bearer {token}
```

**响应**:
```json
{
  "companies": [
    {
      "id": 1,
      "name": "示例公司",
      "brand_name": "示例品牌",
      "category": "美妆",
      "platforms_json": "[\"抖音\", \"小红书\"]",
      "created_at": "2024-01-01T00:00:00"
    }
  ]
}
```

---

## 数字员工管理接口

### 创建数字员工
```http
POST /admin/agents
Authorization: Bearer {token}
```

**请求体**:
```json
{
  "name": "Amy",
  "description": "美妆博主搜索专家",
  "tools_json": "[\"search_kols\"]"
}
```

### 查看数字员工列表
```http
GET /admin/agents
Authorization: Bearer {token}
```

**响应**:
```json
{
  "agents": [
    {
      "id": 1,
      "company_id": 1,
      "name": "Amy",
      "description": "美妆博主搜索专家",
      "tools_json": "[\"search_kols\"]",
      "created_at": "2024-01-01T00:00:00"
    }
  ]
}
```

### 获取可用工具列表
```http
GET /admin/tools
Authorization: Bearer {token}
```

**响应**:
```json
{
  "tools": [
    {
      "name": "search_kols",
      "description": "搜索美妆博主",
      "module": "app.mcp_servers.kol_search_server",
      "function": "search_kols",
      "endpoint": "http://kol-search:8101/tools/search_kols"
    }
  ]
}
```

---

## 聊天接口

### 发送消息（流式返回）
```http
POST /chat/
Authorization: Bearer {token}
```

**请求体**:
```json
{
  "message": "帮我找3个美妆博主",
  "agent_name": "Amy",
  "company_context": "美妆品牌，主要在小红书和抖音平台"
}
```

**响应**: Server-Sent Events (SSE) 流

**事件类型**:
- `thinking`: 思考过程
- `tool_call`: 工具调用
- `tool_result`: 工具结果
- `text`: AI 回复文本
- `done`: 完成
- `error`: 错误信息

**SSE 事件格式**:
```
data: {"type": "thinking", "content": "我需要搜索美妆博主..."}
data: {"type": "tool_call", "tool": "search_kols", "params": {"category": "美妆", "count": 3}}
data: {"type": "tool_result", "result": [{"name": "博主1", "followers": 100000}]}
data: {"type": "text", "content": "我为您找到了3位优秀的美妆博主..."}
data: {"type": "done"}
```

**JavaScript 客户端示例**:
```javascript
const response = await fetch('/chat/', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    message: '帮我找3个美妆博主',
    agent_name: 'Amy'
  })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  
  const chunk = decoder.decode(value);
  const lines = chunk.split('\n');
  
  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const data = JSON.parse(line.slice(6));
      console.log('Event:', data.type, data.content || data);
    }
  }
}
```

---

## 反馈接口

### 提交反馈
```http
POST /feedback/
Authorization: Bearer {token}
```

**请求体**:
```json
{
  "agent_name": "Amy",
  "tool_name": "search_kols",
  "original_response": "我为您找到了3位美妆博主...",
  "user_feedback": "这些博主不太合适，需要更多粉丝量的",
  "rating": 3
}
```

**响应**:
```json
{
  "message": "Feedback submitted successfully",
  "feedback_id": 123
}
```

---

## 进化管理接口

### 查看进化报告
```http
GET /admin/evolution/report?days=7&min_feedback=5
Authorization: Bearer {token}
```

**响应**:
```json
{
  "reports": [
    {
      "agent_id": 1,
      "agent_name": "Amy",
      "company_id": 1,
      "modification_rate": 35.5,
      "total_feedback": 20,
      "modified_count": 7,
      "top_modified_tools": ["search_kols"]
    }
  ],
  "high_modification_agents": [
    {
      "agent_id": 1,
      "agent_name": "Amy",
      "modification_rate": 35.5,
      "top_modified_tools": ["search_kols"]
    }
  ],
  "analysis_period_days": 7
}
```

### 获取进化建议
```http
GET /admin/evolution/suggestions/{agent_id}
Authorization: Bearer {token}
```

**响应**:
```json
{
  "suggestions": [
    {
      "id": 1,
      "agent_id": 1,
      "tool_name": "search_kols",
      "suggestion_text": "建议优化搜索算法...",
      "created_at": "2024-01-01T00:00:00",
      "applied": false
    }
  ]
}
```

### 获取待审查列表
```http
GET /admin/evolution/reviews
Authorization: Bearer {token}
```

**响应**:
```json
{
  "reviews": [
    {
      "id": 1,
      "agent_id": 1,
      "agent_name": "Amy",
      "tool_name": "search_kols",
      "suggestion_text": "建议优化搜索算法...",
      "knowledge_entries": "[\"美妆博主搜索技巧\", \"粉丝量评估标准\"]",
      "prompt_changes": "在搜索时优先考虑粉丝量...",
      "status": "pending",
      "created_at": "2024-01-01T00:00:00"
    }
  ]
}
```

### 批准进化建议
```http
POST /admin/evolution/reviews/{review_id}/approve
Authorization: Bearer {token}
```

**响应**:
```json
{
  "message": "Review approved and changes applied successfully"
}
```

### 拒绝进化建议
```http
POST /admin/evolution/reviews/{review_id}/reject
Authorization: Bearer {token}
```

**响应**:
```json
{
  "message": "Review rejected successfully"
}
```

---

## 成本管理接口

### 获取成本汇总
```http
GET /admin/costs/summary?days=30
Authorization: Bearer {token}
```

**响应**:
```json
{
  "total_cost": 12.50,
  "total_requests": 150,
  "total_input_tokens": 45000,
  "total_output_tokens": 12000,
  "period_days": 30,
  "cost_by_model": [
    {
      "model_name": "deepseek",
      "total_cost": 8.50,
      "total_requests": 120,
      "total_input_tokens": 36000,
      "total_output_tokens": 9500
    },
    {
      "model_name": "gpt4o",
      "total_cost": 4.00,
      "total_requests": 30,
      "total_input_tokens": 9000,
      "total_output_tokens": 2500
    }
  ],
  "cost_by_agent": []
}
```

### 获取成本历史趋势
```http
GET /admin/costs/history?days=30
Authorization: Bearer {token}
```

**响应**:
```json
{
  "trend": [
    {
      "date": "2024-01-15",
      "daily_cost": 2.50,
      "daily_requests": 25,
      "daily_input_tokens": 7500,
      "daily_output_tokens": 2000
    },
    {
      "date": "2024-01-14",
      "daily_cost": 1.80,
      "daily_requests": 18,
      "daily_input_tokens": 5400,
      "daily_output_tokens": 1450
    }
  ],
  "period_days": 30
}
```

### 按模型查看成本
```http
GET /admin/costs/models/30
Authorization: Bearer {token}
```

**响应**:
```json
[
  {
    "model_name": "deepseek",
    "total_cost": 8.50,
    "total_requests": 120,
    "total_input_tokens": 36000,
    "total_output_tokens": 9500
  }
]
```

### 按 Agent 查看成本
```http
GET /admin/costs/agents/{agent_id}/30
Authorization: Bearer {token}
```

**响应**:
```json
[
  {
    "model_name": "deepseek",
    "total_cost": 3.20,
    "total_requests": 45,
    "total_input_tokens": 13500,
    "total_output_tokens": 3575
  }
]
```

### 获取今日成本
```http
GET /admin/costs/today
Authorization: Bearer {token}
```

**响应**:
```json
{
  "date": "2024-01-15",
  "total_cost": 2.50,
  "total_requests": 25,
  "total_input_tokens": 7500,
  "total_output_tokens": 2000
}
```

---

## 健康检查接口

### 服务健康状态
```http
GET /health
```

**响应**:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T00:00:00"
}
```

---

## 错误处理

### 标准错误响应格式
```json
{
  "detail": "错误描述信息"
}
```

### 常见错误码
- `401`: 未授权（token 无效或过期）
- `403`: 权限不足（需要管理员权限）
- `404`: 资源不存在
- `422`: 请求参数验证失败
- `500`: 服务器内部错误

---

## 开发调试

### API 文档
访问 `http://localhost:8000/docs` 查看 Swagger UI 自动生成的 API 文档

### 测试环境
- 主服务: `http://localhost:8000`
- KOL 搜索工具: `http://localhost:8101`
- 报告工具: `http://localhost:8104`

### 环境变量
参考 `.env.example` 文件配置必要的环境变量

---

## 注意事项

1. **认证**: 除了注册和登录接口，所有接口都需要在请求头中包含 `Authorization: Bearer {token}`
2. **公司隔离**: 普通用户只能访问自己公司的数据，管理员可以管理全公司数据
3. **流式响应**: 聊天接口使用 SSE 流式返回，需要客户端正确处理流数据
4. **错误处理**: 建议客户端统一处理各种错误状态码
5. **Docker 环境**: 在 Docker 环境中，工具服务调用使用服务名（如 `kol-search:8101`）

---

## 技术支持

如有对接问题，请检查：
1. 网络连接是否正常
2. JWT token 是否有效
3. 请求参数格式是否正确
4. 服务是否正常运行（健康检查接口）
