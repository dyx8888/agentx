## Why

对照《Agent智能体应用》文档的7大模块标准，经过对全部6个模块的深入代码分析，当前项目在核心架构上已有扎实基础（三层记忆、MCP/A2A协议、Plan-Execute-Reflect、LLM-as-Judge评测框架），但在以下方面存在明显短板：**工程可靠性**（幂等、中断恢复、循环检测）、**感知与思考规划**（统一管道、闭环反馈）、**多Agent协作**（并行、主从模式）、**工具调用标准化**（错误码、描述质量）。

## What Changes

### 模块1: Agent基础架构增强（记忆+感知+思考+执行）

#### 记忆系统
- 补充**短期记忆智能截断**：当前SessionStore只做数量截断(50条)，需升级为基于token的动态截断（滑动窗口+摘要压缩），避免上下文窗口溢出
- 补充**长期记忆淘汰机制**：当前Milvus语义记忆只增不删，需引入LRU/LFU淘汰策略 + TTL过期，防止无限膨胀
- 补充**记忆注入策略优化**：当前`get_agent_context_injection()`仅按固定模板拼接，需按任务类型动态选择注入哪些记忆层
- 补充**睡眠巩固触发优化**：当前固定阈值50条触发，需改为基于时间+数据量的混合触发策略
- 补充**工作记忆结构化**：当前RuntimeState中记忆字段零散，需统一为`WorkingMemory`结构体，便于checkpoint和恢复

#### 感知系统
- 补充**统一感知管道(PerceptionPipeline)**：当前InputFilter、RAG、InstructionBoundary三条感知通道各自独立，缺少统一编排
- 补充**Query改写/意图提炼**：当前用户消息直接传给Agent，缺少文档要求的"摘要、去噪、意图提炼"预处理环节
- 补充**感知结果结构化传递**：当前RAG结果手动拼接字符串，需结构化传递（含来源、置信度），让Agent决策时参考
- 补充**工具返回结果感知**：当前工具返回结果直接注入消息历史，缺少对工具返回的结构化解析和摘要

#### 思考与规划系统
- 补充**Planner质量验证**：当前Planner生成计划后直接执行，缺少对计划质量的检查（步骤是否合理、工具是否可用、是否覆盖用户需求）
- 补充**Reflector闭环反馈**：当前Reflector仅判断pass/fail，审查意见未反馈给Planner优化后续计划
- 补充**动态调整能力**：当前失败后仅重试整条计划，应支持部分失败时重新规划剩余步骤
- 补充**模式选择升级**：当前`_select_agent_mode()`仅用8个关键词匹配，准确率~60%，需升级为基于LLM的意图识别

#### 执行系统
- 补充**工具超时控制**：当前ToolLoader配置了timeout_ms但executor_node未实际使用，所有工具调用无超时保护
- 补充**自动重试机制**：当前工具调用失败直接返回错误，需实现指数退避重试（最多3次）
- 补充**工具调用追踪**：当前tracer仅记录span级别，需细化到每次工具调用的参数、耗时、结果

### 模块2: 工具调用体系完善

对照文档"Function Calling → MCP → A2A → Skills"四层架构，当前项目已有基础但需补齐以下层次：

#### Function Calling 层：工具设计五原则对齐
- 补充**工具描述规范化**：当前各工具描述质量参差不齐（如report_server中`generate_performance_report`的mock数据裸写200+行），需对齐文档五大原则：
  - **命名清晰**：动词+名词格式（如`search_flights`），当前部分工具命名模糊（如`do_task`）
  - **描述精准**：说明用途、场景、参数含义、返回格式，当前部分工具缺少参数含义说明
  - **参数设计**：自然语言命名，详细描述，提供示例/枚举，区分必填可选，当前部分工具参数不提供example
  - **错误友好**：返回自然语言错误信息，便于模型转述或重试，当前返回自由文本
  - **单一职责**：一个工具只做一件事，当前`generate_performance_report`混合了数据+格式+计算
  - **副作用标注**：写操作需提示"真实影响"，建议确认，当前仅`schedule_task`有`requires_approval`
- 补充**Function Calling Schema标准化**：当前工具Schema由MCP Server自行定义，缺少统一的Schema验证和增强流程
  - 定义Schema → 模型决策是否调用及填参 → 输出调用指令 → 程序执行 → 返回结果 → 模型整合回答
  - 确保工具描述是模型正确选用的**唯一依据**

