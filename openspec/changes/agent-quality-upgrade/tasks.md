## 1. 幂等性模块 (agent-idempotency)

- [x] 1.1 创建 `app/core/idempotency.py`，实现 `IdempotencyManager` 类
- [x] 1.2 实现幂等键生成：`idem:{company_id}:{agent_name}:{tool_name}:{hash(params)}`
- [x] 1.3 实现Redis存储 + 本地内存降级策略
- [x] 1.4 在 `executor_node.py` 中集成幂等检查：副作用工具调用前先check
- [x] 1.5 为 `schedule_task`、`a2a_delegate_task` 等副作用工具添加 `side_effect: true` metadata

## 2. 中断恢复模块 (agent-checkpoint-recovery)

- [x] 2.1 实现 LangGraph RedisSaver checkpointer
- [x] 2.2 在 `AgentRuntime._build_graph()` 中集成 checkpointer
- [x] 2.3 实现 `thread_id` 生成和恢复逻辑
- [x] 2.4 实现检查点自动清理（任务完成后 + TTL过期）
- [x] 2.5 添加Redis不可用时的内存降级策略

## 3. 循环检测升级 (agent-loop-detection)

- [x] 3.1 在 `executor_node.py` 中实现 `_detect_loop()` 函数
- [x] 3.2 实现状态指纹计算：`hash(agent_name + tool_name + tool_args)`
- [x] 3.3 实现滑动窗口（最近5步）检测逻辑
- [x] 3.4 在 `RuntimeState` 中添加 `fingerprint_window` 字段
- [x] 3.5 循环触发时返回结构化错误消息

## 4. 工具超时与重试

- [x] 4.1 在 `executor_node.py` 中为工具调用添加 `asyncio.wait_for` 超时控制
- [x] 4.2 从 `tool_providers.yaml` 读取 `timeout_ms` 配置（当前已配置但未使用）
- [x] 4.3 实现自动重试逻辑（最多3次，指数退避 1s/2s/4s）
- [x] 4.4 超时/重试失败后返回结构化 ToolResult（使用 ErrorCode.TOOL_TIMEOUT）
- [x] 4.5 在 `executor_node.py` 中添加工具调用耗时追踪

## 4A. 四级降级策略

- [x] 4A.1 在 `executor_node.py` 中实现 `_degrade_tool()` 四级降级函数
- [x] 4A.2 实现降级策略1：使用缓存数据（标注 `source: "cache"` 和时间戳）
- [x] 4A.3 实现降级策略2：切换备用数据源（`tool_providers.yaml` 中配置 `fallback_url`）
- [x] 4A.4 实现降级策略3：跳过非关键步骤（`tool_providers.yaml` 中配置 `critical: false`）
- [x] 4A.5 实现降级策略4：转人工工单（生成工单ID，暂停Agent等待人工介入）
- [x] 4A.6 在 `tool_providers.yaml` 中为每个工具增加降级配置段（`fallback`、`cache_ttl`、`critical`）
- [x] 4A.7 在Agent System Prompt中注入降级行为规则

## 5. 工具错误标准化 (tool-error-standardization)

- [x] 5.1 完善 `app/tools/result.py` 中的 `ErrorCode` 枚举（已定义6个，需补充 PERMISSION_DENIED）
- [x] 5.2 扩展 `ERROR_SUGGESTIONS` 映射表，为每个错误码添加LLM自愈建议
- [x] 5.3 迁移 `report_server.py` 的 `generate_performance_report` 等工具返回值为 ToolResult
- [x] 5.4 迁移 `kol_search_server.py` 的 `search_kols` 返回值为 ToolResult
- [x] 5.5 迁移其他 MCP Server 工具返回值为 ToolResult（outreach_server, script_server, monitor_server）
- [x] 5.6 统一 `knowledge_retrieval_server.py` 错误处理：`return []` 改为 `ToolResult.error(...)`
- [x] 5.7 在 `executor_node.py` 中实现 `_wrap_tool_result` 自动解析 ToolResult 并注入LLM可读消息

## 6. 工具描述规范化 (tool-description-standardization)

