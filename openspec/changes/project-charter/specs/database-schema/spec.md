## ADDED Requirements

### Requirement: 核心表结构——用户与公司

系统 MUST 维护完整的用户和公司表，作为多租户体系的基石。所有多租户表 MUST 包含 `company_id` 字段并通过外键关联到 `companies.id`。

#### companies 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 公司唯一标识 |
| `name` | `VARCHAR(100)` | NOT NULL | 公司名称 |
| `brand_name` | `VARCHAR(100)` | NOT NULL | 品牌名称 |
| `category` | `VARCHAR(50)` | NOT NULL | 所属品类（如"美妆""服饰""食品"） |
| `platforms_json` | `TEXT` | NOT NULL | 经营平台列表 JSON（如 `["抖音","小红书"]`） |
| `platform_credentials` | `TEXT` (EncryptedText) | NULLABLE | 平台 API 凭证加密存储（JSON 字符串） |
| `llm_api_key` | `TEXT` (EncryptedText) | NULLABLE | 企业自有 LLM API Key 加密存储 |
| `subscription_status` | `VARCHAR(20)` | DEFAULT 'inactive' | 订阅状态：inactive / subscribed / cancelled |
| `created_at` | `DATETIME` | DEFAULT NOW | 创建时间 |

**索引**: `id` (主键)

#### users 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 用户唯一标识 |
| `username` | `VARCHAR(50)` | UNIQUE, NOT NULL, INDEX | 用户名 |
| `email` | `VARCHAR(100)` | UNIQUE, NOT NULL, INDEX | 邮箱 |
| `password_hash` | `VARCHAR(255)` | NOT NULL | bcrypt 哈希后的密码 |
| `company_id` | `INTEGER` | FK→companies.id, NOT NULL | 所属公司 |
| `is_admin` | `BOOLEAN` | DEFAULT FALSE | 是否平台管理员 |
| `created_at` | `DATETIME` | DEFAULT NOW | 创建时间 |

**索引**: `id`, `username`, `email`, `(company_id, is_admin)`

#### Scenario: 新公司注册时自动创建用户
- **WHEN** 公司注册时提交公司信息 + 管理员账号
- **THEN** 系统在同一事务中创建 `companies` 记录和 `users` 记录（is_admin=False，公司内管理员通过 permissions 模块区分）

---

### Requirement: Agent 与任务相关表

系统 MUST 维护 Agent、Task、TaskStep 及相关配置表的完整结构。

#### agents 表（当前）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | Agent 唯一标识 |
| `company_id` | `INTEGER` | FK→companies.id, NOT NULL | 所属公司 |
| `name` | `VARCHAR(100)` | NOT NULL | Agent 名称 |
| `description` | `TEXT` | NOT NULL | 职责描述 |
| `tools_json` | `TEXT` | NOT NULL | 工具集配置 JSON |
| `created_at` | `DATETIME` | DEFAULT NOW | 创建时间 |

**待扩展字段**（阶段一实施）:

| 新增列 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| `role_type` | `VARCHAR(50)` | DEFAULT 'custom' | 职位类型：brand_bd / content_op / data_analyst / cs_specialist / warehouse_logistics / visual_designer / supply_selector / ad_delivery / custom |
| `system_prompt` | `TEXT` | NULLABLE | 自定义 System Prompt（覆盖预设） |
| `model_config` | `TEXT` | NULLABLE | JSON: `{"primary": "deepseek-v3", "fallback": "deepseek-r1", "complex": "deepseek-r1"}` |
| `review_level` | `VARCHAR(20)` | DEFAULT 'mandatory' | 默认审核级别 |
| `is_active` | `BOOLEAN` | DEFAULT TRUE | 是否启用 |
| `updated_at` | `DATETIME` | ON UPDATE NOW | 更新时间 |

**索引**: `id`, `(company_id, role_type)`

