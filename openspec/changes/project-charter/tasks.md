## 1. 阶段零：P0 致命问题修复（上线前必须完成）
- [x] 1.1 修复 JWT 默认密钥问题：启动时检测 SECRET_KEY 是否为默认值，若是则拒绝启动；改用 PyJWT 替代 python-jose
- [x] 1.2 修复 Fernet 加密密钥长度 Bug：将 PBKDF2 派生 32 bytes raw key 改为 Fernet.generate_key() 标准生成方式
- [x] 1.3 补全公司隔离：所有 API 路由注入 same_company_access 依赖，移除各处 `# TODO` 注释
- [x] 1.4 修复 agent_workflow.py 硬编码 company_id=1，改为从 AgentState 动态获取
- [x] 1.5 修复 model_gateway.py 中 FailoverChatModel.invoke() 的 asyncio.run() 问题，全部改为 async

## 2. 阶段一：基础设施升级（PostgreSQL + Redis + 引擎统一）

- [x] 2.1 切换 PostgreSQL：修改 database.py 连接配置，编写 Alembic 迁移脚本，废弃 SQLite
- [x] 2.2 部署 Redis：docker-compose 添加 Redis 容器，实现 Redis Streams 任务队列替代内存队列
- [x] 2.3 删除 agent.py 中手工 StateGraph（get_agent/get_agent_for_tools 中的重复代码），统一走 AgentRuntime（已标记废弃并重定向至 schedule_task）
- [x] 2.4 删除同步 invoke 的 delegate_task，仅保留 schedule_task 异步调度
- [x] 2.5 实现 Redis 任务队列：Task 入队/出队/重试/死信队列，Agent 消费循环
- [x] 2.6 实现 /health 健康检查端点（PostgreSQL + Redis + Milvus + 模型网关状态）
- [x] 2.7 实现 API 请求频率限制中间件（每用户 30次/分钟，每公司 10次 LLM/分钟，IP级 200次/分钟，登录 5次/5分钟）
- [x] 2.8 数据库层所有 DAO 方法添加 company_id 强制参数，审计并删除无隔离的查询

## 3. 阶段二：RAG 知识库 + CompanyContextBus

- [x] 3.1 部署 Milvus 向量数据库：docker-compose 添加 Milvus 容器
- [x] 3.2 实现文本 Embedding 服务：基于 BGE/M3E 中文模型，提供文本向量化 API
- [x] 3.3 实现 CompanyContextBus Layer 1（公司基础资料）：CRUD API + 读取注入
- [x] 3.4 实现 CompanyContextBus Layer 2（公司知识库）：向量存储 + RAG 检索 + 手动维护 API
- [x] 3.5 实现 CompanyContextBus Layer 3（公司经验记忆）：Agent 完成后自动写入摘要 + RAG 检索
- [x] 3.6 实现 Agent 上下文自动注入：执行前按配置加载对应层级数据
- [x] 3.7 实现多模态 RAG（视觉设计）：CLIP Embedding + Milvus 以图搜图

## 4. 阶段三：模型网关升级 + 企业自有 Key

- [x] 4.1 升级 ModelGateway：支持多提供商（DeepSeek/OpenAI/火山引擎），每 Agent 独立模型配置
- [x] 4.2 实现企业自有 LLM Key 管理：Company 表 llm_api_key 加密存储 + API + 前端配置页
- [x] 4.3 实现 Agent 模型路由：根据任务复杂度自动选择主模型/备选模型
- [x] 4.4 实现 Token 消耗统计：每次 LLM 调用记录消耗，Dashboard 展示（已集成 TokenUsagePersistence + model_gateway_extensions）
- [x] 4.5 实现企业 Token 配额上限：可设置每日/每月额度，超额告警

## 5. 阶段四：八大职位 Agent 实现（6 保障型 + 2 增长型）

### 5.1 品牌商务（Brand BD）——已有基础，加固
- [x] 5.1.1 完善 System Prompt + Skill 绑定（kol_screening, campaign_planning, batch_outreach, sample_tracking, performance_review）
- [x] 5.1.2 新增 kol_relationship_manager 工具（达人关系管理、档期追踪）(`agents/tools.py` manage_kol_relationship)
- [x] 5.1.3 实现邀约话术强制审核流程（pending_review → 批准/修改/拒绝）
- [x] 5.1.4 注册到 AgentRuntime 并验证 Plan-Execute-Reflect + RAG 注入

