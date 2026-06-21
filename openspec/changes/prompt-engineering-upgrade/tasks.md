## 1. P0 — 安全防线：新建核心模块

- [ ] 1.1 新建 `app/core/instruction_boundary.py`：三级防改写铁律 + XML 标签包裹函数（`wrap_system_instructions` / `wrap_user_input` / `wrap_external_data`）+ 防御性空输入处理
- [ ] 1.2 新建 `app/middleware/input_filter.py`：`InputFilter` 类含硬拒绝/可疑/白名单三组正则 + `validate_message()` Pydantic 验证器入口
- [ ] 1.3 新建 `app/core/agent_robustness.py`：优先级分层/安全合规约束/兜底机制/拒答策略 + `enrich_system_prompt()` 统一注入函数

## 2. P0 — 安全防线：挂载到调用点

- [ ] 2.1 修改 `app/agent.py`：`_build_system_prompt()` 末尾调用 `wrap_system_instructions()` + `enrich_system_prompt()`；`build_system_message()` 同样包裹
- [ ] 2.2 修改 `app/api/chat.py`：`process_message()` 中 `HumanMessage` 构造处调用 `wrap_user_input()`；`_load_session_history()` 新增 `<previous_*_message role="reference">` 历史消息标记
- [ ] 2.3 修改 `app/api/chat.py` 的 `ChatRequest`：添加 `@field_validator('message')` 调用 `InputFilter.validate_message`
- [ ] 2.4 修改 `app/api/agents.py` 的 `AgentChatRequest`：添加 `@field_validator('message')` 调用 `InputFilter.validate_message`
- [ ] 2.5 修改 `app/api/tasks.py` 的 `CreateTaskRequest`：添加 `@field_validator('task_description')` 调用 `InputFilter.validate_message`
- [ ] 2.6 修改 `app/runtime/nodes/planner_node.py`：`SystemMessage` 调用 `wrap_system_instructions()` + `enrich_system_prompt()`；`HumanMessage` 调用 `wrap_user_input()`
- [ ] 2.7 修改 `app/runtime/nodes/executor_node.py`：同上
- [ ] 2.8 修改 `app/runtime/nodes/reflector_node.py`：同上
- [ ] 2.9 修改 `app/engines/customer_service_engine.py`：`_generate_reply()` 的 prompt 调用 `enrich_system_prompt()`

## 3. P1 — 要素完善：CoT 显式化

- [ ] 3.1 修改 `app/agent.py`：`_build_system_prompt()` 中的 Plan-and-Solve 指令块重写为三步显式推理（分析拆解→逐步执行→汇总输出）
- [ ] 3.2 修改 `app/agent.py`：`_build_system_prompt()` 中的 Reflection 指令块重写为三段式输出（初步结果→自我审查→最终版本）

## 4. P1 — 要素完善：受众定义（8 个 Agent）

- [ ] 4.1 修改 `app/agents/brand_bd.py`：角色后加 "面向品牌方老板和运营经理，说话风格专业、数据驱动、结论先行"
- [ ] 4.2 修改 `app/agents/cc.py`：角色后加 "面向品牌方内容团队和运营经理，说话风格创意驱动、可直接执行"
- [ ] 4.3 修改 `app/agents/ben.py`：角色后加 "面向品牌方决策层和运营经理，说话风格客观中立、数据说话、不渲染情绪"
- [ ] 4.4 修改 `app/agents/amy.py`：角色后加 "面向终端消费者，说话风格亲切自然、解决问题导向"
- [ ] 4.5 修改 `app/agents/warehouse_logistics.py`：角色后加 "面向品牌方运营团队和仓库管理员，说话风格简洁高效、流程导向"
- [ ] 4.6 修改 `app/agents/visual_designer.py`：角色后加 "面向品牌方设计和运营团队，说话风格规范导向、视觉可描述"
- [ ] 4.7 修改 `app/agents/product_selector.py`：角色后加 "面向品牌方采购和运营经理，说话风格分析驱动、风险意识强"
- [ ] 4.8 修改 `app/agents/smart_ad_delivery.py`：角色后加 "面向品牌方投放团队和运营经理，说话风格精准数据、量化表达"

## 5. P1 — 要素完善：Few-shot 示例体系（8 个 Agent）

- [ ] 5.1 修改 `app/agents/brand_bd.py`：追加达人筛选 Few-shot 示例（用户输入→分析过程→工具调用→输出表格→风险提示）
- [ ] 5.2 修改 `app/agents/cc.py`：追加短视频脚本 Few-shot 示例（平台适配→分镜表格→A/B/C三版对应）
- [ ] 5.3 修改 `app/agents/ben.py`：追加投放效果分析 Few-shot 示例（指标速览→异动分析→优化建议→预测）
- [ ] 5.4 修改 `app/agents/amy.py`：追加售后处理 Few-shot 示例（用户消息→客服回复→静默发送→AI标注）
- [ ] 5.5 修改 `app/agents/warehouse_logistics.py`：追加库存预警 Few-shot 示例
- [ ] 5.6 修改 `app/agents/visual_designer.py`：追加主图生成 Few-shot 示例
- [ ] 5.7 修改 `app/agents/product_selector.py`：追加选品评估 Few-shot 示例
- [ ] 5.8 修改 `app/agents/smart_ad_delivery.py`：追加投放策略 Few-shot 示例

