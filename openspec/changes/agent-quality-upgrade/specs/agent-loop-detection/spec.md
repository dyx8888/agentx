## ADDED Requirements

### Requirement: 状态指纹计算
系统SHALL在executor_node每次工具调用前计算状态指纹，指纹由 `hash(agent_name + tool_name + tool_args)` 生成。

#### Scenario: 相同状态产生相同指纹
- **WHEN** 同一Agent使用相同工具和参数被调用两次
- **THEN** 系统生成相同的状态指纹

#### Scenario: 不同状态产生不同指纹
- **WHEN** Agent使用不同工具或不同参数
- **THEN** 系统生成不同的状态指纹

### Requirement: 循环检测规则
系统SHALL维护最近5步的状态指纹滑动窗口，当窗口内相同指纹出现3次及以上时，判定为循环。

#### Scenario: 检测到循环
- **WHEN** Agent在最近5步中3次调用同一工具且参数相同
- **THEN** 系统判定为循环，终止当前执行并返回错误信息

#### Scenario: 正常重复不误判
- **WHEN** Agent在最近5步中2次调用同一工具且参数相同
- **THEN** 系统不判定为循环，继续正常执行

### Requirement: 循环终止行为
当检测到循环时，系统SHALL向用户返回明确的错误消息，包含检测到的循环模式和终止原因。

#### Scenario: 循环终止消息
- **WHEN** 循环检测触发
- **THEN** 系统返回包含 "检测到执行循环"、循环工具名称、建议操作的消息