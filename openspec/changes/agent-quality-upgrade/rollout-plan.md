# Agent Quality Upgrade - 灰度上线方案

## 概述

本文档定义了 Agent Quality Upgrade 各项功能的灰度上线策略，采用分阶段逐步开启的方式，确保生产环境稳定性。

## 阶段划分

### Phase 1: 基础稳定性（第1周）

**目标：** 在不影响现有功能的前提下，验证基础设施的稳定性。

| 功能 | 默认状态 | 灰度策略 | 回滚条件 |
|------|---------|---------|---------|
| `loop_detection` | **开启** | 100% 全量 | 误判率 > 5% |
| `idempotency` | 关闭 | 10% → 50% → 100% | 延迟增加 > 10ms P99 |
| `checkpoint_recovery` | 关闭 | 内部测试环境先开启 | 恢复失败率 > 10% |

**验证指标：**
- 循环检测误判率 < 5%
- 幂等检查延迟 P99 < 10ms
- Checkpoint 保存成功率 > 99%

**操作步骤：**
```bash
# 1. loop_detection 已默认开启，监控误判率
# 2. 逐步开启 idempotency
export FEATURE_IDEMPOTENCY=true  # 先在 10% 实例开启
# 3. 观察 24h 后扩大到 50%
# 4. 观察 48h 后全量开启

# 5. 开启 checkpoint_recovery（内部测试）
export FEATURE_CHECKPOINT_RECOVERY=true
```

### Phase 2: 工具可靠性（第2周）

**目标：** 提升工具调用的可靠性和错误处理能力。

| 功能 | 默认状态 | 灰度策略 | 回滚条件 |
|------|---------|---------|---------|
| `tool_error_standardization` | **开启** | 100% 全量 | 工具返回格式兼容性问题 |
| `tool_timeout_retry` | 关闭 | 20% → 50% → 100% | 重复调用导致副作用 |
| `degradation` | 关闭 | 10% → 30% → 100% | 降级结果质量差 |

**验证指标：**
- 工具调用成功率提升 > 5%
- 超时重试成功率 > 60%
- 降级策略触发率 < 10%

**操作步骤：**
```bash
# 1. tool_error_standardization 已默认开启
# 2. 开启 tool_timeout_retry（20% 流量）
export FEATURE_TOOL_TIMEOUT_RETRY=true
# 3. 监控重试成功率和副作用
# 4. 逐步扩大到 50% → 100%
# 5. 开启 degradation（10% 流量）
export FEATURE_DEGRADATION=true
```

### Phase 3: MCP协议增强（第3周）

**目标：** 增强 MCP 协议层的稳定性和功能。

| 功能 | 默认状态 | 灰度策略 | 回滚条件 |
|------|---------|---------|---------|
| `mcp_health_check` | **开启** | 100% 全量 | 健康检查导致连接池耗尽 |

**验证指标：**
- MCP Server 连接成功率 > 99%
- 连接池复用率 > 80%
- 健康检查延迟 < 100ms

### Phase 4: Skills语义匹配（第4周）

**目标：** 提升 Skills 匹配准确率。

| 功能 | 默认状态 | 灰度策略 | 回滚条件 |
|------|---------|---------|---------|
| `semantic_skill_matching` | 关闭 | A/B测试 50% | 匹配准确率低于关键词匹配 |

**验证指标：**
- 语义匹配准确率 > 原有关键词匹配准确率
- 匹配延迟 < 200ms
- 误匹配率 < 10%

**操作步骤：**
```bash
# A/B 测试：50% 流量使用语义匹配
export FEATURE_SEMANTIC_SKILL_MATCHING=true  # 50% 实例
# 对比两组的关键指标
# 7天后根据结果决定全量或回滚
```

### Phase 5: 记忆管理（第5周）

**目标：** 优化记忆生命周期管理，防止内存溢出。

| 功能 | 默认状态 | 灰度策略 | 回滚条件 |
|------|---------|---------|---------|
| `token_based_truncation` | 关闭 | 20% → 50% → 100% | 截断导致上下文丢失 |
| `lru_memory_eviction` | 关闭 | 20% → 50% → 100% | 高价值记忆被误淘汰 |

**验证指标：**
- 会话内存使用降低 > 30%
- 截断后任务完成率不下降
- 高置信度记忆保留率 > 95%

**操作步骤：**
```bash
# 1. 开启 token_based_truncation（20%）
export FEATURE_TOKEN_BASED_TRUNCATION=true
# 2. 监控上下文质量和任务完成率
# 3. 逐步扩大到 50% → 100%
# 4. 开启 lru_memory_eviction（20%）
export FEATURE_LRU_MEMORY_EVICTION=true
```

### Phase 6: 感知管道（第6周）