## 6. P1 — 要素完善：输出规范 + 肯定优先

- [ ] 6.1 新建 `app/core/output_spec.py`：统一输出规范（格式要求/质量标准/行为规范）
- [ ] 6.2 修改 `app/core/agent_robustness.py`：`enrich_system_prompt()` 中追加 `OUTPUT_SPEC` 注入
- [ ] 6.3 修改 `app/agents/brand_bd.py`：3 处否定句式重写为肯定优先（工具调用/邀约个性化/物流跟踪）
- [ ] 6.4 修改 `app/agents/cc.py`：1 处否定句式重写（工具调用）
- [ ] 6.5 修改 `app/agents/amy.py`：2 处否定句式重写（敏感问题/客户不满）
- [ ] 6.6 修改 `app/agents/smart_ad_delivery.py`：1 处否定句式重写（投放决策）

## 7. P2 — 工程化：版本元数据

- [ ] 7.1 修改 8 个 Agent 文件（`brand_bd/cc/ben/amy/warehouse_logistics/visual_designer/product_selector/smart_ad_delivery.py`）：各加 `PROMPT_VERSION="2.0.0"` / `PROMPT_UPDATED="2026-05-29"` / `PROMPT_CHANGELOG` 常量
- [ ] 7.2 修改 `app/core/agent_robustness.py`：加版本元数据 `PROMPT_VERSION="1.0.0"`
- [ ] 7.3 修改 `app/core/output_spec.py`：加版本元数据 `PROMPT_VERSION="1.0.0"`
- [ ] 7.4 修改 `app/core/instruction_boundary.py`：加版本元数据 `PROMPT_VERSION="1.0.0"`

## 8. P2 — 工程化：PromptLoader

- [ ] 8.1 新建 `app/core/prompt_loader.py`：`PromptMeta` dataclass + `PromptRegistry` 注册表 + `PromptLoader` 加载器（含 `fill_placeholders`）
- [ ] 8.2 修改 `app/agent.py`：加 `_auto_register_prompt_versions()` 启动时注册全部 11 个 Prompt 模块
- [ ] 8.3 修改 `app/api/admin/admin.py`（或选中的 admin 路由文件）：加 `GET /admin/prompts/versions` 端点返回 `PromptRegistry.get_version_summary()`

## 9. P3 — 进化闭环：Meta Prompt 标准化

- [ ] 9.1 新建 `app/core/meta_prompt_standards.py`：`META_ANALYST_ROLE` / `META_ENGINEER_ROLE` / `META_CONSTRAINTS` / `META_OUTPUT_FORMAT` 常量
- [ ] 9.2 修改 `app/evolution/suggester.py`：`_call_llm_for_suggestions()` 重写为结构化 Meta Prompt（SystemMessage 含角色+约束+格式+Few-shot + HumanMessage 含数据）
- [ ] 9.3 修改 `app/evolution/suggester.py`：`_call_llm_for_single_result()` 重写为结构化 Meta Prompt（含单样本置信度校准指令）
- [ ] 9.4 修改 `app/runtime/memory.py`：`_extract_patterns()` 重写为结构化 Meta Prompt（含角色+约束+分类规则+频率置信度+Few-shot）
- [ ] 9.5 修改 `app/runtime/memory.py`：`_extract_prompt_rules()` 重写为结构化 Meta Prompt（含规则级别+触发条件+空数据返回空数组指令）

## 10. P3 — 进化闭环：自动化测评流水线

- [ ] 10.1 新建 `tests/evaluation/cases/brand_bd.yaml`：品牌商务 3 个测试用例（达人筛选/邀约/复盘）
- [ ] 10.2 新建 `tests/evaluation/judge.py`：LLM-as-Judge 评判引擎（含结构化 System Prompt、行为打分、质量总分、不可接受检测）
- [ ] 10.3 新建 `tests/evaluation/runner.py`：测评运行器（加载 YAML → 调用 Agent → 评判 → JSON 报告 + 终端摘要）

## 11. 验证与收尾

- [ ] 11.1 运行 `ruff check backend/` 检查代码风格
- [ ] 11.2 运行 `pytest backend/tests/ -x` 确认现有测试通过（适配 test_collaboration.py 等受影响的测试）
- [ ] 11.3 启动后端服务，调用 `GET /admin/prompts/versions` 确认版本注册正常
- [ ] 11.4 发送测试消息（正常请求 + 攻击请求）确认三层防护生效