#### tasks 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 任务唯一标识 |
| `company_id` | `INTEGER` | FK→companies.id, NOT NULL | 所属公司 |
| `source_agent_id` | `INTEGER` | FK→agents.id, NULLABLE | 发起 Agent（NULL 表示用户直接发起） |
| `target_agent_name` | `VARCHAR(100)` | NOT NULL | 目标 Agent 名称（如"品牌商务"） |
| `task_description` | `TEXT` | NOT NULL | 任务描述 |
| `status` | `VARCHAR(20)` | DEFAULT 'pending' | pending / processing / completed / failed / cancelled |
| `review_level` | `VARCHAR(20)` | DEFAULT 'auto' | mandatory / recommended / auto |
| `review_status` | `VARCHAR(20)` | DEFAULT 'none' | pending_review / approved / rejected / modified / ignored |
| `result` | `TEXT` | NULLABLE | 任务执行结果 |
| `error_message` | `TEXT` | NULLABLE | 错误信息（status=failed 时填充） |
| `created_at` | `DATETIME` | DEFAULT NOW | 创建时间 |
| `completed_at` | `DATETIME` | NULLABLE | 完成时间 |

**索引**: `id`, `(company_id, status)`, `(company_id, review_level, review_status)`, `(target_agent_name, status)`

#### task_steps 表（新增，阶段五实施）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 步骤唯一标识 |
| `task_id` | `INTEGER` | FK→tasks.id, NOT NULL | 所属任务 |
| `step_order` | `INTEGER` | NOT NULL | 步骤序号 |
| `name` | `VARCHAR(200)` | NOT NULL | 步骤名称 |
| `status` | `VARCHAR(20)` | DEFAULT 'pending' | pending / processing / completed / failed / waiting_review |
| `review_level` | `VARCHAR(20)` | DEFAULT 'auto' | 本步骤的审核级别 |
| `result` | `TEXT` | NULLABLE | 步骤执行结果 |
| `reviewed_by` | `INTEGER` | FK→users.id, NULLABLE | 审核人 |
| `reviewed_at` | `DATETIME` | NULLABLE | 审核时间 |
| `created_at` | `DATETIME` | DEFAULT NOW | 创建时间 |
| `completed_at` | `DATETIME` | NULLABLE | 完成时间 |

**索引**: `(task_id, step_order)` UNIQUE

#### Scenario: 任务被拒绝后重新生成步骤
- **WHEN** 用户拒绝某个 task_step（action=reject）
- **THEN** 该步骤标记为 failed→Agent 重新生成该步骤→新步骤追加到 task_steps 表

---

### Requirement: 协作与通信相关表

系统 MUST 维护 Agent 间协作和通信的配置与记录表。

#### company_agent_tools 表（MCP 工具热插拔）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 记录 ID |
| `company_id` | `INTEGER` | FK→companies.id, NOT NULL | 所属公司 |
| `agent_name` | `VARCHAR(50)` | NOT NULL | Agent 名称 |
| `tool_name` | `VARCHAR(100)` | NOT NULL | 工具名称 |
| `enabled` | `BOOLEAN` | DEFAULT TRUE | 是否启用 |

**唯一约束**: `(company_id, agent_name, tool_name)`

#### company_agent_skills 表（Skill 热插拔）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 记录 ID |
| `company_id` | `INTEGER` | FK→companies.id, NOT NULL | 所属公司 |
| `agent_name` | `VARCHAR(50)` | NOT NULL | Agent 名称 |
| `skill_name` | `VARCHAR(100)` | NOT NULL | Skill 名称 |
| `enabled` | `BOOLEAN` | DEFAULT TRUE | 是否启用 |

**唯一约束**: `(company_id, agent_name, skill_name)`

#### task_board 表（任务看板）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 项目 ID |
| `company_id` | `INTEGER` | FK→companies.id, NOT NULL | 所属公司 |
| `project_name` | `VARCHAR(100)` | NOT NULL | 项目名称 |
| `task_description` | `TEXT` | NOT NULL | 任务描述 |
| `assigned_agent` | `VARCHAR(50)` | NOT NULL | 指派 Agent |
| `status` | `VARCHAR(20)` | DEFAULT 'pending' | pending / in_progress / done |
| `priority` | `INTEGER` | DEFAULT 2 | 优先级 1-5（1 最高） |
| `parent_task_id` | `INTEGER` | FK→task_board.id, NULLABLE | 父任务（子任务层级） |
| `result_summary` | `TEXT` | NULLABLE | 结果摘要 |
| `created_at` | `DATETIME` | DEFAULT NOW | 创建时间 |
| `updated_at` | `DATETIME` | DEFAULT NOW | 更新时间 |

---

### Requirement: 进化与学习相关表