**目标：** 统一感知管道，替换手动拼接的感知流程。

| 功能 | 默认状态 | 灰度策略 | 回滚条件 |
|------|---------|---------|---------|
| `perception_pipeline` | 关闭 | 10% → 30% → 100% | 意图识别准确率下降 |

**验证指标：**
- 意图识别准确率 >= 原有水平
- 感知管道延迟 P99 < 500ms
- Query 改写质量 >= 原有水平

**操作步骤：**
```bash
export FEATURE_PERCEPTION_PIPELINE=true  # 10% 流量
# 对比新旧管道的意图识别准确率
# 逐步扩大到 30% → 100%
```

### Phase 7: 并行Agent（第7周）

**目标：** 支持并行 Agent 执行，提升多任务处理效率。

| 功能 | 默认状态 | 灰度策略 | 回滚条件 |
|------|---------|---------|---------|
| `parallel_agent` | 关闭 | 内部白名单 → 10% | 并行执行导致资源竞争 |

**验证指标：**
- 并行任务完成时间 < 串行时间的 60%
- 并行任务成功率 > 90%
- 资源使用增长 < 2x

**操作步骤：**
```bash
# 仅对特定公司/Agent 开放
export FEATURE_PARALLEL_AGENT=true  # 白名单模式
# 监控资源使用和任务完成情况
# 逐步开放更多租户
```

### Phase 8: 分层编排（第8周）

**目标：** 支持分层 Agent 编排，处理复杂跨领域任务。

| 功能 | 默认状态 | 灰度策略 | 回滚条件 |
|------|---------|---------|---------|
| `hierarchical_orchestrator` | 关闭 | 内部白名单 → 5% | 层级通信超时 |

**验证指标：**
- 分层任务完成率 > 80%
- 层级间通信延迟 < 1s
- 信息传递失真率 < 20%

### Phase 9: 全量稳定（第9周+）

**目标：** 所有功能稳定运行，持续优化。

- 回顾所有阶段的监控数据
- 调整阈值和策略参数
- 编写运维手册和故障处理 SOP
- 团队培训：新功能使用和故障排查

## 监控与告警

### 关键指标

| 指标 | 告警阈值 | 严重级别 |
|------|---------|---------|
| 幂等命中率 | < 80% | Warning |
| 幂等检查延迟 P99 | > 10ms | Warning |
| Checkpoint 保存成功率 | < 99% | Critical |
| Checkpoint 恢复成功率 | < 95% | Critical |
| 循环误判率 | > 5% | Warning |
| 工具调用成功率 | < 95% | Critical |
| 工具超时率 | > 10% | Warning |
| 降级触发率 | > 20% | Warning |
| MCP 连接健康度 | < 90% | Critical |
| 感知管道延迟 P99 | > 500ms | Warning |
| 意图识别准确率 | 下降 > 10% | Warning |

### 告警通道

1. **P0 (Critical):** 企业微信 + 电话 + PagerDuty
2. **P1 (Warning):** 企业微信 + 邮件
3. **P2 (Info):** 邮件 + 看板

## 回滚策略

### 快速回滚（< 5分钟）
```bash
# 关闭单个功能
export FEATURE_{NAME}=false

# 或关闭所有新功能
export FEATURE_IDEMPOTENCY=false
export FEATURE_CHECKPOINT_RECOVERY=false
export FEATURE_TOOL_TIMEOUT_RETRY=false
export FEATURE_DEGRADATION=false
export FEATURE_SEMANTIC_SKILL_MATCHING=false
export FEATURE_TOKEN_BASED_TRUNCATION=false
export FEATURE_LRU_MEMORY_EVICTION=false
export FEATURE_PERCEPTION_PIPELINE=false
export FEATURE_PARALLEL_AGENT=false
export FEATURE_HIERARCHICAL_ORCHESTRATOR=false
```

### 部分回滚
- 按租户回滚：仅对问题租户关闭功能
- 按 Agent 回滚：仅对问题 Agent 关闭功能
- 按功能回滚：仅关闭出问题的具体功能

## 风险评估

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| 幂等检查误判导致任务不执行 | 低 | 高 | 仅对标记 `side_effect: true` 的工具生效 |
| Checkpoint 恢复失败导致任务丢失 | 中 | 高 | 内存降级 + 人工介入通道 |
| 语义匹配误导 Agent 选择错误 Skill | 中 | 中 | A/B 测试 + 阈值控制 |
| 记忆截断丢失关键上下文 | 低 | 中 | LLM 摘要压缩 + 高置信度保护 |
| 并行执行导致 LLM 并发超限 | 中 | 中 | 全局并发限制 + 队列机制 |
| 分层编排信息传递失真 | 高 | 中 | 层数限制 (3层) + 结构化摘要 |