- [x] 6.1 清理 `report_server.py` 中 `generate_performance_report` 的200+行mock数据，改为外部数据源
- [x] 6.2 为所有MCP工具补充标准docstring格式：Purpose / When to Use / Parameters / Returns / Example
- [x] 6.3 在 `ToolLoader._load_mcp_stdio()` 中增加工具描述校验：长度 > 20字符，包含参数说明
- [x] 6.4 为描述不足的工具自动调用LLM增强描述（基于函数签名和参数名）
- [x] 6.5 统一 `tools.yaml` 和 `tool_providers.yaml` 中的重复配置，废弃 `tools.yaml`

## 6A. MCP协议增强

- [x] 6A.1 在 `ToolLoader` 中实现 `ToolSchemaValidator`：五原则自动评分（命名/描述/参数/错误/职责）
- [x] 6A.2 评分阈值60分，低于阈值自动调用LLM增强工具描述
- [x] 6A.3 扩展MCP Server支持资源(resources)暴露：`list_resources()`、`read_resource()`
- [x] 6A.4 扩展MCP Server支持数据提示(prompts)暴露：`list_prompts()`、`get_prompt()`
- [x] 6A.5 在ToolLoader中增加MCP Server健康检查：启动时验证所有Server连接，不健康时WARNING日志+降级
- [x] 6A.6 实现MCP Server连接池：复用连接，避免每次调用重新建立stdio进程

## 6B. A2A状态追踪与任务生命周期

- [x] 6B.1 在 `a2a_adapter.py` 中实现任务状态管理：`task_status(task_id)` 轮询接口
- [x] 6B.2 状态流转：PENDING → RUNNING → COMPLETED / FAILED / TIMEOUT
- [x] 6B.3 使用Redis存储任务状态：`a2a:task:{task_id}` → `{status, result, created_at, updated_at}`
- [x] 6B.4 实现A2A消息格式标准化：对齐Google A2A规范的Task/Message/Artifact结构
- [x] 6B.5 实现A2A能力协商：Agent Card中capabilities与MCP工具列表动态同步

## 6C. Skills组合封装增强

- [x] 6C.1 扩展 `SkillMeta` 数据结构：增加 `prompt_template` 和 `knowledge_base_ids` 字段
- [x] 6C.2 实现Skills动态加载：文件监听 + 热加载新技能，无需重启服务
- [x] 6C.3 为每个SKILL.md增加关联知识库配置（Milvus collection名称）

## 7. Skills语义匹配升级 (skills-semantic-matching)

- [x] 7.1 在 `skills/registry.py` 的 `match_skill()` 中替换字符串包含匹配为 embedding 语义匹配
- [x] 7.2 为每个 SKILL.md 预计算 embedding 向量，存储在 `_skill_embeddings` 缓存中
- [x] 7.3 用户查询计算 embedding，与所有技能做余弦相似度排序，取 top-3
- [x] 7.4 设置相似度阈值（默认 0.6），低于阈值不匹配

## 8. 评测流水线 (agent-evaluation-pipeline)

- [x] 8.1 扩充测试用例：从1个Agent(brand_bd)扩展到覆盖全部Agent，每个Agent 3个典型场景 + 1个异常场景 + 1个安全边界
- [x] 8.2 在 `MetricsCalculator` 中增加工具调用准确率、平均步数、Token消耗指标
- [x] 8.3 实现 `ReportGenerator`：生成JSON和Markdown格式的评测报告
- [x] 8.4 实现CLI入口：`python -m tests.evaluation.runner --ci` 支持CI模式
- [x] 8.5 创建GitHub Actions / GitLab CI配置，集成评测流水线
- [x] 8.6 设置评测通过阈值（完成率 >= 80%，工具准确率 >= 70%）
- [x] 8.7 升级 `app/evolution/suggester.py`：基于评测结果自动触发优化建议

## 8A. 评测根因分析

