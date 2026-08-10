## ADDED Requirements

### Requirement: 企业注册与入驻
平台 SHALL 支持新企业自助注册：填写公司名称、品牌名称、所属品类、经营平台（可多选），系统自动创建公司记录和默认 admin 账号。注册后企业主可邀请团队成员加入。

#### Scenario: 美妆品牌完成注册
- **WHEN** 新用户在注册页填写公司信息并提交
- **THEN** 系统创建公司、admin 用户，展示"选择订阅职位"引导页

### Requirement: 职位订阅与付费
平台 SHALL 支持按职位订阅付费。企业可选择订阅一个或多个职位（8 个职位各独立定价，增长型职位定价高于保障型）。当前阶段先实现订阅状态管理，付费对接远期完成。

#### Scenario: 企业选择订阅品牌商务和内容运营
- **WHEN** 企业主在职位订阅页面选择多个职位并确认
- **THEN** 系统创建订阅记录，自动初始化对应 Agent 实例，配置默认工具、Skill 和模型

### Requirement: 平台管理员后台
平台管理员（platform admin）MUST 有独立的管理后台，包含：公司列表管理、用户管理、订阅管理、系统用量监控。

#### Scenario: 管理员查看所有公司的 Token 消耗
- **WHEN** 平台管理员进入后台的"用量监控"页面
- **THEN** 系统展示每个公司的 Token 消耗排名和总量

### Requirement: 请求频率限制
平台 SHALL 对 API 请求实施频率限制，防止单个用户或公司过度消耗资源。默认限制：每用户每分钟 30 次普通请求、每公司每分钟 10 次 LLM 调用请求。

#### Scenario: 用户触发频率限制
- **WHEN** 某用户在一分钟内发送超过 30 次 API 请求
- **THEN** 系统返回 429 Too Many Requests，包含 Retry-After 头部

### Requirement: 健康检查端点
平台 MUST 提供 `/health` 端点，返回服务运行状态及各依赖（PostgreSQL、Redis、Milvus、模型网关）的健康状态。

#### Scenario: 容器编排检测服务健康
- **WHEN** Docker 健康检查请求 `/health` 端点
- **THEN** 系统返回 200 OK 和健康状态 JSON：`{"status": "healthy", "database": "ok", "redis": "ok", "milvus": "ok", "model_gateway": "ok"}`

### Requirement: 数据库备份
平台 SHALL 支持 PostgreSQL 自动和手动备份。通过 pg_dump 定时备份，备份文件保留最近 7 天。

#### Scenario: 每日自动备份执行
- **WHEN** 每日凌晨 2:00 触发备份任务
- **THEN** 系统生成带日期后缀的备份文件，删除 7 天前的旧备份

---

### Requirement: 企业自有 LLM API Key 管理

企业 MUST 能够在公司设置中配置自有 LLM API Key（加密存储），平台不承担 LLM 调用费用。支持配置多个模型提供商的 Key（DeepSeek、OpenAI、火山引擎等）。

#### Scenario: 企业配置 DeepSeek API Key
- **WHEN** 企业主在设置页面填入 DeepSeek API Key 并保存
- **THEN** 系统加密存储 Key→该企业所有 Agent 使用此 Key 调用 LLM→Key 不匹配时 Agent 报错提示

#### Scenario: 未配置 Key 时 Agent 行为
- **WHEN** 企业未配置任何 LLM API Key
- **THEN** Agent 在需要调用 LLM 时返回友好提示："请先在公司设置中配置 LLM API Key"，而非报技术错误

---

### Requirement: 每个 Agent 独立模型配置

企业 SHALL 能够为每个 Agent 独立选择使用的 LLM 模型，支持主模型和备选模型配置。不同 Agent 的工作复杂度和方向不同，允许差异化配置。

#### Scenario: 为品牌商务配置 DeepSeek-R1 为复杂策略模型
- **WHEN** 企业主在 Agent 设置中为品牌商务 Agent 选择「复杂策略模型=DeepSeek-R1」
- **THEN** 品牌商务在执行大型营销策划时自动切换为 DeepSeek-R1，日常任务使用主模型 DeepSeek-V3

