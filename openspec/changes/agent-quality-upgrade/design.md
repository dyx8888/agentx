## Context

当前项目基于LangGraph + FastAPI构建了多Agent电商平台，已实现三层记忆、MCP/A2A协议、Plan-Execute-Reflect架构、LLM-as-Judge评测框架。但对照《Agent智能体应用》文档7大模块标准，在工程可靠性、工具调用标准化、感知规划闭环、多Agent协作、Engine-Agent边界等方面存在明显缺口。

## Goals / Non-Goals

**Goals:**
- 为所有副作用操作引入幂等性保障，防止重复扣款/订票等危险操作
- 实现基于Redis的checkpoint机制，支持Agent任务中断后从断点恢复
- 升级循环检测：在max_iterations基础上增加状态指纹检测
- 建立自动化评测流水线，集成到CI
- 统一工具错误码和描述规范，让LLM能理解并自动重试
- 实现统一感知管道(PerceptionPipeline)，Query改写+意图提炼
- 实现Planner质量验证+Reflector闭环反馈+动态调整
- 明确Engine-Agent边界，Engine作为Agent工具注册，支持YAML工作流编排
- 升级模式选择为LLM意图识别，准确率目标>90%
- 实现Skills语义匹配(embedding-based)替代关键词匹配
- 清理legacy代码，统一配置管理

**Non-Goals:**
- 不改变现有Agent的prompt和业务逻辑
- 不引入新的外部依赖（复用现有Redis/Milvus）
- 不重构前端

## Decisions

### 1. 幂等性：IdempotencyKey + Redis去重

**选择**：在`app/core/idempotency.py`中实现`IdempotencyManager`，使用Redis存储已处理的幂等键。

```
┌──────────┐     ┌──────────────────┐     ┌──────────┐
│ Executor │────▶│ IdempotencyMgr   │────▶│  Tool    │
│  Node    │     │ .check_or_exec() │     │  (实际)  │
└──────────┘     └──────┬───────────┘     └──────────┘
                        │
                   ┌────▼────┐
                   │  Redis  │
                   │ KV: key │
                   │ → result│
                   └─────────┘
```

- 幂等键格式：`idem:{company_id}:{agent_name}:{tool_name}:{hash(params)}`
- TTL：24小时（副作用操作建议更短）
- 替代方案：DB去重（更重但更持久），当前选择Redis平衡性能和可靠性

### 2. 中断恢复：LangGraph Checkpointer + RedisSaver

**选择**：利用LangGraph内置的checkpointer机制，实现RedisSaver。

```
Orchestrator.run()
     │
     ▼
┌─────────────┐    checkpoint    ┌──────────┐
│  LangGraph  │◄───────────────▶│  Redis   │
│  .compile(  │   save/restore   │  Saver   │
│   checkpointer)                │          │
└─────────────┘                  └──────────┘
```

- 每个节点执行后自动保存checkpoint
- 重启时通过`thread_id`恢复状态
- 替代方案：自建任务队列（Celery），但LangGraph内置方案更轻量且无需额外组件

### 3. 循环检测：状态指纹 + 滑动窗口

**选择**：在`executor_node`中增加`_detect_loop()`，维护最近N步的状态指纹集合。

```
状态指纹 = hash(agent_state + tool_name + tool_args)
滑动窗口 = 最近5步
检测规则 = 窗口内相同指纹出现 >= 3次 → 判定为循环
```

- 替代方案：纯LLM-based检测（更智能但成本高），当前选择规则+LLM混合

### 4. 评测流水线：pytest + 自定义Evaluator

**选择**：基于pytest构建评测框架，通过`app/evaluation/`模块封装。

```
┌──────────┐    ┌──────────────┐    ┌──────────────┐
│ Test     │───▶│ AgentRuntime │───▶│ Evaluator    │
│ Cases    │    │ .run(test)   │    │ .score()     │
│ (YAML)   │    └──────────────┘    └──────┬───────┘
└──────────┘                               │
                                     ┌─────▼──────┐
                                     │  Metrics   │
                                     │  - 完成率   │
                                     │  - 工具准确率│
                                     │  - 平均步数  │
                                     └────────────┘
```

- 测试用例：YAML格式，描述输入、预期工具调用、预期结果
- 指标：任务完成率、工具调用准确率、平均步数、Token消耗
- CI集成：GitHub Actions / GitLab CI，每次PR触发评测

### 5. 工具错误标准化：ToolResult强制使用

