## ADDED Requirements

### Requirement: 检查点自动保存
AgentRuntime在LangGraph每个节点执行后SHALL自动保存检查点到Redis，包含完整的RuntimeState快照。

#### Scenario: 正常执行流程保存检查点
- **WHEN** AgentRuntime执行完planner节点
- **THEN** 系统自动将当前RuntimeState保存到Redis，key为 `checkpoint:{thread_id}`

#### Scenario: 执行中断后恢复
- **WHEN** AgentRuntime因重启或异常中断，使用相同的thread_id重新启动
- **THEN** 系统从Redis恢复最近的检查点，从断点继续执行

### Requirement: 检查点生命周期
检查点数据SHALL在任务完成后自动清理，最长保留时间为1小时。

#### Scenario: 任务完成清理
- **WHEN** AgentRuntime.run()正常返回
- **THEN** 系统清理该thread_id对应的所有检查点

#### Scenario: 超时自动清理
- **WHEN** 检查点创建超过1小时未被恢复
- **THEN** Redis自动过期删除该检查点

### Requirement: 降级策略
当Redis不可用时，系统SHALL降级为内存检查点，并记录WARNING日志。

#### Scenario: Redis不可用时的内存检查点
- **WHEN** Redis连接失败
- **THEN** 系统使用内存字典存储检查点，重启后检查点丢失