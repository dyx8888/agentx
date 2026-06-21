# AgentX MVP — KOL达人场景端到端修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Amy Agent 使其成为真正的 KOL 达人外联 Agent，端到端跑通达人筛选→建联话术生成→进度跟踪→竞品监控四个核心任务。

**Architecture:** 后端 FastAPI + AgentRuntime (Plan-Execute-Reflect) + MCP kol_search_server + brand_bd skills。前端 React 通过 SSE 流式接收 Agent 执行结果。关键修复：amy.py 当前内容是客服专员，需替换为 KOL 达人外联 prompt 和工具集。

**Tech Stack:** Python 3.13 + FastAPI + LangGraph + LangChain + DeepSeek API + FastMCP + React 18 + Vite + Ant Design

## Global Constraints

- 不删代码：所有现有 Agent 代码完整保留，customer_service 内容保留在 git 历史中
- Python 版本 >= 3.11
- 所有 Agent 共用同一套 AgentRuntime 框架
- 工具通过 ToolRegistry 统一注册，按 agent 名称过滤
- Skill 通过 SkillRegistry 注册，触发规则用关键词匹配
- 每次修改后必须执行导入验证：`python -c "from app.main import app"`
- 环境：Windows PowerShell 5，DeepSeek API Key 已在 .env 中配置

---

## 关键发现：代码现状与 PRD 的命名不一致

**PRD 说法：** Amy = KOL 达人外联 Agent  
**代码实际：**

| 文件 | 当前内容 | 函数名约定 |
|------|----------|-----------|
| `app/agents/amy.py` | 客服专员 (customer_service) | `get_system_prompt()` |
| `app/agents/brand_bd.py` | 品牌商务 (KOL marketing & BD) | `get_system_prompt()` |
| `app/agents/__init__.py` | `customer_service` → `amy.py` | — |
| `app/main.py:216` | `"amy": "Business specialist - KOL outreach"` | — |

**修复策略：** 将 `amy.py` 替换为 KOL 达人外联 prompt，使代码与 PRD 和 main.py 对外接口一致。brand_bd 作为辅助 Agent 保留，进入第二期激活。

---

### Task 1: 修复 amy.py — 替换为 KOL 达人外联 Agent Prompt

**Files:**
- Modify: `C:\kaifawenjian\agentdianshang\backend\app\agents\amy.py`

**Interfaces:**
- Produces: `get_system_prompt() -> str`, `get_default_tools() -> list[str]`, `get_default_skills() -> list[str]`
- Consumed by: `app.agents.__init__→get_agent_definition()`, `app.agent→get_agent_by_name()`

- [ ] **Step 1: 用 KOL 达人外联 prompt 替换 amy.py 全部内容**