**选择**：已有`ToolResult`类（`app/tools/result.py`），扩展为所有工具的强制返回类型。

```
ToolResult
├── .ok(data, message)
├── .error(error_code, message, suggestion)
├── .pending_approval(tool_name, params, message)
└── .to_json() → LLM可读的结构化错误
```

错误码枚举：
- `TOOL_TIMEOUT`：超时 → 建议重试
- `CONNECTION_ERROR`：连接失败 → 建议切换备用源
- `MAX_CALLS_EXCEEDED`：超过调用上限 → 建议简化任务
- `INVALID_PARAMS`：参数错误 → 建议修正参数
- `PERMISSION_DENIED`：权限不足 → 建议联系管理员

### 6. 统一感知管道：PerceptionPipeline 5阶段编排

**选择**：在`app/perception/`模块中实现管道式编排。

```
用户输入
    │
    ▼
┌───────────────┐
│ InputFilter   │ → 安全过滤、敏感词检测
└───────┬───────┘
        ▼
┌───────────────┐
│ QueryRewriter │ → LLM改写：补全省略、口语转结构化
└───────┬───────┘
        ▼
┌───────────────┐
│ IntentExtract │ → LLM提炼：意图类型、优先级、平台
└───────┬───────┘
        ▼
┌───────────────┐
│ RagRetriever  │ → Milvus检索：知识库匹配
└───────┬───────┘
        ▼
┌───────────────┐
│ PerceptionCtx │ → 结构化输出：含所有阶段结果
└───────────────┘
```

- 替代方案：直接在chat.py中手动拼接（当前做法），但管道模式更易扩展和维护

### 7. 思考规划增强：Planner验证 + Reflector闭环

**选择**：在现有Plan-Execute-Reflect架构上增加质量验证和反馈闭环。

```
Planner → _validate_plan() → Executor → Reflector
    ▲                                       │
    └─────────── feedback ──────────────────┘
```

- Planner验证：检查工具可用性、步骤具体性、需求覆盖度
- Reflector闭环：审查建议(suggestion)注入Planner的prompt
- 动态调整：部分失败时仅重新规划剩余步骤，保留已完成结果
- 替代方案：无验证直接执行（当前做法），但会导致无效计划被错误执行

### 8. Engine-Agent边界：Engine作为Agent工具

**选择**：所有Engine通过ToolRegistry注册为Agent可调用的工具。

```
chat.py
    │
    ├── engine_routes.yaml 匹配？──→ Engine 主导（高风险场景）
    │
    └── 不匹配 ──→ AgentRuntime ──→ call_engine("customer_service", params)
```

- Engine主导模式：高风险场景（投诉/退款）Engine控制流程，Agent仅在内容生成介入
- Agent主导模式：常规场景Agent自主规划，可选调用Engine工具
- 工作流编排：YAML配置化（`config/workflows/*.yaml`），无需写Python代码

### 9. Skills语义匹配：Embedding替代关键词

**选择**：在`skills/registry.py`中替换`match_skill()`的字符串包含匹配为embedding语义匹配。

```
用户查询 → embedding → 余弦相似度排序 → top-3 skills
                ↑
        预计算 skill_embeddings 缓存
```

- 相似度阈值：0.6（低于阈值不匹配）
- 替代方案：关键词匹配（当前做法），但无法处理同义词（"写脚本" vs "创作内容"）

### 10. LLM意图识别模式选择

**选择**：替换`_select_agent_mode()`的8个关键词匹配为LLM调用。

```
用户输入 → LLM分析 → {mode: "plan_solve", complexity: "multi_step", reason: "..."}
```

- 意图类型：simple_query → ReAct, multi_step_complex → Plan-and-Solve, high_quality → Reflection
- 替代方案：关键词匹配（当前做法，准确率~60%），LLM意图识别准确率目标>90%

### 11. 工具Schema标准化与五原则校验

**选择**：在`ToolLoader`中增加`ToolSchemaValidator`，对每个工具的Schema进行五原则校验。

```
MCP Server → ToolLoader → SchemaValidator → 五原则评分
                  │                              │
                  │                    ┌─────────▼────────┐
                  │                    │ 命名清晰 ✓/✗      │
                  │                    │ 描述精准 ✓/✗      │
                  │                    │ 参数设计 ✓/✗      │
                  │                    │ 错误友好 ✓/✗      │
                  │                    │ 单一职责 ✓/✗      │
                  │                    │ 副作用标注 ✓/✗    │
                  │                    └──────────────────┘
                  │                              │
                  ▼                              ▼
              注册工具              LLM自动增强（低于阈值）
```