- [x] 8A.1 实现 `RootCauseAnalyzer`：从低分案例中自动归纳失败模式
- [x] 8A.2 失败模式分类：规划错误、工具误选、参数错误、幻觉、安全绕过、异常处理差
- [x] 8A.3 每种失败模式关联优化建议：规划错误→改进提示词+加示例；工具误选→优化工具描述；安全绕过→增加护栏
- [x] 8A.4 实现根因分析报告生成：Top 3失败模式 + 对应优化建议 + 影响案例数

## 8B. 人工校准与迭代

- [x] 8B.1 实现人工校准机制：每50次评测抽检5次，校准LLM-as-Judge评分
- [x] 8B.2 维护golden test set：人工标注的标准答案集合，用于校准LLM-as-Judge
- [x] 8B.3 实现回归测试：修改后自动跑评测集，对比上次分数，低于阈值告警
- [x] 8B.4 实现测试集随业务迭代更新：纳入真实故障案例，每次线上事故后自动生成测试用例

## 8C. 全链路Trace记录

- [x] 8C.1 评测运行中记录完整的思考-行动-观察Trace（而非仅输入输出）
- [x] 8C.2 Trace包含：每步的thought、工具调用参数/结果、耗时、Token消耗
- [x] 8C.3 实现Trace可视化：生成HTML格式的评测Trace报告，支持按步骤展开

## 9. 并行Agent执行 (parallel-agent-execution)

- [x] 9.1 实现 `a2a_delegate_parallel` 工具函数：`a2a_delegate_parallel(tasks: list[dict]) -> list[dict]`
- [x] 9.2 使用 `asyncio.gather` 实现并行分派，`return_exceptions=True` 实现部分失败容错
- [x] 9.3 实现全局超时（60秒）+ 超时后返回已完成任务结果
- [x] 9.4 标准化 Agent Card 格式：补充 `url`、`skills`、`defaultInputModes`、`defaultOutputModes` 字段
- [x] 9.5 实现 `OrchestratorAgent` 主从模式：统一调度子Agent，汇总结果
- [x] 9.6 实现结果汇总Agent：并行执行后的结果去重和冲突检测

## 9A. 分层Agent架构（金字塔模式）

- [x] 9A.1 实现 `HierarchicalOrchestrator`：支持多层嵌套（总指挥→组长→组员），最大3层
- [x] 9A.2 实现层级间通信规范：向上汇报结构化摘要（JSON），向下传递子任务（含上下文）
- [x] 9A.3 实现层级深度限制：超过3层时自动合并，防止信息传递失真
- [x] 9A.4 实现层级超时控制：每层独立超时，父层可提前终止子层

## 9B. 串行流水线增强

- [x] 9B.1 实现流水线上下文传递：前一个Agent的输出结构化传递给下一个Agent（非纯自然语言）
- [x] 9B.2 实现流水线进度追踪：记录每个Agent的执行状态（等待中/执行中/已完成/失败）
- [x] 9B.3 实现流水线可视化：生成Mermaid格式的流水线执行图（含耗时和状态）

## 9C. 协作模式自动选择

- [x] 9C.1 实现协作模式选择器：基于任务特征自动推荐（固定接力→串行，独立任务→并行，动态调度→主从，超大工程→分层）
- [x] 9C.2 实现混合模式支持：主流程并行+子任务串行，或主Agent串行调用多个并行组

## 10. Agent脚手架CLI (agent-scaffold-cli)

- [x] 10.1 创建 `app/cli/` 模块
- [x] 10.2 实现 `create-agent` 命令，基于模板生成Agent文件
- [x] 10.3 模板包含：PROMPT_VERSION、SYSTEM_PROMPT、CAPABILITIES、三个标准函数
- [x] 10.4 支持 `--force` 覆盖已存在的Agent

## 10A. 任务分解工具

- [x] 10A.1 实现 `python -m app.cli decompose-task "需求描述"` 命令，调用LLM自动分解任务树
- [x] 10A.2 生成任务依赖图（Mermaid格式），标注串行/并行关系
- [x] 10A.3 在脚手架模板中增加任务分解原则注释：单一职责、输入输出、成功标准、串并行区分

## 10B. 角色划分向导