系统 MUST 维护 Agent 进化、反馈和学习相关的记录表，支持 AI 自动进化。

#### evolution_log 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 记录 ID |
| `agent_id` | `INTEGER` | FK→agents.id, NOT NULL | 所属 Agent |
| `tool_name` | `VARCHAR(100)` | NULLABLE | 关联工具名称 |
| `suggestion_text` | `TEXT` | NOT NULL | 进化建议内容 |
| `applied` | `BOOLEAN` | DEFAULT FALSE | 是否已应用 |
| `created_at` | `DATETIME` | DEFAULT NOW | 创建时间 |

#### feedback 表（当前版本）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 反馈 ID |
| `agent_id` | `INTEGER` | FK→agents.id, NOT NULL | 所属 Agent |
| `tool_name` | `VARCHAR(100)` | NOT NULL | 工具名称 |
| `original_output` | `TEXT` | NOT NULL | 原始输出 |
| `human_edited_output` | `TEXT` | NULLABLE | 人工修改后输出 |
| `status` | `VARCHAR(20)` | DEFAULT 'pending' | pending / modified / approved |
| `created_at` | `DATETIME` | DEFAULT NOW | 创建时间 |

#### feedback_log 表（扩展版）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 反馈 ID |
| `user_id` | `INTEGER` | NULLABLE | 提交反馈的用户 |
| `company_id` | `INTEGER` | FK→companies.id, NOT NULL | 所属公司 |
| `agent_name` | `VARCHAR(50)` | NOT NULL | Agent 名称 |
| `task_type` | `VARCHAR(50)` | NOT NULL | 任务类型 |
| `original_output` | `TEXT` | NOT NULL | 原始输出 |
| `user_feedback` | `TEXT` | NULLABLE | 用户文字反馈 |
| `rating` | `INTEGER` | NULLABLE | 评分 1-5 |
| `corrected_output` | `TEXT` | NULLABLE | 修正后输出 |
| `created_at` | `DATETIME` | DEFAULT NOW | 创建时间 |

**索引**: `(company_id, agent_name, created_at DESC)`

#### skill_evolution_log 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 记录 ID |
| `skill_name` | `VARCHAR(100)` | NOT NULL | Skill 名称 |
| `version` | `VARCHAR(20)` | NOT NULL | 版本号 |
| `improvement_suggestion` | `TEXT` | NOT NULL | 改进建议 |
| `trigger_reason` | `TEXT` | NULLABLE | 触发原因 |
| `applied` | `BOOLEAN` | DEFAULT FALSE | 是否已应用 |
| `applied_at` | `DATETIME` | NULLABLE | 应用时间 |

#### user_lora 表（LoRA 微调记录）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 记录 ID |
| `user_id` | `INTEGER` | NOT NULL | 关联用户 |
| `company_id` | `INTEGER` | FK→companies.id, NOT NULL | 所属公司 |
| `lora_path` | `VARCHAR(255)` | NOT NULL | LoRA 权重文件路径 |
| `base_model` | `VARCHAR(100)` | NOT NULL | 基座模型 |
| `training_samples_count` | `INTEGER` | DEFAULT 0 | 训练样本数 |
| `last_trained_at` | `DATETIME` | NULLABLE | 最后训练时间 |
| `is_active` | `BOOLEAN` | DEFAULT TRUE | 是否启用 |

---

### Requirement: 缓存与分析相关表

系统 MUST 维护结果缓存、决策日志和行为记录表。

#### result_cache 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 缓存 ID |
| `company_id` | `INTEGER` | FK→companies.id, NOT NULL | 所属公司 |
| `project_id` | `INTEGER` | NULLABLE | 关联项目 |
| `agent_name` | `VARCHAR(50)` | NOT NULL | Agent 名称 |
| `task_type` | `VARCHAR(50)` | NOT NULL | 任务类型 |
| `input_summary` | `TEXT` | NOT NULL | 输入摘要 |
| `output_summary` | `TEXT` | NOT NULL | 输出摘要 |
| `key_data` | `TEXT` | NULLABLE | 关键数据 JSON |
| `file_paths` | `TEXT` | NULLABLE | 文件路径 JSON |
| `created_at` | `DATETIME` | DEFAULT NOW | 创建时间 |

**索引**: `(company_id, agent_name, task_type)`