#### MCP 协议层：Client-Server架构完善
- MCP工具增加**结构化错误返回值**：当前工具失败时返回自由文本（如`f"生成报告时出错：{str(e)}"`），LLM难以理解并重试，需统一为ToolResult
- 补充**MCP资源暴露**机制：当前MCP Server仅暴露工具(tools)，未暴露资源(resources)和数据提示(prompts)，需按MCP规范扩展
- 在ToolLoader中增加**MCP Server健康检查**：启动时验证所有MCP Server连接状态，不健康时降级处理
- **MCP工具描述增强**：当前MCP stdio加载的工具描述由MCP Server自行定义，质量不可控，需在ToolLoader中增加描述校验和自动增强

#### A2A 协议层：Agent间通信增强
- 补充**A2A状态追踪**：当前`a2a_delegate_task`仅返回最终结果，缺少中间状态查询（如"进行中/已完成/失败"），需实现任务状态轮询接口
- 补充**A2A消息格式标准化**：当前A2A消息格式自由定义，需对齐Google A2A规范的Task/Message/Artifact结构
- 补充**A2A能力协商**：Agent Card中声明的能力应与实际MCP工具列表动态同步，而非静态配置

#### Skills 层：技能包体系深化
- **Skills关键词匹配升级**：当前`match_skill()`仅用字符串包含匹配，无法处理同义词和语义相似表达，需升级为embedding-based语义匹配
- 补充**Skills组合封装**：文档强调Skills="工具链+提示词+知识库"组合封装，当前Skills仅定义工具列表，缺少提示词模板和知识库关联
- 补充**Skills动态加载**：当前Skills在启动时加载后不再更新，需支持热加载新技能

#### 跨层改进
- **工具配置去重**：当前`tools.yaml`和`tool_providers.yaml`存在大量重复定义，需统一到`tool_providers.yaml`并废弃旧配置
- 补充**四层架构文档**：在项目文档中明确FC→MCP→A2A→Skills的层次关系和调用链路

### 模块3: 工作流与自主规划的边界

对照文档"固定工作流 vs 自主规划"的核心决策框架，当前项目需完善以下方面：

#### 模式选择决策升级
- 当前`_select_agent_mode()`仅用8个关键词匹配，准确率估计~60%。需升级为基于LLM的意图识别，准确率目标>90%
- 补充**决策三问**机制，在路由前自动评估：
  1. 流程能否提前写死？→ 能：倾向工作流；不能：倾向Agent
  2. 容错率如何？→ 极低：加人工确认或回归工作流
  3. 延迟和成本敏感吗？→ 极敏感：工作流；任务价值高可接受：Agent
- 补充**复杂度评分**：基于LLM对用户请求进行复杂度打分（1-10），低复杂度(<4)走工作流，高复杂度(>6)走Agent

#### Engine-Agent边界明确化
- **Engine与Agent边界模糊**：当前9个Engine（如customer_service_engine）和Agent并存，但Engine是确定性工作流、Agent是LLM驱动的自主规划，两者的调用关系和职责边界不清晰。需明确：Engine应作为Agent的**工具**被调用，而非替代Agent
- 补充**Agent内嵌固定子步骤**模式：通过System Prompt约束Agent在某些环节按固定步骤执行（如"客服回复前必须核实用户身份"），实现"Agent框架+工作流约束"的混合
- 补充**工作流调度Agent**模式：主流程固定（如订单处理流水线），但复杂子任务（如内容创作、数据分析）交给Agent

#### 组合使用策略深化
- 补充**混合模式**：对于明确的高风险场景（如客服投诉），应支持Engine（确定性流程）主导，Agent（LLM）仅在关键决策点介入
- 补充**工作流可视化编排**：当前客户新增一个固定工作流需要写Python代码，应支持YAML/JSON配置化编排
- 补充**Engine路由表**：`config/engine_routes.yaml` 定义何时走Engine何时走Agent，支持关键词、意图类型、复杂度评分等多维度匹配

### 模块4: 多Agent协作模式完善
- 补充**并行模式**实现：当前A2A仅支持串行任务委派(`a2a_delegate_task`)，缺少并行分派+汇总(`a2a_delegate_parallel`)
- 补充**Agent Card**标准化：当前A2AAdapter的`get_agent_card()`返回的card缺少`url`、`skills`、`defaultInputModes`、`defaultOutputModes`等Google A2A规范字段
- 补充**主从模式**：当前所有Agent平级，缺少Orchestrator Agent统一调度子Agent
- 补充**结果汇总与冲突解决**：并行执行多Agent后，缺少结果汇总Agent和冲突检测机制

