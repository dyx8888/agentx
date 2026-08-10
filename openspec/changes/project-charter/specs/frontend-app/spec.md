## ADDED Requirements

### Requirement: 用户认证页面
前端应用 MUST 提供登录页面和注册页面。登录页 SHALL 支持用户名+密码登录，登录成功后跳转到 Dashboard。注册页 SHALL 收集用户名、邮箱、密码、公司信息。

#### Scenario: 用户成功登录
- **WHEN** 用户在登录页输入正确的用户名和密码并提交
- **THEN** 系统返回 JWT Token 并跳转到 Dashboard 页面

#### Scenario: 用户注册新账号
- **WHEN** 新用户填写注册表单（用户名、密码、公司名称、品牌名称、品类、平台）
- **THEN** 系统创建用户账号和对应公司，自动登录并跳转到 Dashboard

### Requirement: Dashboard 工作台
Dashboard MUST 包含：顶部导航栏（公司名称、消息通知、用户菜单）、左侧菜单（工作台、数字员工、任务管理、数据分析、系统设置）、主内容区展示统计卡片和最近任务列表。

#### Scenario: Dashboard 首次加载
- **WHEN** 用户进入 Dashboard
- **THEN** 系统调用后端 API 获取真实数据（非 Mock），展示统计卡片和任务列表

### Requirement: Agent 对话界面
前端应用 MUST 为每个数字员工提供独立的对话界面，支持：聊天消息流（Markdown 渲染）、工具调用过程展示、任务进度展示、审核状态标识。

#### Scenario: 与品牌商务 Agent 对话
- **WHEN** 用户点击"品牌商务"进入对话界面，发送"帮我找美妆品类的达人"
- **THEN** 系统以 SSE 流式返回 Agent 的思考和工具调用过程，最终展示达人列表

#### Scenario: 对话中展示审核状态
- **WHEN** Agent 产出被标记为强制审核
- **THEN** 对话界面展示黄色审核等待标记→用户可直接在对话中批准/修改/拒绝

---

### Requirement: 任务审核工作流

前端 MUST 提供完整的任务审核界面。审核列表 SHALL 按审核级别分组（强制审核 / 推荐审核），支持批准、修改后批准、拒绝操作。

#### Scenario: 审核待确认的达人邀约话术
- **WHEN** 企业主进入审核列表→查看品牌商务生成的邀约话术
- **THEN** 企业主可：(1) 直接批准 → 系统执行发送、(2) 修改后批准 → 以修改后内容执行、(3) 拒绝 → 标注原因返回 Agent 重做

#### Scenario: 批量审核推荐审核项
- **WHEN** 多条内容脚本进入推荐审核列表
- **THEN** 企业主可一键全部通过或逐条查看→24 小时未处理自动标记为已忽略

#### Scenario: 审核超时提醒
- **WHEN** 强制审核项超过 4 小时未处理
- **THEN** 审核列表红色高亮→PWA 推送通知→Dashboard 顶部横幅提醒

---

### Requirement: 响应式布局 + PWA 移动端

前端应用 MUST 支持 PC 端和移动端的响应式布局。PC 端使用侧边栏+内容区布局，移动端使用底部导航+折叠菜单布局。支持 PWA 安装到手机主屏幕和离线缓存。

#### Scenario: 手机端访问 Dashboard
- **WHEN** 用户在手机上打开应用
- **THEN** 系统自动切换为移动端布局，侧边栏折叠，统计卡片纵向排列，底部导航栏

#### Scenario: PWA 安装到手机主屏幕
- **WHEN** 用户在手机上首次访问应用
- **THEN** 浏览器提示「添加到主屏幕」→安装后像原生 App 一样打开→支持推送通知

#### Scenario: PWA 离线访问
- **WHEN** 用户手机断网后打开已缓存的应用
- **THEN** 显示已缓存的数据和界面→网络恢复后自动刷新最新数据

---

### Requirement: 全局错误处理
前端应用 MUST 处理以下错误场景并给出用户友好的提示：网络请求失败、Token 过期（自动跳转登录页）、404 页面不存在、500 服务器错误。

#### Scenario: Token 过期自动跳转
- **WHEN** 用户在 Dashboard 页面停留超过 30 分钟（Token 过期）
- **THEN** 下一次 API 请求失败后，前端自动清除 Token 并跳转到登录页

---

### Requirement: 公司设置页面

前端 MUST 提供完整的公司设置页面，企业主可以在设置中：
- 管理各平台 API 凭证（抖音、淘宝、拼多多、蝉妈妈等）
- 配置自有 LLM API Key（DeepSeek、OpenAI、火山引擎等）
- 为每个 Agent 独立选择 LLM 模型
- 管理职位订阅和到期时间
- 创建和管理自定义 Agent
- 添加/删除公司成员账号

#### Scenario: 配置多个 LLM 提供商 Key
- **WHEN** 企业主在 LLM 设置页面分别填入 DeepSeek 和 OpenAI 的 API Key
- **THEN** 系统加密存储→每个 Agent 的模型配置下拉列表显示可用模型→企业主可为不同 Agent 分配不同模型

#### Scenario: 创建自定义 Agent
- **WHEN** 企业主在 Agent 管理页面点击「创建自定义 Agent」→填写名称、描述、System Prompt、选择工具集和模型
- **THEN** 系统创建 Agent 实例→立即出现在 Agent 列表中→企业主可与其对话