#### decision_log 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 决策 ID |
| `company_id` | `INTEGER` | FK→companies.id, NOT NULL | 所属公司 |
| `project_id` | `INTEGER` | NULLABLE | 关联项目 |
| `agent_name` | `VARCHAR(50)` | NOT NULL | Agent 名称 |
| `decision_point` | `TEXT` | NOT NULL | 决策点描述 |
| `options_considered` | `TEXT` | NOT NULL | 候选选项 JSON |
| `chosen_option` | `VARCHAR(200)` | NOT NULL | 选定选项 |
| `reasoning` | `TEXT` | NULLABLE | 决策理由 |
| `outcome` | `VARCHAR(20)` | DEFAULT 'pending' | pending / success / failed |
| `created_at` | `DATETIME` | DEFAULT NOW | 创建时间 |

#### user_behavior 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 行为 ID |
| `user_id` | `INTEGER` | NULLABLE | 用户 ID |
| `company_id` | `INTEGER` | FK→companies.id, NOT NULL | 所属公司 |
| `action_type` | `VARCHAR(50)` | NOT NULL | 行为类型：chat / tool_call / feedback |
| `action_detail` | `TEXT` | NULLABLE | 行为详情 JSON |
| `session_id` | `VARCHAR(50)` | NULLABLE | 会话 ID |
| `created_at` | `DATETIME` | DEFAULT NOW | 创建时间 |

**索引**: `(company_id, user_id, created_at DESC)`, `(session_id)`

---

### Requirement: 订阅计费相关表

系统 MUST 维护订阅计划和企业订阅关系表。

#### subscription_plans 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 计划 ID |
| `name` | `VARCHAR(100)` | NOT NULL | 职位名称（如"品牌商务专员"） |
| `description` | `TEXT` | NULLABLE | 职位描述 |
| `price_per_month` | `FLOAT` | NOT NULL | 月费 |
| `capabilities` | `TEXT` | NULLABLE | 能力列表 JSON |
| `role_type` | `VARCHAR(50)` | NULLABLE | 对应 role_type |
| `is_active` | `BOOLEAN` | DEFAULT TRUE | 是否启用 |
| `created_at` | `DATETIME` | DEFAULT NOW | 创建时间 |

#### company_subscriptions 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 订阅 ID |
| `company_id` | `INTEGER` | FK→companies.id, NOT NULL | 所属公司 |
| `plan_id` | `INTEGER` | FK→subscription_plans.id, NOT NULL | 订阅计划 |
| `agent_name` | `VARCHAR(100)` | NOT NULL | 绑定的 Agent 名称 |
| `status` | `VARCHAR(20)` | DEFAULT 'active' | active / cancelled / expired |
| `start_date` | `DATETIME` | DEFAULT NOW | 开始时间 |
| `end_date` | `DATETIME` | NULLABLE | 到期时间 |
| `auto_renew` | `BOOLEAN` | DEFAULT FALSE | 是否自动续费 |
| `created_at` | `DATETIME` | DEFAULT NOW | 创建时间 |

**索引**: `(company_id, status)`

---

### Requirement: 安全相关新增表

系统 MUST 新增以下表以支持 platform-security spec 中定义的安全要求。

#### refresh_tokens 表（新增，阶段零 P0 实施）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | Token ID |
| `user_id` | `INTEGER` | FK→users.id, NOT NULL | 所属用户 |
| `token_hash` | `VARCHAR(255)` | UNIQUE, NOT NULL | Refresh Token 的 SHA-256 哈希 |
| `expires_at` | `DATETIME` | NOT NULL | 过期时间 |
| `revoked` | `BOOLEAN` | DEFAULT FALSE | 是否已吊销 |
| `created_at` | `DATETIME` | DEFAULT NOW | 创建时间 |
| `revoked_at` | `DATETIME` | NULLABLE | 吊销时间 |

**索引**: `(user_id, revoked)`, `(token_hash)`

#### login_attempts 表（新增，阶段零 P0 实施）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 记录 ID |
| `username` | `VARCHAR(50)` | NOT NULL | 尝试登录的用户名 |
| `ip_address` | `VARCHAR(45)` | NOT NULL | 登录 IP（IPv4/IPv6） |
| `success` | `BOOLEAN` | NOT NULL | 是否成功 |
| `created_at` | `DATETIME` | DEFAULT NOW | 尝试时间 |

