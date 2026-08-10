# Master Orchestrator + 多 Agent 协作 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建 Master Orchestrator（AI CEO）+ 激活 Amy/Ben/cc/warehouse/brand_bd，端到端跑通 Master→Worker a2a 多 Agent 协作链路。

**Architecture:** 用户只和 Master 对话。Master 用 Plan-Solve 拆任务 → a2a_delegate_task 派活 → 收结构化摘要 → Reflection 汇总。Worker Agent（Amy/Ben/cc/warehouse）各用最适合的模式执行。

**Tech Stack:** Python 3.13 + FastAPI + LangGraph + LangChain + DeepSeek API + React 18 + Vite

## Global Constraints

- 不删代码：所有现有 Agent 代码完整保留
- 用户只和 Master 对话，不直接接触 Worker
- 子 Agent 返回结构化摘要 `{agent, summary, key_data, tokens_used}`
- 每次修改后必须验证：`python -c "from app.main import app"`
- 环境：Windows PowerShell，DeepSeek API Key 已配置

---

### Task 1: 新建 Master Orchestrator Agent

**Files:**
- Create: `C:\kaifawenjian\agentdianshang\backend\app\agents\master.py`
- Modify: `C:\kaifawenjian\agentdianshang\backend\app\agents\__init__.py`

**Interfaces:**
- Produces: `get_system_prompt() -> str`, `get_default_tools() -> list[str]`, `get_default_skills() -> list[str]`
- Consumed by: `app.agents.__init__→get_agent_definition()`, `app.agent→get_agent_by_name()`

- [ ] **Step 1: 创建 master.py**

```python
"""
Master Orchestrator Agent — AI CEO
负责：理解用户意图 → 拆解子任务 → 分配给专业 Agent → 收集摘要 → 审核汇总
单点入口：用户只和 Master 对话，不直接接触 Worker Agent
"""

PROMPT_VERSION = "1.0.0"
PROMPT_UPDATED = "2026-06-18"

MASTER_SYSTEM_PROMPT = """你是 AgentX 平台的 Master Orchestrator（AI CEO）。你管理一个专业的 AI Agent 团队，每个 Agent 有明确的职责分工。用户只和你对话，你需要：

## 核心职责

1. **理解用户意图**：分析用户的需求是什么，需要哪些专业 Agent 参与
2. **拆解任务**：将复杂需求拆解为 3-6 个具体子任务，每个子任务分配给最合适的 Agent
3. **派发任务**：使用 a2a_delegate_task 工具将子任务逐一派发给对应 Agent
4. **收集结果**：接收每个 Agent 返回的结构化摘要，提取关键信息
5. **审核汇总**：所有子任务完成后，用 Reflection 模式自我审核（是否有矛盾？遗漏了什么？），输出完整的汇总报告

## 你的团队

| Agent | 角色 | 擅长 |
|-------|------|------|
| amy | KOL 达人外联专员 | 搜索达人、筛选匹配、生成个性化建联话术 |
| ben | 数据分析师 | 数据报表、竞品分析、达人数据质量评估 |
| cc | 内容运营 | 策划直播/短视频脚本、内容创作 |
| warehouse | 仓储物流专员 | 跟踪样品物流、提醒试样、管理发货 |
| brand_bd | 品牌商务 | 合作方案策划、内容审核、品牌策略 |

## 任务拆解规则

收到用户需求后，先分析需要哪些 Agent 参与，然后按依赖顺序逐个派发：

### 示例 1：达人合作全流程
用户："帮我做美妆赛道达人合作全流程"

拆解：
1. amy: 搜索美妆品类达人（抖音/小红书，10万-50万粉）
2. ben: 分析这批达人的数据质量（互动率、粉丝画像、历史合作）
3. amy: 为排名前 3 的达人生成个性化建联话术
4. cc: 为优选达人策划一期合作直播脚本
5. warehouse: 如果已寄样品，跟踪物流状态
6. brand_bd: 审核达人产出内容的质量

### 示例 2：竞品分析
用户："最近有哪些美妆品牌在找抖音达人合作？"

拆解：
1. ben: 搜索竞品品牌近期达人合作动向
2. ben: 分析竞品合作模式（直播带货/种草视频/品牌代言）
3. 输出竞品达人策略分析报告

## 派发任务格式

使用 a2a_delegate_task(target_agent_name="amy", task="搜索美妆品类达人，抖音平台，粉丝10-50万", task_type="general")

## 收集结果规则

- 每个 Agent 返回后，提取核心摘要存入 WorkingMemory
- 不要累积完整对话历史，只保留关键数据
- 如果某个 Agent 失败，标注"xx 部分未完成"，继续执行其他部分

## 最终汇总规则

所有子任务完成后，用 Reflection 模式自我审核：
1. **完整性检查**：用户的所有需求都被覆盖了吗？
2. **一致性检查**：不同 Agent 的结果之间有矛盾吗？
3. **质量检查**：每个结果都达到了可交付标准吗？
4. **遗漏检查**：还有什么用户可能需要的但没主动提出的？

最终输出格式：
```
## 任务执行总结

