## Context

AgentX Platform 是一个基于 LangGraph + MCP 的电商品牌 AI 数字员工平台，包含 8 个专业 Agent。当前 Prompt 全部以 Python 字符串常量形式存在，缺少安全防线、要素不完整、无版本管理。对照提示词工程最佳实践文档（`提示词工程.docx`），需从 4 个层面、16 个改进点进行系统性升级。

### 现有状态

- **无防注入**：用户输入和系统指令直接混合在消息列表中，无 XML 边界隔离
- **无安全约束**：8 个 Agent System Prompt 中无数据隐私、广告法合规、业务边界的约束
- **要素缺失**：无受众定义、无 Few-shot 示例、CoT 未显式化
- **无治理**：无版本号、无注册表、无 API 查询当前运行版本
- **Meta Prompt 简陋**：进化引擎中的 LLM 分析 Prompt 只有 1 行 SystemMessage

### 约束

- 所有改动必须是**追加性质**，不删除现有代码
- 不改 8 个 Agent 的基础业务 Prompt 逻辑
- 不改业务流程控制流

## Goals / Non-Goals

**Goals:**
- 建立三层安全防线：前置关键词过滤（Pydantic 层）→ 指令边界隔离（Prompt 层）→ 健壮性增强（Prompt 层）
- 8 个 Agent Prompt 补齐受众定义、Few-shot 示例、CoT 显式指令
- 建立 Prompt 版本管理体系（运行时可见、API 可查）
- Meta Prompt 达到与业务 Prompt 同等的工程化标准

**Non-Goals:**
- 不修改 Agent 的基础业务逻辑
- 不引入新的外部依赖
- 不改变 LangGraph Agent 的执行流程
- 不修改数据库 schema
- 不改变现有 API 接口签名

## Decisions

### D1: 模块化拆分 vs 内联修改

**决策**：新建独立模块，在调用点引入

**理由**：
- `instruction_boundary.py`、`agent_robustness.py`、`output_spec.py`、`meta_prompt_standards.py` 各司其职
- 未来如果 Agent Prompt 迁移到 YAML 模板，这些模块不用改，直接引用
- 避免在每个 Agent/Node 中重复写同样的安全规则

**替代方案**：直接在 `agent.py` 的 `_build_system_prompt()` 中内联所有安全规则。被否决——790 行 `agent.py` 会膨胀到 1000+ 行，且 8 个 Agent 都要各自重复。

### D2: Pydantic field_validator vs FastAPI Middleware

**决策**：使用 Pydantic `@field_validator` 而非 FastAPI `BaseHTTPMiddleware`

**理由**：
- `input_filter.py` 只需要拦截包含用户文本的 Request body 字段（`message`、`task_description`），不需要拦截所有 HTTP 请求
- Pydantic 验证器在请求解析阶段执行，早于业务逻辑，且不需要处理 streaming body 问题
- 精确控制：只对 3 个 Request 模型的 3 个字段生效

**替代方案**：`BaseHTTPMiddleware`。被否决——需要 read request body（含 streaming 复杂性），且无法精准区分哪些路由需要检查。

### D3: 关键字过滤使用正则 vs 调用 LLM 判断

**决策**：使用精确正则匹配，不调用 LLM

**理由**：
- LLM 调用有延迟（500ms+）和成本，不适合做前置网关
- 攻击模式是固定的几个类别（角色切换、提示词泄露、越狱），正则足够覆盖
- 误杀有白名单兜底，漏报有 Prompt 层铁律兜底

### D4: enrich_system_prompt() 统一注入 vs 各 Agent 文件内联

**决策**：所有安全/兜底/拒答/优先级通过 `enrich_system_prompt()` 统一注入

**理由**：
- 6 个改进点（优先级分层、安全合规、兜底机制、拒答策略、输出规范）全部收敛到 `agent_robustness.py` 一个文件
- 后续修改安全规则只需改一处
- 调用点在 6 个文件中各加 1 行，改动量最小

### D5: 版本元数据放源码 vs 外部数据库

**决策**：版本元数据以 Python 常量放在每个 Prompt 模块源码中，运行期收集到内存注册表

**理由**：
- 源码即真理：Git 管理源码 = Git 管理版本
- 零额外依赖：不需要数据库表
- 启动时自动收集到 `PromptRegistry`（内存字典），API 查询 O(1)

## Risks / Trade-offs

| 风险 | 严重度 | 缓解措施 |
|------|--------|----------|
| 关键词过滤器误杀正常请求 | 中 | 3 组白名单保护（内容创作语境中的"扮演"、"脚本"等），可疑模式只记日志不拦截 |
| System Prompt 膨胀导致 Token 成本增加 | 低 | 新增 ~1800 tokens/请求，DeepSeek 价格约 $0.002/1K tokens，日均 1 万请求 ≈ $6-8 |
| 安全约束过于激进导致 Agent 拒绝正常的业务请求 | 低 | 三级粒度防御，Level 3 明确允许风格/格式调整；Few-shot 示例引导正向行为 |
| 测试用例中的 Prompt 字符串断言失效 | 低 | `test_collaboration.py` 等可能直接比较 Prompt 文本，需同步更新 |
| Meta Prompt 重写后进化建议质量不一定提升 | 低 | Few-shot 示例和置信度校准机制降低幻觉风险；测评流水线可持续监测 |