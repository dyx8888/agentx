## ADDED Requirements

### Requirement: 脚手架生成
系统SHALL提供CLI命令 `python -m app.cli create-agent <name>` 快速生成新Agent的模板代码。

#### Scenario: 创建新Agent
- **WHEN** 用户执行 `python -m app.cli create-agent data_analyst`
- **THEN** 系统在 `app/agents/data_analyst.py` 生成包含PROMPT_VERSION、CAPABILITIES、get_system_prompt()、get_default_tools()的模板

#### Scenario: 重复名称提示
- **WHEN** 用户尝试创建已存在的Agent名称
- **THEN** 系统提示 "Agent 'data_analyst' 已存在，使用 --force 覆盖"

### Requirement: 模板规范
生成的Agent模板SHALL包含：文件头注释、PROMPT_VERSION、PROMPT_UPDATED、PROMPT_CHANGELOG、SYSTEM_PROMPT、CAPABILITIES列表、DEFAULT_SKILLS列表、以及三个标准函数。

#### Scenario: 模板完整性
- **WHEN** 脚手架生成新Agent
- **THEN** 生成的文件包含 `get_system_prompt()`, `get_default_tools()`, `get_default_skills()` 三个函数

### Requirement: 任务分解工具
CLI SHALL支持 `decompose-task` 命令，调用LLM自动分解任务需求为任务树。

#### Scenario: 任务分解
- **WHEN** 用户执行 `python -m app.cli decompose-task "为新产品上市做营销推广"`
- **THEN** 系统输出任务树：根任务→子任务1（市场调研）→子任务2（内容创作）→子任务3（渠道投放），并标注串行/并行关系

#### Scenario: 任务依赖图生成
- **WHEN** 任务分解完成
- **THEN** 系统生成Mermaid格式的任务依赖图，显示任务间的前置关系和可并行执行的任务组

### Requirement: 角色划分向导
CLI SHALL提供交互式角色划分决策向导，根据任务特征推荐单Agent或多Agent架构。

#### Scenario: 推荐单Agent架构
- **WHEN** 任务特征为：工具集中（<5个）、领域单一、结构简单
- **THEN** 系统推荐"单Agent多工具"模式，并说明理由

#### Scenario: 推荐多Agent架构
- **WHEN** 任务特征为：跨领域（>3个领域）、工具异构（>10个）、结构复杂
- **THEN** 系统推荐"多Agent主从/分层"模式，并建议Agent数量

### Requirement: 生产化模板
脚手架生成的Agent SHALL包含生产化所需的默认配置：测试用例、错误处理、日志记录、迭代记录。

#### Scenario: 生成测试用例模板
- **WHEN** 脚手架创建新Agent `data_analyst`
- **THEN** 同时生成 `tests/evaluation/cases/data_analyst.yaml` 包含3个场景骨架

#### Scenario: 生成错误处理模板
- **WHEN** 脚手架生成工具函数
- **THEN** 每个工具函数包含 `try/except` 块 + `ToolResult.error()` 调用模板

#### Scenario: 生成日志记录点
- **WHEN** 脚手架生成Agent
- **THEN** Agent代码包含预设日志记录点：工具调用前/后、LLM调用前/后、异常捕获

#### Scenario: 迭代记录模板
- **WHEN** 脚手架生成Agent
- **THEN** CHANGELOG区域包含结构化模板：版本号、变更日期、变更内容、评测分数、备注