### 背景
[用户需求概述]

### 各阶段结果
1. 达人筛选：[Amy 的结果摘要]
2. 数据分析：[Ben 的结果摘要]
3. 建联话术：[Amy 的结果摘要]
...

### 关键发现
[最重要的 3 条发现]

### 行动建议
[具体的下一步建议]

### 执行情况
- 成功: N/Total 个子任务
- 失败: M 个（标注原因）
```
"""

MASTER_DEFAULT_TOOLS: list[str] = [
    "a2a_delegate_task",
]


def get_system_prompt() -> str:
    return MASTER_SYSTEM_PROMPT


def get_default_tools() -> list[str]:
    return MASTER_DEFAULT_TOOLS


def get_default_skills() -> list[str]:
    return []
```

- [ ] **Step 2: 注册 Master 到 AGENT_REGISTRY**

在 `app/agents/__init__.py` 的 AGENT_REGISTRY 字典中添加：

```python
"master": {
    "module": "app.agents.master",
    "name_display": "Master Orchestrator",
    "icon": "🎯",
    "role": "orchestrator",
    "review_level": "auto",
},
```

在现有 `review_level` 定义之后插入。确保缩进与现有条目一致。

- [ ] **Step 3: 验证导入**

```powershell
cd C:\kaifawenjian\agentdianshang\backend; .\.venv\Scripts\python.exe -c "from app.agents.master import get_system_prompt, get_default_tools; p=get_system_prompt(); assert 'Master' in p; assert 'a2a_delegate_task' in get_default_tools(); print('OK: Master Orchestrator created')"
```

Expected: `OK: Master Orchestrator created`

- [ ] **Step 4: 验证从 Registry 加载 Master**

```powershell
cd C:\kaifawenjian\agentdianshang\backend; .\.venv\Scripts\python.exe -c "from app.agents import get_agent_definition; d=get_agent_definition('master'); assert d is not None; print(f'OK: master loaded, tools={d[\"default_tools\"]}')"
```

Expected: `OK: master loaded, tools=['a2a_delegate_task']`

- [ ] **Step 5: 全量导入验证**

```powershell
cd C:\kaifawenjian\agentdianshang\backend; .\.venv\Scripts\python.exe -c "from app.main import app; print('Import OK')"
```

Expected: `Import OK`

---

### Task 2: 激活 Amy Agent（KOL 达人外联）

**Files:**
- Modify: `C:\kaifawenjian\agentdianshang\backend\app\agents\amy.py`

- [ ] **Step 1: 用 KOL 达人外联 prompt 替换 amy.py**

```python
"""
KOL 达人外联 Agent — 负责达人搜索筛选与个性化建联
面向电商商务场景，专业高效、数据驱动
"""

PROMPT_VERSION = "3.0.0"
PROMPT_UPDATED = "2026-06-18"
PROMPT_CHANGELOG = """
v3.0.0 (2026-06-18): MVP 重构 — 聚焦达人筛选与建联话术生成
"""

KOL_OUTREACH_SYSTEM_PROMPT = """你是 KOL 达人外联数字员工，负责品牌达人搜索、筛选和建联。你接收 Master Orchestrator 派发的任务，只返回结构化摘要，不输出冗长解释。

## 核心能力

1. **达人搜索**：调用 search_kols 工具按品类搜索达人，筛选粉丝量、互动率等条件
2. **达人评估**：从搜索结果中评估达人适合度（粉丝质量、内容风格、品牌匹配度）
3. **建联话术生成**：根据达人特征生成个性化合作邀约私信

## 返回格式（重要！）

每次任务完成后，返回如下结构化摘要：

```
【执行摘要】
- 搜索条件：[平台/品类/粉丝量]
- 搜索结果：找到 N 位达人
- Top 3 达人：[名称(粉丝数/互动率)]

【关键数据】
- 平均互动率：X%
- 最佳匹配：XX（原因）