- [x] 10B.1 实现CLI交互式角色划分向导：根据任务特征推荐单Agent vs 多Agent
- [x] 10B.2 单Agent多工具：任务集中、工具少，结构简单，推荐初期使用
- [x] 10B.3 多Agent主从/分层：任务跨领域、工具多且异构，推荐大规模项目

## 10C. 生产化模板

- [x] 10C.1 脚手架生成的Agent包含默认测试用例模板（`tests/evaluation/cases/{agent_name}.json`）
- [x] 10C.2 脚手架生成的工具函数包含默认错误处理模板（`try/except` + `ToolResult.error`）
- [x] 10C.3 脚手架生成的Agent包含默认日志记录点（工具调用前后、LLM调用前后）
- [x] 10C.4 Agent文件CHANGELOG区域扩展为迭代记录模板（版本、变更、评测分数、备注）

## 11. 记忆生命周期管理 (memory-lifecycle)

- [x] 11.1 在 `SessionStore` 中实现基于token的智能截断（替换纯数量截断）
- [x] 11.2 实现截断时的摘要压缩：LLM将被截断消息压缩为摘要注入
- [x] 11.3 在 `ThreeLayerMemoryManager` 中实现长期记忆LRU淘汰策略
- [x] 11.4 实现高置信度记忆保护（confidence >= 0.9 跳过淘汰）
- [x] 11.5 创建 `app/core/working_memory.py`，定义 `WorkingMemory` 结构体
- [x] 11.6 在 `AgentRuntime` 中集成 `WorkingMemory`，替换零散状态字段
- [x] 11.7 实现睡眠巩固混合触发：时间触发 + 数据量触发
- [x] 11.8 实现睡眠巩固去重保护（防止并发执行）

## 12. 统一感知管道 (perception-pipeline)

- [x] 12.1 创建 `app/perception/` 模块（PerceptionPipeline、QueryRewriter、IntentExtractor）
- [x] 12.2 实现 `QueryRewriter`：基于LLM的Query改写，补全省略+口语转结构化
- [x] 12.3 实现 `IntentExtractor`：基于LLM的意图提炼，输出结构化意图对象
- [x] 12.4 实现 `PerceptionPipeline`：按序编排 InputFilter → QueryRewriter → IntentExtractor → RagRetriever → ToolResultParser
- [x] 12.5 定义 `PerceptionContext` 数据结构（含所有感知阶段输出）
- [x] 12.6 在 `chat.py` 中集成 PerceptionPipeline，替换手动拼接的感知流程
- [x] 12.7 实现 `ToolResultParser`：对工具返回结果进行结构化解析和摘要

## 13. 思考规划增强 (planning-enhancement)

- [x] 13.1 在 `planner_node.py` 后增加 `_validate_plan()` 函数：检查工具可用性、步骤具体性、需求覆盖度
- [x] 13.2 在 `reflector_node.py` 中实现Reflector建议 → Planner的闭环反馈机制
- [x] 13.3 在 `orchestrator.py` 中实现 `_dynamic_replan()` 部分失败时重新规划剩余步骤
- [x] 13.4 连续2次动态调整失败后终止执行，返回已完成结果
- [x] 13.5 实现 `_select_agent_mode_by_llm()` 基于LLM的意图识别替代关键词匹配
- [x] 13.6 在 `RuntimeState` 中增加 `plan_history`、`reflection_feedback` 字段

## 14. Engine-Agent混合模式 (engine-agent-integration)

- [x] 14.1 将所有Engine注册为ToolRegistry中的工具：`call_engine(engine_name, params)`
- [x] 14.2 实现 `CustomerServiceEngine` 的Engine主导模式：高风险场景Engine主导，Agent仅在内容生成介入
- [x] 14.3 创建 `config/workflows/` 目录，定义YAML工作流编排格式
- [x] 14.4 实现 `WorkflowLoader`：从YAML加载工作流定义并生成Engine实例
- [x] 14.5 在 `chat.py` 中实现统一路由表：`engine_routes.yaml` 定义Engine路由规则
- [x] 14.6 创建 `config/engine_routes.yaml` 示例：客服投诉 → CustomerServiceEngine