- 评分阈值：总分60分以下自动调用LLM增强描述
- 替代方案：人工审核（慢，不可扩展），自动校验（快速反馈，持续改进）

### 12. A2A状态追踪与任务生命周期

**选择**：在`a2a_delegate_task`中增加任务状态轮询，支持长时间任务的状态查询。

```
┌──────────┐   delegate   ┌──────────┐   poll_status   ┌──────────┐
│ 主Agent  │─────────────▶│ 子Agent  │◀───────────────│ 主Agent  │
│          │   task_id    │          │  status:running │          │
└──────────┘              └──────────┘                 └──────────┘
                                  │
                                  ▼
                           ┌──────────┐
                           │  Redis   │
                           │ task:{id}│
                           │ → status │
                           │ → result │
                           └──────────┘
```

- 状态流转：PENDING → RUNNING → COMPLETED / FAILED / TIMEOUT
- 轮询间隔：2秒，最大等待60秒
- 替代方案：WebSocket推送（实时但复杂），轮询（简单可靠）

### 13. 分层Agent架构（金字塔模式）

**选择**：在OrchestratorAgent基础上支持多层嵌套，每层负责子任务分解和结果汇总。

```
              ┌──────────────┐
              │ 总指挥Agent  │  ← 第1层：接收用户目标，分解为子目标
              └──────┬───────┘
          ┌──────────┼──────────┐
          ▼          ▼          ▼
    ┌─────────┐ ┌─────────┐ ┌─────────┐
    │组长Agent│ │组长Agent│ │组长Agent│  ← 第2层：领域专家，调度组员
    └────┬────┘ └────┬────┘ └────┬────┘
      ┌──┴──┐     ┌──┴──┐     ┌──┴──┐
      ▼     ▼     ▼     ▼     ▼     ▼
    [组员] [...] [...] [...] [...] [...]  ← 第3层：执行具体任务
```

- 最大层级：3层（防止信息失真）
- 层级间通信：向上汇报结构化摘要（JSON），向下传递子任务（含上下文）
- 替代方案：扁平化（当前做法，简单但不可扩展），分层（复杂但适用于大规模任务）

### 14. 四级降级策略

**选择**：在`executor_node`中实现四级降级策略，工具失败时按优先级降级。

```
工具调用失败
    │
    ├── 1. 使用缓存数据（返回时标注"数据可能延迟"）
    │
    ├── 2. 切换备用数据源（如主API→备用API）
    │
    ├── 3. 跳过非关键步骤（生成部分结果告知用户）
    │
    └── 4. 转人工工单（关键步骤无法降级时）
```

- 降级顺序：按1→2→3→4依次尝试
- 降级配置：在`tool_providers.yaml`中为每个工具配置降级策略
- 替代方案：统一返回错误（当前做法，用户体验差），分级降级（更好但复杂）

### 15. 评测根因分析与迭代闭环

**选择**：在评测流水线中增加`RootCauseAnalyzer`，自动归纳失败模式并关联优化建议。

```
评测结果 → RootCauseAnalyzer → 失败模式分类
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              规划推理差      工具选择错误      异常处理差
              → 改进提示词    → 优化工具描述    → 加强降级规则
              → 加示例        → 参数说明        → 升级提示词
                    │               │               │
                    └───────────────┼───────────────┘
                                    ▼
                              Suggester自动生成优化建议
                                    │
                                    ▼
                              Evolution.apply()
```

- 失败模式：规划错误、工具误选、参数错误、幻觉、安全绕过
- 人工校准：每50次评测抽检5次，校准LLM-as-Judge评分
- 替代方案：全人工分析（慢），LLM自动分析（快但需人工校准）

### 16. 可靠性协同工作流

**选择**：所有可靠性机制（幂等、checkpoint、循环检测、超时降级）在executor_node中统一编排。

```
executor_node 执行流程：
    │
    ├── 1. 生成幂等键（如有副作用）
    ├── 2. 检查幂等缓存 → 命中则返回已有结果
    ├── 3. 保存checkpoint（执行前）
    ├── 4. 循环检测（滑动窗口）
    ├── 5. asyncio.wait_for(工具调用, timeout)
    │       ├── 成功 → 继续
    │       └── 失败 → 重试(指数退避) → 降级(四级策略)
    ├── 6. 保存checkpoint（执行后）
    └── 7. 记录工具调用trace
```