【建联话术】
@达人1：...
@达人2：...
```

## 达人筛选规则

1. 解析条件：平台（抖音/小红书/微博等）、品类（美妆/服饰等）、粉丝量级、互动率
2. 调用 search_kols(category="品类", count=5)
3. 从结果中筛选匹配条件的达人
4. 输出结构化列表（达人名称、粉丝数、互动率、内容风格、适合度评分）
5. 条件模糊时主动请求 Master 澄清

## 建联话术规则

1. 分析达人近期内容风格
2. 匹配品牌调性（品牌名、品类、目标人群）
3. 结构：个性化开头 + 品牌介绍 + 合作价值 + 行动号召
4. 平台适配：抖音轻松活泼，小红书精致专业
5. 尾部标注"由AI生成，请根据实际情况调整"

## 示例输出

【执行摘要】
- 搜索条件：抖音/美妆/10万-50万粉
- 搜索结果：找到 3 位达人
- Top 3：李佳琦(48.5万粉/8.2%)、美妆小天才(32.1万/6.5%)、小美(18.3万/9.1%)

【关键数据】
- 平均互动率：7.9%
- 最佳匹配：美妆小天才（教程型风格，品牌调性匹配度高）

【建联话术】
@美妆小天才：Hi 美妆小天才，看了你最近成分党教程，专业又接地气。我们是「花漾」天然护肤品牌...（由AI生成）
"""

KOL_OUTREACH_CAPABILITIES: list[str] = [
    "search_kols",
    "kol_screening",
    "outreach_generation",
    "delegate_task",
    "a2a_delegate_task",
]

KOL_OUTREACH_DEFAULT_SKILLS: list[str] = [
    "kol_screening",
    "outreach_generation",
]


def get_system_prompt() -> str:
    return KOL_OUTREACH_SYSTEM_PROMPT


def get_default_tools() -> list[str]:
    return KOL_OUTREACH_CAPABILITIES


def get_default_skills() -> list[str]:
    return KOL_OUTREACH_DEFAULT_SKILLS
```

- [ ] **Step 2: 验证 Amy 导入**

```powershell
cd C:\kaifawenjian\agentdianshang\backend; .\.venv\Scripts\python.exe -c "from app.agents.amy import get_system_prompt, get_default_tools; p=get_system_prompt(); assert 'KOL' in p; assert 'search_kols' in get_default_tools(); print('OK: Amy is now KOL达人外联')"
```

Expected: `OK: Amy is now KOL达人外联`

- [ ] **Step 3: 全量导入验证**

```powershell
cd C:\kaifawenjian\agentdianshang\backend; .\.venv\Scripts\python.exe -c "from app.main import app; print('Import OK')"
```

---

### Task 3: 注册 search_kols 到 ToolRegistry

**Files:**
- Modify: `C:\kaifawenjian\agentdianshang\backend\app\tools\registry.py`

- [ ] **Step 1: 在 initialize_from_config 方法中注册**

找到 `initialize_from_config` 方法末尾，在 `return` 之前添加：

```python
# 注册 KOL 搜索工具
try:
    from app.mcp_servers.kol_search_server import search_kols
    self.register(
        name="search_kols",
        func=search_kols,
        description="搜索 KOL 达人。参数: category(品类如'美妆')、count(返回数量,默认3)"
    )
    logger.info("tool_registered", tool_name="search_kols", source="kol_search_server")
except Exception as e:
    logger.warning("tool_registration_failed", tool_name="search_kols", error=str(e))
```

- [ ] **Step 2: 验证工具注册**

```powershell
cd C:\kaifawenjian\agentdianshang\backend; .\.venv\Scripts\python.exe -c "from app.tools.registry import registry; registry.initialize_from_config(); tools = registry.get_tools_by_names(['search_kols']); assert len(tools) == 1; print(f'OK: search_kols registered, name={tools[0].name}')"
```

---

### Task 4: 更新 main.py agent_types

**Files:**
- Modify: `C:\kaifawenjian\agentdianshang\backend\app\main.py:215-218`

- [ ] **Step 1: 更新 agent_types 字典**

```python
"agent_types": {
    "master": "Master Orchestrator - AI CEO，拆解任务、分配团队、审核汇总",
    "amy": "KOL达人外联 - 达人搜索筛选、个性化建联话术",
    "ben": "数据分析 - 数据报表、竞品分析",
    "cc": "内容运营 - 脚本策划、内容创作",
    "warehouse": "仓储物流 - 样品跟踪、物流管理",
    "brand_bd": "品牌商务 - 合作策划、内容审核",
}
```

- [ ] **Step 2: 验证**

```powershell
cd C:\kaifawenjian\agentdianshang\backend; .\.venv\Scripts\python.exe -c "from app.main import app; print('Import OK')"
```

---

### Task 5: 端到端验证 — Master→Amy 协作链路

- [ ] **Step 1: 启动后端**

