## Why

AgentX Platform 目前处于"能跑就行"的提示词工程化阶段。8 个 Agent 的 System Prompt 缺少安全防线（无防注入、无指令边界、无合规约束）、缺失关键要素（受众定义、Few-shot 示例、CoT 显式指令）、没有版本管理和自动化测评。对照提示词工程最佳实践，需要从安全底线 → 输出质量 → 工程化治理 → 进化闭环四个维度系统性升级。

## What Changes

### 第 1 轮：P0 安全防线
- 新建 `app/core/instruction_boundary.py`：三级防改写铁律 + XML 标签隔离系统指令与用户输入
- 新建 `app/middleware/input_filter.py`：前置关键词过滤 + Pydantic 验证器（硬拒绝/可疑/白名单）
- 新建 `app/core/agent_robustness.py`：统一注入优先级分层、安全合规、兜底机制、拒答策略
- 修改 `agent.py`、`chat.py`、`planner_node.py`、`executor_node.py`、`reflector_node.py`、`customer_service_engine.py`：挂载上述模块
- 修改 `chat.py` 的 `ChatRequest`、`agents.py` 的 `AgentChatRequest`、`tasks.py` 的 `CreateTaskRequest`：加 `@field_validator`

### 第 2 轮：P1 要素完善
- 修改 `agent.py`：CoT 显式化，Plan-and-Solve、Reflection 两种模式指令块重写
- 修改 8 个 Agent Prompt 文件：加入受众定义（角色 + 面向对象 + 说话口吻）、追加 Few-shot 示例块
- 新建 `app/core/output_spec.py`：统一输出规范（格式/质量/行为）
- 修改 `agent_robustness.py`：注入 OUTPUT_SPEC
- 修改 4 个 Agent Prompt 文件（brand_bd, cc, amy, smart_ad_delivery）："肯定优先"句式重写

### 第 3 轮：P2 工程化
- 修改 11 个 Prompt 相关模块（8 Agent + robustness + output_spec + boundary）：加 `PROMPT_VERSION` / `PROMPT_UPDATED` / `PROMPT_CHANGELOG` 元数据
- 新建 `app/core/prompt_loader.py`：PromptRegistry 运行时版本注册表 + PromptLoader 模板变量填充
- 修改 `agent.py`：加 `_auto_register_prompt_versions()` 启动注册
- 修改 `admin.py`：加 `GET /admin/prompts/versions` API 端点

### 第 4 轮：P3 进化闭环
- 新建 `app/core/meta_prompt_standards.py`：Meta Prompt 共享标准（角色/约束/格式/Few-shot）
- 修改 `suggester.py`：`_call_llm_for_suggestions()`、`_call_llm_for_single_result()` 重写
- 修改 `memory.py`：`_extract_patterns()`、`_extract_prompt_rules()` 重写
- 新建 `tests/evaluation/` 目录：测试用例 YAML + judge.py LLM-as-Judge 评判引擎 + runner.py 测评运行器

## Capabilities

### New Capabilities
- `agent-guard`: 安全防线能力 — 指令边界隔离、三级防改写铁律、前置关键词过滤、安全合规约束、兜底机制、拒答策略
- `prompt-quality`: 提示词要素完善 — 受众定义、Few-shot 示例体系、CoT 显式指令、输出规范统一、肯定优先句式
- `prompt-versioning`: 提示词工程化治理 — 版本元数据、PromptRegistry 注册表、版本查询 API
- `meta-prompt-quality`: Meta Prompt 标准化 — 进化引擎和记忆巩固中的 LLM 分析 Prompt 质量提升
- `prompt-evaluation`: 自动化测评流水线 — 测试用例 YAML、LLM-as-Judge 评判、报告生成

### Modified Capabilities
<!-- 无，这是全新项目层面首次引入提示词工程化体系 -->

## Impact

- **新建 6 个文件**：`app/core/instruction_boundary.py`、`app/middleware/input_filter.py`、`app/core/agent_robustness.py`、`app/core/output_spec.py`、`app/core/prompt_loader.py`、`app/core/meta_prompt_standards.py`
- **新建 4 个测试文件**：`tests/evaluation/cases/brand_bd.yaml` 等测试用例、`tests/evaluation/judge.py`、`tests/evaluation/runner.py`
- **修改 27 个文件**：`agent.py`、`chat.py`、`agents.py`、`tasks.py`、`admin.py`、`planner_node.py`、`executor_node.py`、`reflector_node.py`、`customer_service_engine.py`、`suggester.py`、`memory.py`、`agent_robustness.py`、8 个 Agent Prompt 文件
- **额外 Token 开销**：~1800 input tokens/请求（全部来自 Prompt 增强和安全模块注入）
- **零破坏性改动**：所有修改为追加性质，不删除任何现有代码，不改变业务流程控制逻辑
- **测试需适配**：如 `test_collaboration.py` 等测试中硬编码了 Prompt 内容或 mock 了 SystemMessage 构造，需要同步更新