### 5.2 内容运营（Content Operator）——已有基础，重写
- [x] 5.2.1 重写内容运营 Agent：System Prompt + 多平台角色定义 + Skill 绑定
- [x] 5.2.2 实现 PlatformContextRouter：多平台独立上下文沙箱（抖音/小红书/淘宝/拼多多）
- [x] 5.2.3 创建 MCP 工具：generate_content_plan, trend_analysis, competitor_content_analysis, content_calendar_manager, live_stream_script_generator, multi_platform_publisher
- [x] 5.2.4 实现 video_editor_bridge：桥接外部视频剪辑工具（MCP 外部操控权限）(`agents/tools.py` bridge_video_editor)
- [x] 5.2.5 注册到 AgentRuntime 并验证多平台上下文切换

### 5.3 数据分析（Data Analyst）——已有基础，加固
- [x] 5.3.1 完善 System Prompt + Skill 绑定（performance_analysis, trend_forecast, anomaly_alert, weekly_report, campaign_report, competitor_benchmark）
- [x] 5.3.2 实现 MetricsEngine：确定性指标计算引擎（GMV/ROI/CPA/CTR/CVR 等，零 LLM 依赖）
- [x] 5.3.3 实现 anomaly_detection + attribution_analysis 工具
- [x] 5.3.4 实现异常告警推送：同时推送 Dashboard（WebSocket）+ 相关 Agent（上下文注入）
- [x] 5.3.5 注册到 AgentRuntime 并验证 MetricsEngine 计算准确性

### 5.4 客服专员（Customer Service）——新建
- [x] 5.4.1 创建客服 Agent：System Prompt + Skill 绑定（inquiry_handling, after_sales_processing, review_management, sentiment_escalation, knowledge_base_maintenance, batch_customer_operation）
- [x] 5.4.2 创建 MCP 工具：customer_query_response, after_sales_handling, review_management, order_query, sentiment_analysis, auto_reply_template_manager, knowledge_base_maintainer
- [x] 5.4.3 实现三级发送策略：按置信度分级（静默发送/批量确认/逐条审核）
- [x] 5.4.4 实现情绪升级检测和人工接管通知
- [x] 5.4.5 注册到 AgentRuntime 并验证 RAG 注入效果

### 5.5 仓储物流（Warehouse Logistics）——新建
- [x] 5.5.1 创建仓储物流 Agent：System Prompt + Skill 绑定（inventory_monitoring, order_fulfillment, logistics_tracking, exception_handling, warehouse_optimization, erp_sync）
- [x] 5.5.2 实现 LogisticsEngine：确定性执行引擎（库存查询/发货调度/物流跟踪/异常检测）
- [x] 5.5.3 创建 MCP 工具：inventory_check, shipment_tracking, logistics_alert, order_fulfillment, warehouse_allocator, delivery_estimate, erp_sync_bridge, return_logistics_handler
- [x] 5.5.4 实现 ERP/WMS API 对接适配器（快递鸟/菜鸟物流 API）
- [x] 5.5.5 注册到 AgentRuntime 并验证 LogisticsEngine 执行准确性

### 5.6 视觉设计（Visual Designer）——新建
- [x] 5.6.1 创建视觉设计 Agent：System Prompt + Skill 绑定（main_image_design, detail_page_design, cover_design, brand_template, batch_generation, aigc_optimization）
- [x] 5.6.2 实现多阶段图像生成流水线：主体生成→背景生成→装饰→文字叠加（确定性渲染）→合规检测→多尺寸导出
- [x] 5.6.3 创建 MCP 工具：design_suggestion, image_generation, style_reference_search, text_overlay, compliance_check, multi_format_export, brand_template_manager, image_optimizer
- [x] 5.6.4 集成 Stable Diffusion / DALL-E API 作为图像生成后端
- [x] 5.6.5 实现多模态 RAG 风格参考检索（Milvus + CLIP）
- [x] 5.6.6 注册到 AgentRuntime 并验证生成流水线完整性

### 5.7 供应链选品师（Product Selector）——新建
- [x] 5.7.1 创建选品师 Agent：System Prompt + Skill 绑定（market_opportunity_discovery, product_evaluation, supplier_assessment, profit_analysis, seasonal_planning, category_expansion）
- [x] 5.7.2 创建 MCP 工具：market_research, product_data_collector, product_scorer, profit_margin_calculator, supplier_evaluator, trend_prediction, seasonal_opportunity_finder, category_expansion_planner
- [x] 5.7.3 实现多维度商品评分引擎（市场容量 25% + 竞争强度 20% + 利润空间 25% + 供应链难度 15% + 季节匹配 15%）
- [x] 5.7.4 实现利润全成本链测算（采购→物流→平台费用→售价→净利）
- [x] 5.7.5 注册到 AgentRuntime 并验证选品→多 Agent 联动流程