#### Scenario: 新 Agent 使用默认配置
- **WHEN** 企业订阅新职位
- **THEN** 系统为该 Agent 配置推荐的默认模型组合，企业主可后续调整

---

### Requirement: 公司自定义 Agent

企业 SHALL 能够创建自定义 Agent（完全自定义 System Prompt + 工具集 + 模型配置），不受 8 个预设职位限制。自定义 Agent 可以是预设职位的变体或全新角色。

#### Scenario: 企业创建「直播运营」自定义 Agent
- **WHEN** 企业主在 Agent 管理页面点击「创建自定义 Agent」，填写名称/描述/System Prompt/工具集/模型配置
- **THEN** 系统创建 Agent 实例→注册到 AgentRuntime→企业主可以像使用预设 Agent 一样使用

#### Scenario: 自定义 Agent 参与协作
- **WHEN** 自定义 Agent 配置了与其他 Agent 的协作关系
- **THEN** 自定义 Agent 可以使用 schedule_task、CompanyContextBus 和所有标准协作机制

---

### Requirement: 电商平台 API 对接

平台 SHALL 支持主流电商平台的 API 真实对接。采用统一 PlatformAdapter 抽象 + 独立 Adapter 实现架构。企业提供自有平台 API Key，平台以企业身份调用。

**接入优先级**：
- P0：抖音开放平台（星图/罗盘）、蝉妈妈
- P1：淘宝开放平台（生意参谋）
- P2：拼多多开放平台、小红书开放平台

#### Scenario: 企业配置抖音平台凭证
- **WHEN** 企业主在设置页面填入抖音开放平台 API Key 和 Secret
- **THEN** 系统加密存储凭证→品牌商务 Agent 可使用此凭证调用抖音星图 API 搜索达人→数据分析 Agent 可使用抖音罗盘 API 获取经营数据

#### Scenario: 平台 API 不可用时的降级
- **WHEN** 平台 API 因限流或维护不可用
- **THEN** Adapter 自动降级为 Mock 数据或浏览器操控（Playwright）从网页抓取→Dashboard 提示「当前使用降级数据」

---

### Requirement: PostgreSQL 生产数据库

平台 MUST 直接使用 PostgreSQL 作为生产数据库，不再经过 SQLite 过渡期。数据库连接配置通过环境变量注入。

#### Scenario: 开发环境启动
- **WHEN** 开发者执行 docker-compose up
- **THEN** 自动启动 PostgreSQL 容器→初始化数据库→创建表结构→应用可用

---

### Requirement: Redis 生产部署

平台 MUST 部署 Redis 用于任务队列和缓存。Redis 承担两个核心角色：
- **任务队列**：替代内存队列，支持持久化、重试、死信队列
- **缓存层**：CompanyContextBus 热数据缓存、Agent 短期记忆缓存

#### Scenario: Agent 间任务通过 Redis 队列传递
- **WHEN** 品牌商务向内容运营 schedule_task
- **THEN** 任务写入 Redis Stream→内容运营的消费循环拉取任务→任务持久化，重启不丢失

---

### Requirement: Harness 工程标准

平台 MUST 遵循以下工程标准，所有 PR 合并前需通过 CI 检查：

- **类型检查**：mypy (Python) + TypeScript strict mode，pre-commit hook
- **Lint**：ruff (Python) + eslint (TypeScript)，CI 阻断
- **CI/CD**：GitHub Actions，PR 自动运行测试 + lint + typecheck + 安全扫描
- **安全扫描**：bandit (Python) + npm audit (前端)，CI 阻断高危漏洞
- **版本化 API**：所有 API 路径包含 `/api/v1/` 前缀
- **测试覆盖率**：核心模块 ≥80%，集成测试覆盖多公司隔离、Agent 协同、人机审核流程

#### Scenario: PR 提交触发 CI 流水线
- **WHEN** 开发者提交 PR
- **THEN** GitHub Actions 自动运行 ruff→mypy→eslint→pytest→bandit→npm audit→全部通过后方可合并