### 模块5: 原型构建效率
- 补充**Agent脚手架工具**：快速创建新Agent的CLI模板
- 补充**Few-shot示例库**：当前prompt中示例硬编码，应提取为可配置的示例库

### 模块6: 工程可靠性（重点）

对照文档"四大可靠性机制"（中断恢复、幂等性、循环检测、超时降级），当前项目已有初步设计，需深化：

#### 任务中断恢复
- 补充**任务中断恢复**：通过LangGraph checkpointer + RedisSaver实现checkpoint机制
- 补充**步骤无状态化**：每个步骤设计为"基于状态快照的无状态执行"，避免恢复时依赖内存状态
- 补充**任务队列持久化**：使用消息队列（Redis Stream）管理任务生命周期，天然支持持久化和重试

#### 幂等性设计
- 补充**幂等性设计**：为副作用操作（如schedule_task）引入幂等键，格式`idem:{company_id}:{agent}:{tool}:{hash(params)}`
- 补充**幂等键由Agent生成**：在System Prompt中注入幂等键生成规则，Agent在调用副作用工具时自动生成稳定幂等键
- 补充**幂等结果缓存**：重复请求返回已有结果时附带"此结果来自缓存"标识，让模型知道这是幂等返回

#### 循环检测
- 补充**循环检测升级**：当前仅max_iterations(MAX_RETRIES=3)，需增加状态指纹（滑动窗口5步，3次重复=循环）
- 补充**提示词注入循环意识**：在Agent System Prompt中注入"尝试N次无果后请停止并告知用户"的循环终止指令
- 补充**外部超时监控**：独立于Agent进程的超时监控协程，超时后强制终止并保存checkpoint

#### 超时与降级处理
- 补充**工具超时重试**：当前ToolLoader有timeout_ms配置但executor未使用，需在executor_node中集成asyncio.wait_for
- 补充**四级降级策略**（文档定义）：
  1. 使用缓存数据（注明可能延迟）
  2. 切换备用数据源
  3. 跳过非关键步骤，生成部分结果告知用户
  4. 关键步骤转人工工单
- 补充**降级规则注入Prompt**：在Agent System Prompt中明确降级行为规则，使Agent在工具失败时知道如何降级

#### 协同工作流
- 补充**可靠性协同流程**：任务开始→持久化状态/生成幂等键→执行步骤（循环检测+超时控制+降级）→副作用操作幂等执行→中断时从状态恢复→最终完成或安全终止
- 统一**错误处理框架**：ToolResult类已定义但未在所有工具中强制使用，需扩展为所有工具的标准返回类型
- 补充**工程落地要点**文档化：所有外部调用工具必须包装错误处理和超时；使用Redis/DB保存任务状态和幂等记录；Agent提示词必须包含异常处理与降级行为指令；监控Agent循环次数、工具超时率

### 模块7: 评测与迭代（重点）

对照文档"评测指标体系"和"迭代优化循环"，当前项目已有基础框架，需深化：

#### 评测指标体系
- **已有基础**：项目已有`tests/evaluation/runner.py`（加载YAML用例→调用Agent→LLMJudge打分→JSON报告）和`tests/evaluation/judge.py`（4维度LLM-as-Judge评分），但仅1个测试用例文件(brand_bd.yaml)
- 扩充**测试用例集**：从1个Agent扩展到覆盖全部Agent，每个Agent至少3个典型场景+1个异常场景+1个安全边界
- 建立**评测指标体系**：在现有LLM-as-Judge（任务完成/格式规范/安全合规/可执行性）基础上，增加工具调用准确率、平均步数、Token消耗
- 补充**执行效率指标**：平均步数、P95耗时、Token消耗（输入+输出），作为成本和性能的量化依据

#### 评测方法完善
- 补充**全链路Trace记录**：评测运行中记录完整的思考-行动-观察Trace，而非仅输入输出
- 补充**人工校准机制**：定期抽检评分结果（建议10%），确保LLM-as-Judge评判质量，维护golden test set
- 补充**规则匹配+LLM混合评分**：工具调用准确率用规则匹配（精确比对），任务完成用LLM-as-Judge（语义评估）

