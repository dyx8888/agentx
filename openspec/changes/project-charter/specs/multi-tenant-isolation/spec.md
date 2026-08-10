## ADDED Requirements

### Requirement: 数据访问层强制行级隔离
所有对数据库的读写操作 MUST 附带 company_id 过滤条件。DAO 层每个查询方法的第一个参数 SHALL 为 company_id。任何缺少 company_id 过滤的数据库操作 SHALL 在代码审查阶段被拒绝。

#### Scenario: A 公司用户查询 Agent 列表
- **WHEN** A 公司用户请求 `/api/agents/` 接口
- **THEN** 系统仅返回 company_id 等于该用户所在公司的 Agent 记录

#### Scenario: B 公司用户尝试访问 A 公司的任务详情
- **WHEN** B 公司用户请求 `/api/tasks/123` 接口（该任务属于 A 公司）
- **THEN** 系统返回 404 Not Found（不透露任务是否存在）

### Requirement: API 层自动注入 company_id
所有需要多租户隔离的 API 端点 MUST 通过 FastAPI 依赖注入自动获取当前用户的 company_id，不允许从请求参数中手动传入 company_id。

#### Scenario: 用户创建任务
- **WHEN** 用户调用 POST `/api/tasks/` 并传入任务描述
- **THEN** 系统从当前登录用户的 JWT Token 提取 company_id，自动注入到创建的任务记录中

#### Scenario: 恶意用户尝试伪造 company_id
- **WHEN** 用户 POST 请求中包含 `company_id: 999` 参数
- **THEN** 系统忽略请求中的 company_id，使用 JWT Token 中的真实 company_id

### Requirement: 公司间数据和配置完全隔离
每个公司 MUST 只能看到和管理自己的数字员工、任务、平台凭证、LLM Key。公司 A 的 Agent 无法通过 delegate 或 schedule 与公司 B 的 Agent 通信。

#### Scenario: 跨公司 Agent 通信被拦截
- **WHEN** 公司 A 的 Agent 尝试向公司 B 的 Agent 发送任务
- **THEN** 系统拒绝该请求并返回错误信息

### Requirement: 平台管理员可管理所有公司
平台级别的 admin（is_admin=True）MUST 可以查看和管理所有公司的数据和配置，用于运维和客户支持。普通 admin（公司内 admin）只能管理本公司数据。

#### Scenario: 平台管理员查看所有公司
- **WHEN** 平台 admin 访问 `/api/companies/` 接口
- **THEN** 系统返回所有已注册公司的列表

#### Scenario: 公司 admin 查看公司列表
- **WHEN** 公司 admin（非平台 admin）访问同一个接口
- **THEN** 系统仅返回该用户所属公司的信息