**索引**: `(username, created_at DESC)`, `(ip_address, created_at DESC)`

#### audit_log 表（新增，阶段零 P0 实施）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 审计日志 ID |
| `company_id` | `INTEGER` | FK→companies.id, NOT NULL | 所属公司 |
| `user_id` | `INTEGER` | FK→users.id, NULLABLE | 操作用户 |
| `action` | `VARCHAR(100)` | NOT NULL | 操作类型（如 agent.create, task.approve, credential.update） |
| `resource_type` | `VARCHAR(50)` | NOT NULL | 资源类型（agent / task / credential / company） |
| `resource_id` | `VARCHAR(100)` | NULLABLE | 资源 ID |
| `detail` | `TEXT` | NULLABLE | 操作详情 JSON |
| `ip_address` | `VARCHAR(45)` | NULLABLE | 操作 IP |
| `created_at` | `DATETIME` | DEFAULT NOW | 操作时间 |

**索引**: `(company_id, created_at DESC)`, `(company_id, action, created_at DESC)`, `(user_id, created_at DESC)`

#### key_rotation_log 表（新增，阶段一实施）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 记录 ID |
| `company_id` | `INTEGER` | FK→companies.id, NOT NULL | 所属公司 |
| `key_type` | `VARCHAR(30)` | NOT NULL | 密钥类型：llm_api_key / platform_credential / encryption_key |
| `rotated_by` | `INTEGER` | FK→users.id, NULLABLE | 轮换操作人 |
| `rotated_at` | `DATETIME` | DEFAULT NOW | 轮换时间 |

**索引**: `(company_id, key_type, rotated_at DESC)`

---

### Requirement: Agent 工作记忆与上下文存储

系统 MUST 在数据库层支持 Agent 三层记忆系统的持久化。

#### agent_short_term_memory 表（新增，阶段六实施）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 记忆 ID |
| `company_id` | `INTEGER` | FK→companies.id, NOT NULL | 所属公司 |
| `agent_name` | `VARCHAR(50)` | NOT NULL | Agent 名称 |
| `memory_type` | `VARCHAR(30)` | NOT NULL | task_summary / user_preference / review_feedback / decision_pattern |
| `summary` | `TEXT` | NOT NULL | 记忆摘要（LLM 压缩后的文本） |
| `embedding` | `VECTOR(1536)` | NULLABLE | 向量嵌入（用于 RAG 检索） |
| `importance` | `FLOAT` | DEFAULT 0.5 | 重要性评分 0-1 |
| `access_count` | `INTEGER` | DEFAULT 0 | 被检索次数 |
| `last_accessed_at` | `DATETIME` | NULLABLE | 最后检索时间 |
| `created_at` | `DATETIME` | DEFAULT NOW | 创建时间 |
| `expires_at` | `DATETIME` | NULLABLE | 过期时间（短期记忆 TTL） |

**索引**: `(company_id, agent_name, memory_type)`, `(company_id, agent_name, importance DESC)`

#### Scenario: 睡眠巩固时迁移短期记忆到长期记忆
- **WHEN** 系统触发睡眠巩固（低峰时段）
- **THEN** 从 `agent_short_term_memory` 中筛选 importance > 0.7 且 access_count > 3 的记录→摘要压缩→插入 Milvus 长期记忆向量库→降低原记录的 importance

---

### Requirement: 平台 API 调用记录

系统 MUST 记录所有对外部电商平台 API 的调用，用于计费审计和故障排查。

#### platform_api_call_log 表（新增，阶段七实施）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 记录 ID |
| `company_id` | `INTEGER` | FK→companies.id, NOT NULL | 所属公司 |
| `platform` | `VARCHAR(30)` | NOT NULL | 平台：douyin / taobao / pdd / xiaohongshu / chanmama |
| `endpoint` | `VARCHAR(200)` | NOT NULL | API 端点路径 |
| `request_summary` | `TEXT` | NULLABLE | 请求摘要（不含敏感信息） |
| `response_code` | `INTEGER` | NULLABLE | HTTP 响应码 |
| `latency_ms` | `INTEGER` | NULLABLE | 响应延迟（毫秒） |
| `error_message` | `TEXT` | NULLABLE | 错误信息 |
| `created_at` | `DATETIME` | DEFAULT NOW | 调用时间 |

