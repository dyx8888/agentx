## ADDED Requirements

### Requirement: Engine作为Agent工具注册
所有Engine SHALL通过ToolRegistry注册为Agent可调用的工具，Agent通过Function Calling决定是否调用Engine。

#### Scenario: Agent调用Engine处理客服
- **WHEN** Agent判断用户消息为客服投诉类
- **THEN** Agent通过 `call_engine(engine_name="customer_service", params={...})` 工具调用CustomerServiceEngine

#### Scenario: Engine返回结果给Agent
- **WHEN** CustomerServiceEngine处理完成
- **THEN** Engine返回标准ToolResult，包含处理结果和建议，Agent据此决定后续操作

### Requirement: Engine-Agent混合模式
对于高风险场景，系统SHALL支持Engine主导流程，Agent在关键决策点（如回复内容生成、情绪判断）介入。

#### Scenario: 客服投诉Engine主导
- **WHEN** 用户消息匹配HIGH_RISK_KEYWORDS（如"投诉"、"315"、"律师"）
- **THEN** CustomerServiceEngine主导处理流程，Agent仅在生成回复内容时介入，回复需人工审核

#### Scenario: 低风险场景Agent自主
- **WHEN** 用户消息匹配LOW_RISK（如"你好"、"查询订单"）
- **THEN** Agent自主处理，不需要Engine介入

### Requirement: 工作流YAML配置化编排
固定工作流SHALL支持通过YAML配置文件定义，无需编写Python代码。编排格式包含：步骤序列、条件分支、工具调用、LLM介入点。

#### Scenario: YAML工作流定义
- **WHEN** 运营人员在 `config/workflows/customer_service.yaml` 中定义客服流程
- **THEN** 系统加载YAML配置，自动生成对应的Engine实例

#### Scenario: YAML格式验证
- **WHEN** YAML文件缺少必填字段（如 `steps`、`name`）
- **THEN** 系统在加载时报告验证错误，拒绝创建Engine

### Requirement: 统一入口路由
`chat.py` SHALL通过统一的路由表决定请求走Agent自主规划还是Engine固定工作流，消除当前的双重路径。

#### Scenario: 路由到Engine
- **WHEN** 用户请求匹配 `engine_routes.yaml` 中的规则（如 `keywords: ["投诉", "退款"]`）
- **THEN** 系统直接路由到CustomerServiceEngine，不经过Agent

#### Scenario: 路由到Agent
- **WHEN** 用户请求不匹配任何Engine路由规则
- **THEN** 系统路由到AgentRuntime，由Agent自主规划处理

### Requirement: 决策三问路由
路由决策前SHALL自动评估三个问题：流程能否提前写死？容错率如何？延迟和成本敏感吗？

#### Scenario: 能写死的流程走工作流
- **WHEN** 决策三问判定"流程可提前写死"（如标准订单查询）
- **THEN** 系统路由到Engine固定工作流，减少Token消耗

#### Scenario: 容错率极低加人工确认
- **WHEN** 决策三问判定"容错率极低"（如退款操作）
- **THEN** 系统在Engine工作流中增加人工确认节点，Agent仅在内容生成时介入

#### Scenario: 成本敏感走工作流
- **WHEN** 决策三问判定"延迟和成本极敏感"（如高频简单查询）
- **THEN** 系统路由到轻量级Engine，避免LLM调用开销

### Requirement: 任务复杂度评分
系统SHALL基于LLM对用户请求进行复杂度打分（1-10），作为路由决策依据。

#### Scenario: 低复杂度走工作流
- **WHEN** 复杂度评分 < 4（如"查询订单状态"）
- **THEN** 系统路由到Engine固定工作流

#### Scenario: 高复杂度走Agent
- **WHEN** 复杂度评分 > 6（如"分析竞品并制定差异化策略"）
- **THEN** 系统路由到Agent自主规划

#### Scenario: 中等复杂度混合模式
- **WHEN** 复杂度评分 4-6（如"生成报告并发送邮件"）
- **THEN** 系统使用Engine控制流程，Agent在内容生成环节介入

### Requirement: Agent内嵌固定子步骤
系统SHALL支持通过System Prompt约束Agent在特定环节按固定步骤执行。

#### Scenario: 客服回复前核实身份
- **WHEN** Agent处理客服类请求
- **THEN** System Prompt约束Agent在回复前必须执行身份核实步骤："在回复任何订单信息前，必须先调用verify_user_identity工具核实用户身份"

#### Scenario: 工作流调度Agent
- **WHEN** 主流程为固定工作流但包含复杂子任务
- **THEN** Engine按固定步骤执行流程，在遇到复杂子任务（如"生成个性化推荐文案"）时调用Agent完成