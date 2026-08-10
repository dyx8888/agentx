## ADDED Requirements

### Requirement: 幂等键生成
系统SHALL为每个副作用工具调用自动生成幂等键，格式为 `idem:{company_id}:{agent_name}:{tool_name}:{hash(params)}`。

#### Scenario: 同一任务重复提交
- **WHEN** 同一Agent使用相同参数两次调用 `schedule_task`
- **THEN** 第二次调用直接返回第一次的结果，不创建重复任务

#### Scenario: 不同参数产生不同幂等键
- **WHEN** 同一Agent使用不同参数调用同一工具
- **THEN** 系统生成不同的幂等键，正常执行两次调用

### Requirement: 幂等结果存储
系统SHALL将幂等键和对应的执行结果存储在Redis中，TTL为24小时。

#### Scenario: TTL过期后重新执行
- **WHEN** 幂等键的TTL已过期
- **THEN** 系统视为新请求，正常执行工具调用

#### Scenario: Redis不可用时降级
- **WHEN** Redis连接失败
- **THEN** 系统降级为本地内存缓存，记录WARNING日志

### Requirement: 工具声明副作用
支持副作用操作的工具SHALL在其metadata中标记 `side_effect: true`，使IdempotencyManager识别需要幂等保护的工具。

#### Scenario: 只读工具不触发幂等检查
- **WHEN** 工具metadata中 `side_effect` 为 `false` 或未设置
- **THEN** IdempotencyManager跳过该工具的幂等检查