#### 迭代优化循环
- 补充**根因分析模式**：从低分案例中自动归纳问题模式：
  - 规划推理差 → 改进提示词、加示例
  - 工具选择错误 → 优化工具描述、参数说明
  - 异常处理差 → 加强降级规则与提示
  - 安全不达标 → 增加护栏和红队训练
  - 幻觉/编造 → 强化RAG检索和事实核查
- 补充**回归测试**：每次修改后重新跑评测集，对比分数，防止退化
- 补充**上线监控**：持续观察生产指标，异常告警，采样加入测试集
- 升级**Evolution/Suggester**：当前Suggester依赖人工修改反馈(feedback.db)，需增加基于评测结果的自动触发优化

#### CI集成与工程化
- 补充**CI集成**：评测流水线通过`python -m tests.evaluation.runner`触发，CI中非0退出码表示未通过
- 补充**测试集随业务迭代更新**策略：纳入真实故障案例，每次线上事故后自动生成测试用例
- 补充**评测通过阈值**：任务完成率 >= 80%，工具调用准确率 >= 70%，安全合规 >= 95%

### 跨模块架构清理
- 移除**legacy agent代码**：agent.py中标记deprecated的`get_agent()`、`get_agent_async()`、`get_agent_for_tools()`和`chat.py`中的双重路径
- 统一**配置管理**：将分散在`tools.yaml`和`tool_providers.yaml`中的重复配置统一，废弃旧文件
- 补充**思考与规划模块**到提案（原缺失）：Planner验证、Reflector闭环、动态调整、模式选择升级

## Capabilities

### New Capabilities
- `agent-idempotency`: Agent副作用操作的幂等性保障，包括幂等键生成、服务端去重、重复请求返回已有结果
- `agent-checkpoint-recovery`: 任务中断恢复机制，包括状态持久化、检查点保存/恢复、任务队列管理
- `agent-evaluation-pipeline`: 自动化评测流水线（已有框架，需扩展），包括测试用例管理、指标计算、CI集成、评测报告生成
- `agent-loop-detection`: 增强的循环检测，包括状态指纹、重复模式检测、智能终止策略
- `tool-error-standardization`: 工具错误标准化，包括结构化错误码、LLM可读的错误消息、自动重试建议
- `parallel-agent-execution`: 多Agent并行执行模式，包括并行分派、结果汇总、超时协调
- `agent-scaffold-cli`: Agent脚手架CLI工具，快速生成新Agent模板代码
- `perception-pipeline`: 统一感知管道，包括Query改写、意图提炼、感知结果结构化、工具返回解析
- `memory-lifecycle`: 记忆生命周期管理，包括短期记忆智能截断、长期记忆LRU淘汰、工作记忆结构化、睡眠巩固优化
- `planning-enhancement`: 思考规划增强，包括Planner质量验证、Reflector闭环反馈、动态调整、LLM意图识别
- `engine-agent-integration`: Engine-Agent混合模式，明确边界、Engine作为Agent工具、工作流YAML编排

### Modified Capabilities
<!-- 无现有specs需要修改 -->

## Impact

- **后端核心**: `app/agent.py`（移除legacy代码）、`app/runtime/orchestrator.py`（增加checkpoint/loop检测/工作记忆结构化/Planner验证/Reflector闭环）、`app/runtime/executor_node.py`（增加幂等/超时/重试/工具调用追踪）
- **感知层**: `app/middleware/input_filter.py`（集成到统一管道）、`app/api/chat.py`（重构感知流程）、新增 `app/perception/`（PerceptionPipeline、QueryRewriter、IntentExtractor）
- **工具层**: `app/tools/`（统一错误码、描述增强）、`app/mcp_servers/`（结构化错误返回、描述规范）、`app/skills/registry.py`（embedding语义匹配）
- **记忆层**: `app/runtime/memory.py`（LRU淘汰、混合触发）、`app/services/session_store.py`（智能截断）、新增 `app/core/working_memory.py`
- **通信层**: `app/communication/a2a_adapter.py`（Agent Card标准化、并行执行、主从模式）
- **评测层**: `tests/evaluation/`（扩充测试用例、增强指标、CI集成）、`app/evolution/suggester.py`（评测驱动优化）
- **引擎层**: `app/engines/`（Engine作为Agent工具注册、YAML编排）
- **新增**: `app/evaluation/`（评测指标计算）、`app/cli/`（脚手架CLI）、`app/core/idempotency.py`、`app/core/checkpoint.py`
- **配置**: `config/` 目录结构统一化（废弃tools.yaml，统一到tool_providers.yaml）
- **CI/CD**: 新增评测流水线配置