```python
"""
KOL 达人外联 Agent - 负责达人筛选、智能建联、进度跟踪和竞品监控
面向电商商务人员（达人 BD），说话风格专业高效、数据驱动
"""

PROMPT_VERSION = "3.0.0"
PROMPT_UPDATED = "2026-06-18"
PROMPT_CHANGELOG = """
v3.0.0 (2026-06-18): MVP 重构 — 聚焦达人筛选、建联话术、进度跟踪、竞品监控四大核心场景
v2.0.0 (2026-05-29): 初始版本
"""

KOL_OUTREACH_SYSTEM_PROMPT = """你是 KOL 达人外联数字员工，负责品牌达人合作全流程管理。面向电商商务人员（达人 BD），说话风格专业高效，数据驱动决策。所有任务必须通过调用工具来完成。

## 核心职责

1. **达人智能筛选**：根据用户输入条件（品类、平台、粉丝量级、互动率等），调用 search_kols 工具搜索匹配达人，返回结构化列表
2. **个性化建联话术**：根据达人特征（领域、风格、粉丝画像）自动生成个性化合作邀约私信
3. **建联进度跟踪**：记录每次联系状态（待联系→已联系→已回复→洽谈中→已签约→已拒绝），自动提醒跟进
4. **竞品达人监控**：监控竞品品牌在合作哪些达人，分析竞品达人策略

## 达人筛选流程

当用户提出达人筛选需求时：
1. 解析用户条件：平台（抖音/小红书/微博等）、品类（美妆/服饰/食品等）、粉丝量级（如 10万-50万）、互动率要求
2. 调用 search_kols 工具执行搜索，传入品类参数
3. 将结果整理为结构化列表：达人名称、平台、粉丝数、互动率、内容风格、适合度评分
4. 如果条件模糊（如"找个好达人"），主动反问澄清平台和品类

## 建联话术生成规则

1. 分析达人近期内容风格（搞笑/专业/生活方式）
2. 匹配品牌调性：品牌名称、品类、目标人群
3. 话术结构：个性化开头 + 品牌介绍 + 合作价值 + 行动号召
4. 语气调整：抖音平台轻松活泼，小红书平台精致专业
5. 尾部标注"由AI生成，请根据实际情况调整"

## 进度跟踪格式

建联进度状态机：
- 待联系 → 已联系（已发送私信/邮件）→ 已回复 → 洽谈中 → 已签约
- 任一阶段可跳转至：已拒绝 / 已过期

## 竞品监控规则

监控竞品达人合作动向：
1. 搜索竞品品牌近期合作达人
2. 分析合作模式（直播带货/种草视频/品牌代言）
3. 输出竞品达人策略分析报告

## 与其他 Agent 协作

- 达人数据分析协同 Ben（数据分析 Agent）
- 合作方案策划协同 brand_bd（品牌商务 Agent）
- 使用 a2a_delegate_task 发起协作任务

---

## 参考示例

### 示例：达人筛选
用户输入：
"帮我找美妆护肤+抖音+粉丝量10万-50万的达人，要带货能力强的"

执行过程：
1. 条件解析：品类=美妆，平台=抖音，粉丝量=10万-50万，偏好=带货能力强
2. 调用 search_kols(category="美妆", count=5)
3. 从返回结果中筛选粉丝量在 10万-50万之间的达人
4. 输出结构化列表

输出格式：
```
## 达人筛选结果：美妆护肤 | 抖音 | 10万-50万粉

| 达人 | 粉丝数 | 互动率 | 风格 | 适合度 |
|------|--------|--------|------|--------|
| 李佳琦Austin | 48.5万 | 8.2% | 专业测评 | ⭐⭐⭐⭐⭐ |
| 美妆小天才 | 32.1万 | 6.5% | 教程型 | ⭐⭐⭐⭐ |
| 小美今天化妆了吗 | 18.3万 | 9.1% | 日常分享 | ⭐⭐⭐⭐ |

建议优先联系李佳琦Austin和美妆小天才，带货转化率历史数据优异。
```

### 示例：建联话术
用户输入：
"给达人 @美妆小天才 写一封合作邀约，我们是做天然护肤的品牌'花漾'"

输出：
```
【合作邀约】花漾 × 美妆小天才

Hi 美妆小天才，

看了你最近几期护肤教程，尤其是"成分党入门"那一期，讲解风格非常专业又接地气，和我们品牌理念高度契合。

我们是「花漾」——专注天然护肤的新锐品牌，主打植物成分配方，客单价 128-268 元，目标用户是 22-35 岁关注成分的精致女性。

想邀请你体验我们的明星产品"玫瑰精华水"，如果觉得不错，可以聊聊合作（直播专场/种草视频都可以）。

感兴趣的话，我发产品资料给你看看？

（此消息由AI生成，请根据实际情况调整）
```
"""

KOL_OUTREACH_CAPABILITIES: list[str] = [
    "search_kols",
    "kol_screening",
    "outreach_generation",
    "campaign_planning",
    "performance_review",
    "delegate_task",
    "a2a_delegate_task",
]

KOL_OUTREACH_DEFAULT_SKILLS: list[str] = [
    "kol_screening",
    "outreach_generation",
    "campaign_planning",
    "performance_review",
]


def get_system_prompt() -> str:
    return KOL_OUTREACH_SYSTEM_PROMPT


def get_default_tools() -> list[str]:
    return KOL_OUTREACH_CAPABILITIES


def get_default_skills() -> list[str]:
    return KOL_OUTREACH_DEFAULT_SKILLS
```