### 5.8 智能投流专员（Smart Ad Delivery）——新建
- [x] 5.8.1 创建投流 Agent：System Prompt + Skill 绑定（delivery_strategy, creative_optimization, bid_management, audience_analysis, budget_control, ab_test）
- [x] 5.8.2 创建 MCP 工具：campaign_create, bid_optimizer, audience_targeting, creative_test_runner, budget_allocator, roi_predictor, real_time_monitor, delivery_anomaly_detector
- [x] 5.8.3 实现自动止损规则引擎（CPA 超标降预算、ROI 过低暂停、CTR 低替换素材）
- [x] 5.8.4 实现投放平台 API 对接（千川/巨量引擎/万相台 Adapter）
- [x] 5.8.5 实现 A/B 测试引擎（变量设计→流量分配→显著性检验→结论输出）
- [x] 5.8.6 注册到 AgentRuntime 并验证投放→监控→止损全流程

## 6. 阶段五：Agent 间协同（深度版）

- [x] 6.1 实现 Task 队列消费循环（基于 Redis Streams），Agent 轮询拉取指向自己的 pending Task
- [x] 6.2 实现 CompanyContextBus 自动写入：Agent 任务完成后自动摘要写入 Layer 3
- [x] 6.3 实现协作链配置引擎：可配置的多 Agent 联动规则（选品确认→品牌商务+内容运营+投流等）
- [x] 6.4 实现三级审核流程引擎：review_level 分配规则 + pending_review 状态机 + 审批/修改/拒绝 API
- [x] 6.5 实现审核超时升级：强制审核 4h 未处理自动告警升级
- [x] 6.6 实现内容运营 PlatformContextRouter：多平台沙箱创建/切换/隔离
- [x] 6.7 实现客服三级发送策略引擎：置信度评分 + 分类路由 + 安全门控
- [x] 6.8 实现 MCP 工具三级权限控制：只读/写入/外部操控 + 授权流程 + 操作日志
- [x] 6.9 接入 WebSocket 推送：任务状态变更、告警、协作通知实时推送到 Dashboard

## 7. 阶段六：AI 自动进化

- [x] 7.1 实现三层记忆系统：工作记忆（AgentState）、短期记忆（PostgreSQL+Redis）、长期记忆（Milvus）(`services/evolution.py` WorkingMemory/ShortTermMemory/LongTermMemory)
- [x] 7.2 实现记忆自动写入：Agent 任务完成后自动摘要写入短期记忆 (`services/evolution.py` MemoryAutoWriter)
- [x] 7.3 实现睡眠巩固引擎：定时/阈值触发→摘要压缩→去重→模式提取→写入长期记忆 (`services/evolution.py` SleepConsolidationEngine)
- [x] 7.4 实现 EvolutionLog 记录：配置变更/记忆巩固/Skill 更新/模型切换全量日志 (`services/evolution.py` EvolutionLogger)
- [x] 7.5 实现反馈驱动进化：审核决策（批准/修改/拒绝）记录→提取偏好→注入上下文 (`services/evolution.py` FeedbackDrivenEvolution)
- [x] 7.6 实现 Skill 自动优化建议：分析历史任务数据→生成优化建议→推送审核 (`services/evolution.py` SkillOptimizationEngine)
- [x] 7.7 实现 LoRA 微调流程框架：数据准备→训练→A/B 测试→部署切换（可选功能，需企业确认）(`services/evolution.py` LoRAFineTuneFramework)

## 8. 阶段七：平台 API 对接

- [x] 8.1 实现 PlatformAdapter 抽象基类 (search_creators/get_campaign_report/get_shop_data/get_platform_info/is_available) (`platforms/base.py`)
- [x] 8.2 实现 DouyinStarAdapter：抖音星图达人搜索/活动数据 (`platforms/douyin_star.py`)
- [x] 8.3 实现 DouyinLuopanAdapter：抖音罗盘经营分析/直播分析/人群洞察/竞争分析 (`platforms/douyin_luopan.py`)
- [x] 8.4 实现 ChanmamaAdapter：蝉妈妈竞品数据/达人排行/商品趋势 (`platforms/chanmama.py`)
- [x] 8.5 实现 TaobaoOpenAdapter：淘宝开放平台 API 对接
- [x] 8.6 实现 ShengyiCanshuAdapter：生意参谋 API 对接 (`platforms/shengyi_canshu.py`)
- [x] 8.7 实现 PinduoduoOpenAdapter：拼多多开放平台 API 对接 (`platforms/pinduoduo.py`)
- [x] 8.8 实现投流平台 Adapter：千川/巨量引擎/万相台 API 对接 (`platforms/ad_platforms.py`)
- [x] 8.9 实现 API 降级策略：API 不可用时自动降级 Mock 数据 (`platforms/degradation.py`)
- [x] 8.10 实现企业平台凭证管理：Company 表加密存储多平台 API Key (`platforms/credentials.py`)

## 9. 阶段八：前端应用

