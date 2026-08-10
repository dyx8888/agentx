## ADDED Requirements

### Requirement: 工作台总览
老板驾驶舱首页 MUST 展示公司当前所有数字员工的工作状态概览，包含：在线的 Agent 数量、进行中的任务数、今日完成任务数、待审核事项数。

#### Scenario: 老板登录后看到工作台
- **WHEN** 企业主登录系统进入 Dashboard
- **THEN** 系统展示统计卡片（在线 Agent、进行中任务、今日完成、待审核）

### Requirement: 数字员工状态面板
老板驾驶舱 MUST 提供每个数字员工的实时状态视图，包含：Agent 名称、类型标签（保障型/增长型）、当前状态（空闲/工作中/异常）、最近完成的任务摘要、Token 消耗量、当前使用的模型。

#### Scenario: 查看品牌商务 Agent 的当前状态
- **WHEN** 企业主点击"品牌商务"Agent 卡片
- **THEN** 系统展示该 Agent 的当前执行状态、最近 5 条任务记录、本月 Token 消耗、当前配置的 LLM 模型

#### Scenario: 快速切换 Agent 模型
- **WHEN** 企业主发现某 Agent 效果不佳
- **THEN** 可在状态面板中直接切换 Agent 的主模型（如从 DeepSeek-V3 切换到 DeepSeek-R1）

### Requirement: 任务管理与审核列表
老板驾驶舱 MUST 提供全公司任务列表视图，支持按状态（pending/processing/completed/failed）、按 Agent、按审核级别（强制审核/推荐审核/自动通过）、按时间范围筛选。审核列表分组展示，强制审核置顶。

#### Scenario: 审核心达人邀约话术
- **WHEN** 企业主在审核列表中看到品牌商务生成的邀约话术（强制审核）
- **THEN** 企业主可以直接批准、修改后批准或拒绝→操作结果实时通过 WebSocket 通知品牌商务 Agent

#### Scenario: 批量处理推荐审核项
- **WHEN** 多条内容脚本在推荐审核列表中
- **THEN** 企业主可全选→一键批准→系统自动执行后续流程

### Requirement: 数据看板
老板驾驶舱 MUST 提供关键经营数据看板，包含：本周/本月任务完成趋势图、各 Agent 工作量分布、Token 消耗趋势、达人合作 ROI 汇总、投放效果趋势。

#### Scenario: 查看本月工作量分布
- **WHEN** 企业主进入数据分析页面
- **THEN** 系统展示本月每个 Agent 的任务完成数量柱状图、Token 消耗折线图、各 Agent 产出数量排名

### Requirement: 实时告警推送

老板驾驶舱 MUST 实时接收数据异常告警。数据分析 Agent 检测到异常后，同时推送 Dashboard（WebSocket + PWA 通知）和相关 Agent。

告警类型包括：
- 销售异常（GMV 骤降、转化率异常、退货率飙升）
- 投放异常（ROI 跌破阈值、CPA 超标、消耗异常）
- 库存异常（库存告急、滞销预警）
- 服务异常（差评突增、响应超时）
- 物流异常（包裹停滞、丢件预警）

#### Scenario: 实时接收转化率异常告警
- **WHEN** 数据分析 Agent 检测到某产品转化率同比下跌超过 30%
- **THEN** Dashboard 弹出红色告警→PWA 推送通知→告警详情包含归因分析初步结果→相关 Agent（智能投流+内容运营）自动注入告警上下文

#### Scenario: 告警已读/处理标记
- **WHEN** 企业主查看告警详情并标记为"已知悉"或"处理中"
- **THEN** 系统更新告警状态→Dashboard 告警列表实时同步→同公司其他成员可见处理进度

### Requirement: 公司设置
老板驾驶舱 MUST 提供公司设置入口，企业主可以在设置中：管理各平台账号凭证（加密存储）、配置自有 LLM API Key、为每个 Agent 独立配置 LLM 模型、管理职位订阅和到期时间、创建/编辑自定义 Agent、添加/删除公司成员账号、配置协作链规则。

#### Scenario: 配置企业自有 LLM Key
- **WHEN** 企业主在设置页面填入 DeepSeek API Key 并保存
- **THEN** 系统加密存储凭证→所有 Agent 自动切换使用企业自有 Key→Token 消耗统计开始记录

#### Scenario: 管理平台 API 凭证
- **WHEN** 企业主填入抖音开放平台 API Key 和 Secret
- **THEN** 系统加密存储→品牌商务可使用抖音星图 API→数据分析可使用抖音罗盘 API

---

### Requirement: PWA 移动端适配

老板驾驶舱 MUST 支持 PWA 移动端访问，企业主可在手机上查看 Dashboard、审批任务、接收告警推送。移动端聚焦核心操作：工作台概览、审核审批、告警查看。

#### Scenario: 手机端审批任务
- **WHEN** 企业主在手机上收到 PWA 推送通知"有待审核的达人邀约话术"
- **THEN** 点击通知直接打开审核页面→查看话术内容→批准/修改/拒绝→操作完成返回工作台

#### Scenario: 手机端查看告警
- **WHEN** 企业主在手机上收到转化率异常告警推送
- **THEN** 点击打开告警详情→查看归因分析→标记已读→Dashboard 同步更新

#### Scenario: PWA 安装到主屏幕
- **WHEN** 企业主首次在手机上访问 Dashboard
- **THEN** 浏览器提示「添加到主屏幕」→安装后生成独立图标→支持推送通知→启动画面