- 执行顺序：幂等检查 → checkpoint保存 → 循环检测 → 超时执行 → 重试/降级 → trace记录
- 替代方案：各机制独立实现（当前设计，易遗漏），统一编排（确保全流程覆盖）

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| Redis单点故障导致幂等/checkpoint不可用 | 幂等键降级为本地缓存+DB双写；checkpoint降级为内存 |
| LLM评测与人工评测结果不一致 | 定期人工抽检校准，维护golden test set |
| 循环检测误判导致正常长任务被中断 | 滑动窗口+LLM二次确认，误判率<5% |
| Legacy代码移除导致旧API调用失败 | 先标记deprecated，灰度下线，保留1个版本过渡期 |
| 工具Schema自动增强错误引导LLM | 仅增强低于60分的工具，且保留原始描述供人工对比 |
| A2A状态轮询加重Redis压力 | 轮询间隔2秒+最大60秒超时，预估QPS<50 |
| 分层Agent架构信息传递失真 | 最大3层限制+每层结构化摘要格式统一 |
| 四级降级中缓存数据过期导致错误信息 | 缓存标注时间戳，超过TTL自动跳过缓存降级 |
| 根因分析LLM误判失败模式 | 人工校准+置信度阈值(低于0.7标记为"未分类") |
| 可靠性协同编排增加单次调用延迟 | 异步执行幂等/checkpoint/trace写入，不阻塞主流程 |

## Migration Plan

1. **Phase 1**：新增幂等和checkpoint模块（不影响现有流程）
2. **Phase 2**：在executor_node中集成循环检测、超时重试、工具调用追踪
3. **Phase 3**：统一工具错误码和描述规范，逐步迁移MCP Server工具
4. **Phase 4**：实现PerceptionPipeline（Query改写+意图提炼），集成到chat.py
5. **Phase 5**：实现Planner验证+Reflector闭环+动态调整
6. **Phase 6**：实现Engine-Agent混合模式，YAML工作流编排
7. **Phase 7**：建立评测流水线，运行基线评测，集成CI
8. **Phase 8**：升级Skills语义匹配、模式选择LLM意图识别
9. **Phase 9**：清理legacy代码，统一配置管理
10. **Rollback**：每个Phase可通过feature flag独立回滚

## Open Questions

- 长期记忆淘汰策略：LRU vs LFU vs 基于时间的TTL？需根据实际业务数据量决定
- 评测测试集的维护策略：谁来维护？更新频率？是否需要专门的角色？
- 是否需要引入A/B测试框架来对比不同prompt/工具的效果？
- PerceptionPipeline中各阶段是否需要LLM，还是部分可以用规则引擎替代以降低成本？
- Engine-Agent的混合模式中，Engine是否应该也有自己的LLM决策能力，还是完全依赖Agent？

## Testing Strategy

### 测试金字塔

```
           ┌──────────┐
           │  E2E     │  全链路场景测试（评测流水线）
           │  5-10条  │
           ├──────────┤
           │ 集成测试  │  模块间交互（Agent + Engine + MCP）
           │  20-30条  │
           ├──────────┤
           │ 单元测试  │  每个新模块独立测试
           │  50+条   │
           └──────────┘
```

### 各阶段关键测试

| 阶段 | 关键测试点 | 覆盖率目标 |
|------|-----------|-----------|
| **单元测试** | `IdempotencyManager.check_or_exec()` 幂等命中/未命中/Redis降级 | 95% |
| | `RedisSaver` checkpoint保存/恢复/清理/TTL过期 | 95% |
| | `_detect_loop()` 正常执行/循环检测/误判边界 | 90% |
| | `_wrap_tool_result()` ToolResult.ok/error/pending_approval | 100% |
| | `QueryRewriter.rewrite()` 补全/口语转结构化/空输入 | 90% |
| | `IntentExtractor.extract()` 简单/复杂/恶意输入 | 90% |
| | `WorkflowLoader.load()` 正常YAML/缺少字段/格式错误 | 95% |
| **集成测试** | Agent调用幂等工具 → 重复请求去重 | 必须有 |
| | Agent执行中断 → 从checkpoint恢复 → 继续执行 | 必须有 |
| | PerceptionPipeline完整流程 → Agent接收结构化上下文 | 必须有 |
| | Engine主导模式：客服投诉 → Engine处理 → Agent生成回复 | 必须有 |
| | A2A并行分派 → 3个Agent → 汇总结果 | 必须有 |
| **E2E** | 用户输入 → 感知 → 规划 → 执行 → 反思 → 回复 | 每人场景 |
| **性能测试** | 幂等检查延迟 < 5ms (Redis本地) | P95 |
| | checkpoint保存延迟 < 50ms | P95 |
| | PerceptionPipeline总延迟 < 500ms（不含RAG检索） | P95 |
| | 重试机制不导致P99劣化 > 2x | 回归 |
| **混沌测试** | Redis宕机 → 幂等降级为本地缓存 + WARNING日志 | 必须有 |
| | Redis宕机 → checkpoint降级为内存 | 必须有 |
| | MCP Server宕机 → ToolRegistry降级 | 必须有 |
| | Milvus宕机 → RAG跳过，感知管道继续 | 必须有 |