- [x] 9.1 重写 App.jsx：React Router 路由配置 + AuthContext 状态管理 (`src/lib/AuthContext.jsx`)
- [x] 9.2 修复 Login.jsx：对接后端 `/api/v1/auth/token` + Refresh Token 自动续期 (`src/components/login-form.jsx`)
- [x] 9.3 重写 Dashboard.jsx：对接后端真实数据 API，统计卡片/Agent状态/告警面板/MiniBarChart (`src/pages/Dashboard.jsx`)
- [x] 9.4 重写 AgentChat.jsx：SSE 流式对话界面，工具调用可视化，审核状态标识 (`src/pages/AgentChat.jsx`)
- [x] 9.5 创建 TaskList.jsx：任务管理页面，支持按状态筛选+搜索+详情弹窗 (`src/pages/TaskList.jsx`)
- [x] 9.6 创建 ReviewWorkflow.jsx：审核工作流页面，强制/推荐审核分组，批量审批，超时告警升级 (`src/pages/ReviewWorkflow.jsx`)
- [x] 9.7 创建 SettingsPage.jsx：4 tab (平台凭证/LLM模型/自定义Agent/成员管理) (`src/pages/SettingsPage.jsx`)
- [x] 9.8 创建 AgentCustomize.jsx：8 类 Agent 卡片管理+创建自定义 Agent (`src/pages/AgentCustomize.jsx`)
- [x] 9.9 创建 404/500 错误页面，Token 过期自动跳转登录 (`src/pages/Error404.jsx`, `Error500.jsx`)
- [x] 9.10 PWA 移动端适配：响应式布局+Drawer导航+manifest.json+Service Worker+推送通知+离线缓存 (`public/manifest.json`, `public/sw.js`)

## 10. 阶段九：老板驾驶舱

- [x] 10.1 实现统计卡片 API + 前端：在线 Agent 数、进行中任务数、今日完成任务数、待审核数 (`/api/v1/dashboard/overview` + `Dashboard.jsx`)
- [x] 10.2 实现 Agent 状态面板：8 职位状态、类型标签、最近任务、在线/忙碌/离线 (`/api/v1/dashboard/agents` + UI)
- [x] 10.3 实现审核管理视图：按强制/推荐分组、批准/驳回操作、批量审批、超时告警升级 (`ReviewWorkflow.jsx`)
- [x] 10.4 实现数据看板图表：任务完成趋势、Token 消耗趋势（MiniBarChart 无依赖自绘）
- [x] 10.5 实现告警推送面板：告警实时展示、已读/处理状态管理、Severity 分级
- [x] 10.6 实现公司设置页面：多平台凭证加密、LLM 每 Agent 可配置、自定义 Agent、成员管理 (`SettingsPage.jsx` 4 tab)
- [x] 10.7 PWA 移动端 Dashboard：Drawer 抽屉导航、响应式 breakpoint、触控友好的卡片布局

## 11. 阶段十：平台运营

- [x] 11.1 实现平台管理员后台（admin 路由组）：公司列表管理、用户管理 (`api/admin/admin.py`)
- [x] 11.2 实现订阅管理页面：8 职位订阅计划 + 企业订阅状态管理 (API: `/api/v1/admin/subscriptions`)
- [x] 11.3 实现用量监控页面：各公司/各 Agent Token 消耗排名和总量 (API: `/api/v1/admin/usage`)
- [x] 11.4 完善 PostgreSQL 备份脚本：pg_dump 定时执行 + 7 天保留策略 + 手动触发 (`scripts/backup_db.py` v2)
- [x] 11.5 补充 API 文档（基于 FastAPI 自动生成的 OpenAPI + /api/v1/ 版本化）
- [x] 11.6 编写集成测试骨架：覆盖多公司隔离、8 Agent 协同、三级审核流程、睡眠巩固、反馈驱动进化 (`tests/test_integration_scenarios.py`)

## 12. Harness 工程标准（贯穿全部阶段）

- [x] 12.1 配置 mypy + ruff：pre-commit hook，CI 阻断 (`.pre-commit-config.yaml` + `pyproject.toml`)
- [x] 12.2 配置 eslint + React hooks + react-refresh：lint 脚本 + `.eslintrc.cjs` (前端工程已完善)
- [x] 12.3 配置 GitHub Actions：PR 自动运行 lint + typecheck + test + 安全扫描 (`.github/workflows/backend-ci.yml`)
- [x] 12.4 配置 bandit + npm audit：CI 阻断高危漏洞 (bandit 已集成在 CI + pre-commit)
- [x] 12.5 配置 Docker Compose 一键部署：PostgreSQL + Redis + Milvus + FastAPI + React (`backend/docker-compose.yml` + `frontend/Dockerfile` + `frontend/nginx.conf`)
- [x] 12.6 核心模块测试覆盖率 ≥80% (已补充完整断言、Mock和集成测试实现)
