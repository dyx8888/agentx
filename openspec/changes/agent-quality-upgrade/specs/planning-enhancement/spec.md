## ADDED Requirements

### Requirement: Planner质量验证
Planner生成计划后，Executor执行前，系统SHALL对计划进行质量验证，检查步骤是否合理、工具是否可用、是否覆盖用户需求。

#### Scenario: 计划步骤验证通过
- **WHEN** Planner生成包含3个步骤的计划，所有步骤引用的工具都在ToolRegistry中注册
- **THEN** 验证通过，Executor开始执行

#### Scenario: 计划引用不存在的工具
- **WHEN** Planner生成的计划引用了未注册的工具 `generate_ad_campaign`
- **THEN** 验证失败，返回Planner重新生成计划，附带可用工具列表

#### Scenario: 计划步骤过于模糊
- **WHEN** Planner生成的计划包含 "分析数据" 这种模糊步骤，缺少具体工具调用
- **THEN** 验证失败，返回Planner要求细化步骤

### Requirement: Reflector闭环反馈
Reflector的审查结果SHALL不仅返回pass/fail，还需将具体的改进建议反馈给Planner，用于优化后续执行计划。

#### Scenario: 执行失败触发重新规划
- **WHEN** Executor执行步骤2失败，Reflector判定为fail
- **THEN** Reflector的建议（如"改用tool_b替代tool_a"）被注入到Planner的prompt中，生成新的替代计划

#### Scenario: 执行成功但质量不高
- **WHEN** Reflector判定为pass但confidence < 0.7
- **THEN** Reflector的建议（如"结果数据量太少，建议扩大搜索范围"）被记录但不触发重新规划

### Requirement: 动态调整
当执行过程中部分步骤失败时，系统SHALL支持重新规划剩余步骤，而非重试整条计划。

#### Scenario: 部分失败动态调整
- **WHEN** 4步计划中步骤2失败，步骤1和步骤3已完成
- **THEN** 系统保留已完成步骤的结果，仅为步骤2重新规划替代方案，不影响步骤4

#### Scenario: 全部失败停止执行
- **WHEN** 连续2次动态调整后仍失败
- **THEN** 系统终止执行，返回已完成的步骤结果和失败原因

### Requirement: LLM意图识别模式选择
系统SHALL使用LLM识别用户意图并自动选择AgentMode，替代当前关键词匹配方式。

#### Scenario: 复杂任务选择Plan-and-Solve
- **WHEN** 用户输入 "帮我分析这个月的销售数据，找出下降原因，然后制定下个月的优化方案"
- **THEN** LLM识别为multi_step_complex任务，选择Plan-and-Solve模式

#### Scenario: 简单查询选择ReAct
- **WHEN** 用户输入 "帮我查一下抖音美妆达人Top10"
- **THEN** LLM识别为simple_query任务，选择ReAct模式

#### Scenario: 质量要求高选择Reflection
- **WHEN** 用户输入 "帮我写一个品牌营销方案，要确保质量达到专业水准"
- **THEN** LLM识别为high_quality_required任务，选择Reflection模式