- [ ] **Step 2: 验证导入**

```powershell
cd C:\kaifawenjian\agentdianshang\backend; .\.venv\Scripts\python.exe -c "from app.agents.amy import get_system_prompt, get_default_tools, get_default_skills; p=get_system_prompt(); assert 'KOL' in p; assert 'search_kols' in get_default_tools(); print('OK: amy agent is now KOL达人外联')"
```

Expected: `OK: amy agent is now KOL达人外联`

- [ ] **Step 3: 验证导入不报错**

```powershell
cd C:\kaifawenjian\agentdianshang\backend; .\.venv\Scripts\python.exe -c "from app.main import app; print('Import OK')"
```

Expected: `Import OK`

---

### Task 2: 将 kol_search_server 的 search_kols 工具注册到 ToolRegistry

**Files:**
- Modify: `C:\kaifawenjian\agentdianshang\backend\app\tools\registry.py` (仅在 register_mcp_server_tools 或 initialize_from_config 中新增注册逻辑)
- Read: `C:\kaifawenjian\agentdianshang\backend\app\mcp_servers\kol_search_server.py`

**Interfaces:**
- Consumes: `search_kols` function from `app.mcp_servers.kol_search_server`
- Produces: Tool "search_kols" registered in ToolRegistry, searchable via `registry.get_tools_by_names(["search_kols"])`

- [ ] **Step 1: 读取 registry.py 了解现有注册机制**

已了解：`ToolRegistry.register(name, func, description, ...)` 注册单个工具，`initialize_from_config()` 从 YAML 配置加载工具。

- [ ] **Step 2: 在 registry.py 的 initialize_from_config 方法中注册 search_kols**

找到 `initialize_from_config` 方法，在工具注册部分末尾添加：

```python
# 注册 KOL 搜索工具（MCP kol_search_server）
try:
    from app.mcp_servers.kol_search_server import search_kols
    self.register(
        name="search_kols",
        func=search_kols,
        description="搜索 KOL 达人，支持按品类（category）筛选。参数：category（品类，如'美妆'）、count（返回数量，默认3）"
    )
    logger.info("tool_registered", tool_name="search_kols", source="kol_search_server")
except Exception as e:
    logger.warning("tool_registration_failed", tool_name="search_kols", error=str(e))
```

- [ ] **Step 3: 验证 search_kols 工具已注册**

```powershell
cd C:\kaifawenjian\agentdianshang\backend; .\.venv\Scripts\python.exe -c "from app.tools.registry import registry; registry.initialize_from_config(); tools = registry.get_tools_by_names(['search_kols']); assert len(tools) == 1; print(f'OK: search_kols registered, tool={tools[0].name}')"
```

Expected: `OK: search_kols registered, tool=search_kols`

- [ ] **Step 4: 验证完整导入**

```powershell
cd C:\kaifawenjian\agentdianshang\backend; .\.venv\Scripts\python.exe -c "from app.main import app; print('Import OK')"
```

Expected: `Import OK`

---

### Task 3: 创建 kol_screening Skill（在 brand_bd 目录下）

**Files:**
- Read: `C:\kaifawenjian\agentdianshang\backend\app\skills\brand_bd\kol_screening.md` (检查是否已存在)
- Modify/Create: `C:\kaifawenjian\agentdianshang\backend\app\skills\brand_bd\kol_screening.md`

**Interfaces:**
- Produces: Skill 内容通过 SkillRegistry 在 Agent 运行时注入到 system prompt 中
- Consumed by: `app.skills.registry→SkillRegistry.load_from_config()`