## Production Readiness

### Feature Flag 设计

所有新增功能通过环境变量控制开关，支持灰度上线：

```yaml
# config/feature_flags.yaml
features:
  idempotency:
    enabled: false           # Phase 1 默认关闭
    redis_ttl_hours: 24
    fallback_to_local: true  # Redis不可用时降级
    
  checkpoint:
    enabled: false           # Phase 1 默认关闭
    redis_ttl_hours: 1
    fallback_to_memory: true
    
  loop_detection:
    enabled: false           # Phase 2 默认关闭
    window_size: 5
    repeat_threshold: 3
    
  tool_timeout:
    enabled: false           # Phase 2 默认关闭
    default_timeout_ms: 30000
    max_retries: 3
    
  tool_result_wrapping:
    enabled: false           # Phase 3 默认关闭
    
  perception_pipeline:
    enabled: false           # Phase 4 默认关闭
    enable_query_rewriter: true
    enable_intent_extractor: true
    skip_on_error: true      # 某阶段失败跳过而非中断
    
  planner_validation:
    enabled: false           # Phase 5 默认关闭
    strict_mode: false       # 严格模式：验证失败终止 vs 警告继续
    
  engine_agent_mode:
    enabled: false           # Phase 6 默认关闭
    
  llm_mode_selection:
    enabled: false           # Phase 8 默认关闭
    fallback_to_keyword: true # LLM失败时回退到关键词匹配
    
  skills_semantic_match:
    enabled: false           # Phase 8 默认关闭
    similarity_threshold: 0.6
```

### 性能预算

| 新增功能 | 预估延迟增加 | 预算 |
|---------|------------|------|
| 幂等检查（Redis） | +2-5ms | < 10ms |
| Checkpoint保存 | +20-50ms | < 100ms |
| 循环检测 | +1-2ms | < 5ms |
| 工具超时控制 | 0ms（仅包装） | 0ms |
| ToolResult包装 | +1-2ms | < 5ms |
| Query改写（LLM） | +200-500ms | < 1000ms |
| 意图提炼（LLM） | +200-500ms | < 1000ms |
| Planner验证 | +50-100ms（LLM） | < 200ms |
| Skills语义匹配 | +10-20ms（embedding） | < 50ms |
| **总计（全开）** | **+484-1179ms** | **< 2000ms** |

### 成本预算（按日活1000用户估算）

| 新增LLM调用 | 每次Token | 日调用量 | 日成本（GPT-4o） |
|------------|----------|---------|-----------------|
| Query改写 | ~200 tokens | 1000 | ~$0.50 |
| 意图提炼 | ~150 tokens | 1000 | ~$0.38 |
| Planner验证 | ~300 tokens | 300（仅Plan模式） | ~$0.23 |
| LLM模式选择 | ~100 tokens | 1000 | ~$0.25 |
| LLM自愈建议 | ~200 tokens | 100（仅错误时） | ~$0.05 |
| **总计** | | | **~$1.41/天，~$42/月** |

### 监控与告警

| 指标 | 告警阈值 | 级别 |
|------|---------|------|
| 幂等Redis命中率 | < 50%（异常低） | WARNING |
| Checkpoint恢复成功率 | < 95% | CRITICAL |
| 循环检测误判率 | > 5% | WARNING |
| 工具超时率 | > 10% | WARNING |
| 工具重试成功率 | < 50% | WARNING |
| PerceptionPipeline延迟P99 | > 2000ms | WARNING |
| LLM模式选择准确率（人工抽查） | < 80% | WARNING |
| Skills匹配准确率（人工抽查） | < 70% | WARNING |
| Engine路由误判率 | > 5% | CRITICAL（客服投诉漏判） |