**索引**: `(company_id, platform, created_at DESC)`, `(platform, response_code)`

---

### Requirement: 统计与报告相关表

系统 MUST 维护 Token 消耗统计和每日汇总表。

#### token_usage_log 表（新增，阶段八实施）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 记录 ID |
| `company_id` | `INTEGER` | FK→companies.id, NOT NULL | 所属公司 |
| `agent_name` | `VARCHAR(50)` | NOT NULL | Agent 名称 |
| `model_name` | `VARCHAR(100)` | NOT NULL | 模型名称 |
| `prompt_tokens` | `INTEGER` | NOT NULL | 输入 Token 数 |
| `completion_tokens` | `INTEGER` | NOT NULL | 输出 Token 数 |
| `task_id` | `INTEGER` | FK→tasks.id, NULLABLE | 关联任务 |
| `created_at` | `DATETIME` | DEFAULT NOW | 记录时间 |

**索引**: `(company_id, created_at DESC)`, `(company_id, agent_name, created_at DESC)`

#### daily_usage_summary 表（新增，阶段八实施）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, AUTOINCREMENT | 汇总 ID |
| `company_id` | `INTEGER` | FK→companies.id, NOT NULL | 所属公司 |
| `date` | `DATE` | NOT NULL | 日期 |
| `total_tasks` | `INTEGER` | DEFAULT 0 | 任务总数 |
| `completed_tasks` | `INTEGER` | DEFAULT 0 | 完成任务数 |
| `total_prompt_tokens` | `INTEGER` | DEFAULT 0 | 总输入 Token |
| `total_completion_tokens` | `INTEGER` | DEFAULT 0 | 总输出 Token |
| `total_platform_api_calls` | `INTEGER` | DEFAULT 0 | 平台 API 调用次数 |

**唯一约束**: `(company_id, date)`

---

### Requirement: 数据库命名与约定规范

所有表和列 MUST 遵循以下命名和设计规范，确保 AI 和人类开发者产出一致的代码。

#### 命名规范
- **表名**: 小写 + 下划线分隔，复数形式（`users`, `companies`, `agents`, `tasks`）
- **列名**: 小写 + 下划线分隔（`company_id`, `created_at`）
- **主键**: 统一使用 `id`（INTEGER，自增）
- **外键**: `<referenced_table_singular>_id`（如 `company_id`）
- **时间戳**: `created_at`（创建时间）、`updated_at`（更新时间）、`completed_at`（完成时间）、`expires_at`（过期时间）
- **布尔值**: `is_<adjective>` 或 `<verb>_ed`（如 `is_active`, `revoked`）
- **JSON 文本**: `<name>_json`（如 `platforms_json`, `tools_json`）

#### 设计规范
- **禁止外键级联删除**: 所有外键不做 ON DELETE CASCADE，软删除由应用层控制
- **时间字段**: 统一使用 `DATETIME` 类型（PostgreSQL `TIMESTAMP`），应用层统一使用 UTC
- **加密字段**: 使用 `EncryptedText` 自定义类型（AES-256-GCM 加密，数据库层面不可读）
- **索引策略**: 所有 WHERE 高频列 + ORDER BY 列建组合索引，外键列默认建索引
- **迁移管理**: 使用 Alembic 管理所有 schema 变更，禁止手动修改表结构

#### Scenario: 新表创建时的规范检查
- **WHEN** 开发者提交包含新表定义的 PR
- **THEN** CI 自动检查表名和列名是否符合命名规范→检查外键是否缺少索引→检查是否包含 created_at 字段

---

### Requirement: ER 关系总览

系统 MUST 具备以下实体关系拓扑，确保 AI 开发者理解表间依赖。