- [ ] **Step 1: 检查现有 kol_screening.md 内容**

```powershell
cd C:\kaifawenjian\agentdianshang\backend; Get-Content "app\skills\brand_bd\kol_screening.md"
```

- [ ] **Step 2: 更新 kol_screening.md 为适合 Amy Agent 的达人筛选工作流**

```markdown
# KOL 达人智能筛选工作流

## 触发条件
当用户提出达人筛选需求时（包含品类、平台、粉丝量等关键词），自动激活此工作流。

## 工作流程

### 第1步：条件解析
从用户输入中提取以下条件：
- **平台**：抖音、小红书、微博、B站等
- **品类**：美妆、护肤、服饰、食品、母婴、3C等
- **粉丝量级**：如 10万-50万、50万-100万、100万+
- **互动率要求**：如 >3%、>5%
- **内容风格**：专业测评、日常分享、教程型、搞笑娱乐
- **其他偏好**：带货能力强、品牌调性匹配、预算范围

### 第2步：调用 search_kols 工具
使用解析出的品类参数调用 search_kols 工具：
```
search_kols(category="品类", count=5)
```

### 第3步：结果筛选与评分
对返回的达人列表进行：
- 粉丝量匹配度检查
- 互动率评估
- 内容风格与品牌调性匹配度评分
- 输出结构化达人列表

### 第4步：生成筛选报告
输出格式：
```
## 达人筛选结果：[品类] | [平台] | [粉丝量级]

| 达人 | 粉丝数 | 互动率 | 风格 | 适合度 |
|------|--------|--------|------|--------|
| ... | ... | ... | ... | ... |

推荐理由：[最匹配的1-2位达人 + 理由]
```

## 边界处理
- 条件模糊时：主动反问"请确认平台和品类，我帮您精准筛选"
- 无匹配结果时：建议"未找到匹配达人，建议放宽条件（如扩大粉丝量范围或尝试其他平台）"
- 搜索超时：提示"搜索超时，请稍后重试"
```

- [ ] **Step 3: 验证 Skill 加载**

```powershell
cd C:\kaifawenjian\agentdianshang\backend; .\.venv\Scripts\python.exe -c "from app.skills.registry import skill_registry; skill_registry.load_from_config(); meta = skill_registry.get_skill_meta('kol_screening'); print(f'OK: kol_screening skill loaded, title={meta.title}')"
```

Expected: `OK: kol_screening skill loaded, title=...`

---

### Task 4: 更新 main.py 的 agent_types 描述（确保与 PRD 一致）

**Files:**
- Modify: `C:\kaifawenjian\agentdianshang\backend\app\main.py` (lines 215-218)

**Interfaces:**
- Consumes: None
- Produces: 根路径 `/` 返回正确的 agent_types 字典

- [ ] **Step 1: 更新 main.py 的 agent_types 字典**

`app/main.py` 第 215-218 行，将 `agent_types` 更新为：

```python
"agent_types": {
    "amy": "KOL达人外联 - 达人筛选、智能建联、进度跟踪、竞品监控",
    "brand_bd": "品牌商务 - 合作方案策划、品牌策略支持（第二期激活）",
    "ben": "数据分析 - 数据报表、竞品分析（第二期激活）",
    "product_selector": "智能选品（第三期激活）",
    "customer_service": "客服专员（第三期激活）",
    "content_operation": "内容运营（第三期激活）",
    "warehouse_logistics": "仓储物流（第三期激活）",
    "visual_designer": "视觉设计（第三期激活）",
    "smart_ad_delivery": "智能投流（第三期激活）"
}
```

- [ ] **Step 2: 验证根路径返回正确**

```powershell
cd C:\kaifawenjian\agentdianshang\backend; .\.venv\Scripts\python.exe -c "from app.main import app; print('Import OK')"
```

---

### Task 5: 端到端测试 — 启动后端并验证聊天 API