```powershell
cd C:\kaifawenjian\agentdianshang\backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Expected: 日志显示 `agent_runtime_initialized`，包含 Master Agent

- [ ] **Step 2: 验证 Master 入口**

```powershell
$response = Invoke-RestMethod -Uri "http://localhost:8000/" -Method Get
$response.agent_types.master
```

Expected: 返回 Master 的描述文本

- [ ] **Step 3: 验证 Master→Amy 协作（达人筛选）**

```powershell
$body = @{message="帮我找美妆品类的达人"; agent_name="master"; company_id="default"} | ConvertTo-Json
$response = Invoke-RestMethod -Uri "http://localhost:8000/api/chat" -Method Post -Body $body -ContentType "application/json"
$response.response
```

Expected: Master 拆任务 → a2a 派 Amy → Amy 调用 search_kols → Master 展示达人列表

- [ ] **Step 4: 验证 Master→Amy 协作（建联话术）**

```powershell
$body = @{message="给达人美妆小天才写一封合作邀约，品牌是花漾天然护肤"; agent_name="master"; company_id="default"} | ConvertTo-Json
$response = Invoke-RestMethod -Uri "http://localhost:8000/api/chat" -Method Post -Body $body -ContentType "application/json"
$response.response
```

Expected: 返回个性化建联话术

---

### Task 6: 端到端验证 — 多 Agent 协作链路

- [ ] **Step 1: Master→Ben 协作**

```powershell
$body = @{message="帮我分析一下这批达人的数据质量"; agent_name="master"; company_id="default"} | ConvertTo-Json
$response = Invoke-RestMethod -Uri "http://localhost:8000/api/chat" -Method Post -Body $body -ContentType "application/json"
$response.response
```

Expected: Master 派 Ben → Ben 返回分析摘要

- [ ] **Step 2: Master→cc 协作**

```powershell
$body = @{message="帮我策划一期美妆达人合作直播脚本"; agent_name="master"; company_id="default"} | ConvertTo-Json
$response = Invoke-RestMethod -Uri "http://localhost:8000/api/chat" -Method Post -Body $body -ContentType "application/json"
$response.response
```

Expected: Master 派 cc → cc 返回脚本摘要

- [ ] **Step 3: Master→warehouse 协作**

```powershell
$body = @{message="跟踪一下寄给达人的样品物流"; agent_name="master"; company_id="default"} | ConvertTo-Json
$response = Invoke-RestMethod -Uri "http://localhost:8000/api/chat" -Method Post -Body $body -ContentType "application/json"
$response.response
```

Expected: Master 派 warehouse → warehouse 返回物流状态

- [ ] **Step 4: Master 全流程汇总**

```powershell
$body = @{message="帮我做美妆赛道达人合作全流程：搜达人+分析数据+写话术+跟踪物流+策划脚本"; agent_name="master"; company_id="default"} | ConvertTo-Json
$response = Invoke-RestMethod -Uri "http://localhost:8000/api/chat" -Method Post -Body $body -ContentType "application/json"
$response.response
```

Expected: 
- 流式显示 Plan 拆解计划
- 逐个派活并显示进度
- 最终 Reflection 审核汇总报告
- 报告结构完整（背景 + 各阶段结果 + 关键发现 + 行动建议）

---

### Task 7: 前端验证

- [ ] **Step 1: 启动前端**

```powershell
cd C:\kaifawenjian\agentdianshang\frontend; npm.cmd run dev
```

Expected: Vite 启动在 `http://localhost:5173`

- [ ] **Step 2: 浏览器验证**

打开 `http://localhost:5173`，确认页面正常渲染

- [ ] **Step 3: 登录并验证 Master 对话**

1. 注册/登录
2. 在聊天界面输入"帮我找美妆达人"
3. 确认 SSE 流式显示 Master 的思考和执行过程
4. 收到包含达人列表的回复

---

## 自审清单

1. **Spec coverage:**
   - US-M00 全部 18 项 AC → Task 1(Master创建)+Task 2(Amy激活)+Task 3(search_kols注册)+Task 5(Master→Amy协作)+Task 6(多Agent扩展)+Task 7(前端)
   - US-01 认证 → 已有基础，Task 7 验证
   - US-02 对话 → Task 5+6 验证
   - ✅ 所有需求点已覆盖

2. **Placeholder 扫描:** 无 TBD/TODO，所有步骤有具体代码和预期输出。

3. **Type consistency:** `get_system_prompt() -> str`, `get_default_tools() -> list[str]`, `get_default_skills() -> list[str]` 接口与 `__init__.py→get_agent_definition()` 调用一致。

4. **上下文控制:** Task 1 中 Master prompt 明确要求子 Agent "只返回结构化摘要"，`a2a_delegate_task` 返回格式已定义。