## 14A. 模式选择决策增强

- [x] 14A.1 在 `_select_agent_mode()` 中增加决策三问逻辑：能写死→工作流 / 容错低→加确认 / 成本敏感→工作流
- [x] 14A.2 实现任务复杂度评分：基于LLM对用户请求打分（1-10），低复杂度(<4)走工作流，高复杂度(>6)走Agent
- [x] 14A.3 实现Engine路由表：`config/engine_routes.yaml` 支持关键词、意图类型、复杂度评分多维度匹配
- [x] 14A.4 实现Agent内嵌固定子步骤模式：通过System Prompt约束Agent在特定环节按固定步骤执行
- [x] 14A.5 实现工作流调度Agent模式：主流程固定，复杂子任务交给Agent

## 15. 架构清理

- [x] 15.1 移除 `agent.py` 中标记deprecated的函数（`get_agent_for_tools`、`get_agent`、`get_agent_async`、`delegate_task`）
- [x] 15.2 简化 `chat.py` 中的双重路径（legacy agent + AgentRuntime），统一使用 AgentRuntime
- [x] 15.3 移除 `agent.py` 中 `load_tools_from_yaml`、`load_tools_from_langchain`、`load_tools_from_mcp` 旧版加载函数
- [x] 15.4 统一配置管理：废弃 `tools.yaml`，统一到 `tool_providers.yaml`
- [x] 15.5 移除 `agent.py` 中 `_auto_register_prompt_versions()` 的模块级副作用调用

## 16. 测试与验证

### 16.1 单元测试
- [x] 16.1.1 `IdempotencyManager` 单元测试：幂等命中/未命中/Redis降级/TTL过期
- [x] 16.1.2 `RedisSaver` 单元测试：保存/恢复/清理/TTL过期
- [x] 16.1.3 `_detect_loop()` 单元测试：正常执行/循环检测/边界情况
- [x] 16.1.4 `_wrap_tool_result()` 单元测试：ok/error/pending_approval/非ToolResult
- [x] 16.1.5 `QueryRewriter` 单元测试：补全/口语转结构化/空输入
- [x] 16.1.6 `IntentExtractor` 单元测试：7种意图类型/恶意输入
- [x] 16.1.7 `WorkflowLoader` 单元测试：正常YAML/缺少字段/格式错误

### 16.2 集成测试
- [x] 16.2.1 Agent调用幂等工具 → 重复请求去重
- [x] 16.2.2 Agent执行中断 → checkpoint恢复 → 继续执行
- [x] 16.2.3 PerceptionPipeline → Agent接收结构化上下文
- [x] 16.2.4 Engine主导：客服投诉 → Engine → Agent生成回复
- [x] 16.2.5 A2A并行分派：3个Agent → 汇总结果

### 16.3 性能测试
- [x] 16.3.1 幂等检查延迟基准测试（目标 < 5ms P95）
- [x] 16.3.2 Checkpoint保存延迟基准测试（目标 < 50ms P95）
- [x] 16.3.3 PerceptionPipeline延迟基准测试（目标 < 500ms P95）
- [x] 16.3.4 全功能开启回归测试（P99不超过基线的2倍）

### 16.4 混沌测试
- [x] 16.4.1 Redis宕机 → 幂等降级为本地缓存，日志记录
- [x] 16.4.2 Redis宕机 → checkpoint降级为内存，日志记录
- [x] 16.4.3 MCP Server宕机 → ToolRegistry降级，功能不中断
- [x] 16.4.4 Milvus宕机 → RAG跳过，感知管道继续

## 17. 上线准备

- [x] 17.1 创建 `config/feature_flags.yaml` 配置文件
- [x] 17.2 实现 `FeatureFlagManager` 读取feature flags
- [x] 17.3 配置监控指标采集（幂等命中率/checkpoint成功率/循环误判率等）
- [x] 17.4 配置告警规则（9个指标阈值）
- [x] 17.5 编写灰度上线方案文档（Phase 1→9 逐步开启计划）