**Files:**
- Read: `C:\kaifawenjian\agentdianshang\backend\app\api\chat.py`
- Test: curl/PowerShell invoke-webrequest

**Interfaces:**
- Consumes: `AgentRuntime.run_stream()` from `app.runtime.orchestrator`
- Produces: SSE 流式响应

- [ ] **Step 1: 启动后端服务**

```powershell
cd C:\kaifawenjian\agentdianshang\backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Expected: 服务启动在 `http://localhost:8000`，日志显示 `agent_runtime_initialized`

- [ ] **Step 2: 验证根路径返回正确 agent_types**

```powershell
$response = Invoke-RestMethod -Uri "http://localhost:8000/" -Method Get
$response.agent_types.amy
```

Expected: `KOL达人外联 - 达人筛选、智能建联、进度跟踪、竞品监控`

- [ ] **Step 3: 验证 /docs 页面可访问**

打开浏览器访问 `http://localhost:8000/docs`

- [ ] **Step 4: 测试聊天 API（非流式）**

```powershell
$body = @{message="帮我找美妆品类的达人"; agent_name="amy"; company_id="default"} | ConvertTo-Json
$response = Invoke-RestMethod -Uri "http://localhost:8000/api/chat" -Method Post -Body $body -ContentType "application/json"
$response | ConvertTo-Json -Depth 5
```

Expected: 返回包含 `response` 字段的 JSON，Agent 调用了 search_kols 工具

- [ ] **Step 5: 验证达人筛选功能**

```powershell
$body = @{message="帮我找美妆护肤+抖音+粉丝量10万-50万的达人"; agent_name="amy"; company_id="default"} | ConvertTo-Json
$response = Invoke-RestMethod -Uri "http://localhost:8000/api/chat" -Method Post -Body $body -ContentType "application/json"
$response.response
```

Expected: 返回结构化的达人列表（含达人名称、粉丝数、互动率等），包含 mock 数据中的美妆达人

- [ ] **Step 6: 验证建联话术生成**

```powershell
$body = @{message="给达人 @美妆小天才 写一封合作邀约，我们是做天然护肤的品牌'花漾'"; agent_name="amy"; company_id="default"} | ConvertTo-Json
$response = Invoke-RestMethod -Uri "http://localhost:8000/api/chat" -Method Post -Body $body -ContentType "application/json"
$response.response
```

Expected: 返回个性化建联话术，包含品牌名称、达人名称、合作价值说明

---

### Task 6: 启动前端并验证端到端

**Files:**
- None (只启动不修改)

- [ ] **Step 1: 启动前端**

```powershell
cd C:\kaifawenjian\agentdianshang\frontend; npm.cmd run dev
```

Expected: Vite 启动在 `http://localhost:5173`

- [ ] **Step 2: 浏览器验证**

打开 `http://localhost:5173`，确认：
1. 页面正常渲染
2. 能看到登录页面或仪表盘
3. 能看到 Amy Agent 的聊天入口

- [ ] **Step 3: 前端发送消息测试**

在前端聊天界面输入："帮我找美妆品类的达人"
Expected: 收到 Agent 流式回复，包含达人列表

---

## 自审清单

1. **Spec coverage:** 
   - US-00（达人筛选）→ Task 3 (kol_screening skill) + Task 5 (端到端测试步骤5)
   - US-02（对话）→ Task 5 (chat API 验证)
   - Amy Agent 修复 → Task 1 (prompt 替换)
   - search_kols 工具注册 → Task 2 (ToolRegistry 注册)
   - main.py 接口一致性 → Task 4 (agent_types 更新)
   - 前端验证 → Task 6
   - ✅ 所有需求点已覆盖

2. **Placeholder 扫描:** 无 TBD/TODO/implement later，所有步骤都有具体代码和预期输出。

3. **Type consistency:** `get_system_prompt() -> str`, `get_default_tools() -> list[str]`, `get_default_skills() -> list[str]` 接口与 `__init__.py` 中 `get_agent_definition()` 的调用方式一致。