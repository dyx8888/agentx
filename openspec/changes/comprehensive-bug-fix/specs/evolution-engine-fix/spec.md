## ADDED Requirements

### Requirement: interval_hours=0 被正确识别为有效值
系统 SHALL 在 `SleepConsolidationEngine.__init__()` 中使用 `is None` 检查而非 `or` 短路来区分"未传入参数"和"传入 0"。

#### Scenario: 传入 interval_hours=0 禁用定时触发
- **WHEN** 用户显式传入 `interval_hours=0`
- **THEN** `self.interval_hours` 被设为 0，定时触发被禁用

#### Scenario: 未传入 interval_hours 使用默认值
- **WHEN** 用户未传入 `interval_hours` 参数（None）
- **THEN** `self.interval_hours` 被设为 `DEFAULT_INTERVAL_HOURS`（4 小时）

### Requirement: _get_agent_runtime 正确导入
系统 SHALL 确保 `_get_agent_runtime()` 函数中导入的模块路径存在且正确。

#### Scenario: AgentRuntime 实例被成功获取
- **WHEN** 记忆写入或睡眠巩固需要 AgentRuntime 实例
- **THEN** 成功获取实例，返回非 None 值

### Requirement: MemoryAutoWriter 使用 SessionStore 公共 API
系统 SHALL 确保 `MemoryAutoWriter._cache_to_redis()` 通过 `SessionStore` 的公共方法访问 Redis 缓存，而非直接访问 `_redis` 私有属性。

#### Scenario: Redis 不可用时优雅降级
- **WHEN** Redis 不可用（`_redis_available = False`）
- **THEN** `_cache_to_redis()` 不抛出 `AttributeError`，而是跳过缓存或使用内存存储