```
┌──────────┐       ┌──────────┐       ┌──────────────────┐
│  users   │───┬──▶│ companies│◀──┬──│subscription_plans│
└──────────┘   │   └──────────┘   │   └──────────────────┘
               │        │         │           │
               │        │         │   ┌───────┴──────────┐
               │        │         └──▶│company_subscriptions│
               │        │             └──────────────────┘
               │        ▼
               │   ┌──────────┐
               └──▶│  agents  │◀─────────────┐
                   └──────────┘              │
                        │                    │
            ┌───────────┼───────────┐        │
            ▼           ▼           ▼        │
      ┌──────────┐┌──────────┐┌──────────┐  │
      │  tasks   ││ feedback ││evolution │  │
      └──────────┘│          ││  _log    │  │
           │      └──────────┘└──────────┘  │
           ▼                                │
      ┌──────────┐                          │
      │task_steps│  ┌───────────────────────┘
      └──────────┘  │
                    ▼
   ┌─────────────────────────────────────┐
   │  company_agent_tools                │
   │  company_agent_skills               │
   │  refresh_tokens      (users FK)     │
   │  login_attempts      (no FK)        │
   │  audit_log           (companies FK) │
   │  key_rotation_log    (companies FK) │
   │  token_usage_log     (companies FK) │
   │  daily_usage_summary (companies FK) │
   │  platform_api_call_log(companies FK)│
   │  agent_short_term_memory(companies) │
   │  task_board          (companies FK) │
   │  result_cache        (companies FK) │
   │  decision_log        (companies FK) │
   │  feedback_log        (companies FK) │
   │  skill_evolution_log (no FK)        │
   │  user_behavior       (companies FK) │
   │  user_lora           (companies FK) │
   └─────────────────────────────────────┘
```

#### Scenario: 跨表查询时自动 JOIN company_id
- **WHEN** 任何涉及多表的查询执行
- **THEN** 所有 JOIN 条件中 MUST 包含 `company_id` 等值条件，不允许仅通过 ID 关联而不校验 company_id

---

### Requirement: 当前表与目标表对照

当前 `database/models.py` 中已存在的表及变更计划：

| 表名 | 当前状态 | 目标状态 | 变更说明 |
|------|---------|---------|---------|
| `companies` | ✅ 已存在 | 🔧 需扩展 | 新增 `llm_config_json` 字段（阶段一） |
| `users` | ✅ 已存在 | ✅ 保持 | 无变更 |
| `agents` | ✅ 已存在 | 🔧 需扩展 | 新增 `role_type`, `system_prompt`, `model_config`, `review_level`, `is_active`, `updated_at` |
| `tasks` | ✅ 已存在 | 🔧 需扩展 | 新增 `review_level`, `review_status`, `error_message` |
| `task_steps` | ❌ 缺失 | 🆕 新增 | 阶段五实施 |
| `feedback` | ✅ 已存在 | ✅ 保持 | 作为旧版保留，新版用 `feedback_log` |
| `evolution_log` | ✅ 已存在 | ✅ 保持 | 无变更 |
| `subscription_plans` | ✅ 已存在 | 🔧 需扩展 | 新增 `role_type` 字段 |
| `company_subscriptions` | ✅ 已存在 | ✅ 保持 | 无变更 |
| `company_agent_tools` | ✅ 已存在 | ✅ 保持 | 无变更 |
| `company_agent_skills` | ✅ 已存在 | ✅ 保持 | 无变更 |
| `task_board` | ✅ 已存在 | ✅ 保持 | 无变更 |
| `result_cache` | ✅ 已存在 | ✅ 保持 | 无变更 |
| `decision_log` | ✅ 已存在 | ✅ 保持 | 无变更 |
| `feedback_log` | ✅ 已存在 | ✅ 保持 | 无变更 |
| `skill_evolution_log` | ✅ 已存在 | ✅ 保持 | 无变更 |
| `user_behavior` | ✅ 已存在 | ✅ 保持 | 无变更 |
| `user_lora` | ✅ 已存在 | ✅ 保持 | 无变更 |
| `refresh_tokens` | ❌ 缺失 | 🆕 新增 | P0：双 Token 认证 |
| `login_attempts` | ❌ 缺失 | 🆕 新增 | P0：登录安全 |
| `audit_log` | ❌ 缺失 | 🆕 新增 | P0：审计日志 |
| `key_rotation_log` | ❌ 缺失 | 🆕 新增 | 阶段一 |
| `agent_short_term_memory` | ❌ 缺失 | 🆕 新增 | 阶段六 |
| `platform_api_call_log` | ❌ 缺失 | 🆕 新增 | 阶段七 |
| `token_usage_log` | ❌ 缺失 | 🆕 新增 | 阶段八 |
| `daily_usage_summary` | ❌ 缺失 | 🆕 新增 | 阶段八 |

**总结**: 已有 17 张表 + 需扩展 5 张 + 新增 8 张 = 总共 25 张表。