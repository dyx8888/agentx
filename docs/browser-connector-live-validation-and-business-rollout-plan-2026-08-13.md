# AgentX 浏览器连接器线上验收与业务接入实施计划 - 2026-08-13

本文档用于安排浏览器连接器从“隔离分支本地实现”推进到“可交给真实用户试用”的剩余工作。核心前提不变：连接器是只读数据采集通道，用来解决无法直接获得多平台官方 API 的问题，不做平台写操作。

## 当前边界

- 隔离分支：`codex/browser-connector-mvp`
- 隔离目录：`C:\Users\win\.codex\visualizations\2026\08\12\019ff3ae-c842-7322-9b56-8a515f416e17\agentx-browser-connector-mvp`
- 禁止直接修改原始脏工作树：`C:\kaifawenjian\agentdianshang`
- 禁止使用 `git add .`
- 每次提交前必须输出：
  - `git status -sb`
  - `git diff --name-status`
  - `git diff --cached --name-status`

## 已有实现基础

| 模块 | 当前状态 | 证据文件 |
| --- | --- | --- |
| Chrome MV3 插件 | 已实现本地 MVP | `browser-extension/agentx-connector/` |
| 白名单 API 捕获 | 已实现 | `browser-extension/agentx-connector/src/injected.js` |
| 浏览器端去敏 | 已实现 | `browser-extension/agentx-connector/src/injected.js`、`src/background.js` |
| 后端 ingest | 已实现 | `backend/app/api/browser_connector.py` |
| CORS/Auth Cookie 测试 | 已实现本地测试 | `tests/api/test_browser_connector_cors_auth.py` |
| sanitized event 落库 | 已实现 | `backend/app/services/browser_connector_capture.py`、`backend/app/database/models.py` |
| 归一化 | 已实现通用规则 | `backend/app/services/browser_connector_normalizer.py` |
| 达人库/知识库/投放分析适配 | 已实现后端入口 | `backend/app/services/browser_connector_business.py` |
| Settings 状态、来源摘要与选择导入 | 已实现 | `frontend/src/pages/SettingsPage.jsx` |
| 上线前发布闸门 | 已实现本地 gate 与状态端点 | `backend/app/core/feature_flags.py`、`backend/config/feature_flags.yaml`、`GET /api/browser-connector/status` |
| staging 验收探针 | 已实现本地脚本 | `tests/performance/browser_connector_staging_probe.py` |
| 部署 manifest 生成器 | 已实现本地脚本 | `browser-extension/agentx-connector/tools/build_deployment_manifest.py` |
| DB 落库审计 | 已实现本地脚本 | `tests/performance/browser_connector_db_audit.py` |
| 验收证据命令编排 | 已实现本地脚本 | `tests/performance/browser_connector_evidence_bundle.py` |
| 试点 readiness 汇总闸门 | 已实现本地脚本 | `tests/performance/browser_connector_pilot_readiness_audit.py` |

当前不能直接宣称“可公开给真实用户使用”，因为仍缺少真实线上域名、真实 Chrome 插件安装、真实平台样本、真实登录 Cookie、生产 CORS、数据库落库链路的端到端验收。

## 用户工作流定位

1. 用户登录 AgentX。
2. 用户安装并启用 AgentX 浏览器连接器插件。
3. 用户打开并登录电商/达人/投放平台网页。
4. 用户正常浏览平台页面，不需要手动导出数据。
5. 插件只读 hook `fetch` / `XMLHttpRequest`，仅处理白名单 API 响应。
6. 插件在浏览器端剔除敏感字段，不采集 cookie、Authorization、密码、验证码、支付信息和 request body。
7. 插件通过 AgentX 登录态把 sanitized payload 发送到 `POST /api/browser-connector/ingest`。
8. 后端再次校验去敏边界，并把 `company_id` / `user_id` 绑定到当前登录用户。
9. 后端保存 sanitized event，归一化为：
   - `creator_profile`：达人库候选记录。
   - `knowledge_observation`：知识库候选片段。
   - `campaign_metrics`：投放/经营分析快照。
   - `unmapped_capture`：暂未识别但已安全保存的采集结果。
10. Settings 展示连接器来源摘要、最近记录和只读投放快照，并要求用户选择记录、显式确认后才导入达人库或知识库。
11. 后端连接器端点默认关闭，只对 feature flag 或试点租户/用户白名单开放；Settings 先读取后端试点状态，再决定是否加载记录。

## 实施批次

### 批次 A：真实浏览器端到端验收

目标：证明真实 Chrome 环境中插件、AgentX 登录态、白名单捕获、去敏、发送、后端 ingest 可以连通。

预计改动文件：

- `browser-extension/agentx-connector/README.md`
- `frontend/e2e/browser-connector-extension.spec.js`
- `playwright.browser-connector.config.js`
- `docs/browser-connector-live-validation-and-business-rollout-plan-2026-08-13.md`

执行项：

1. 固定真实浏览器验收脚本：使用 Chromium 持久上下文加载 MV3 插件。
2. 验证白名单 API 被捕获，非白名单 API 不被捕获。
3. 验证 fetch 和 XMLHttpRequest 都被 hook。
4. 验证敏感字段在浏览器端不会进入发送 payload。
5. 验证后台请求使用 `credentials: include`，但 payload 本身不包含凭证。
6. 输出一次可复跑的验收命令和结果路径。

验收标准：

- 插件可以真实加载。
- 后端收到 capture 并返回成功响应。
- 测试中故意加入的敏感字段不会出现在 ingest payload 或数据库记录中。
- 不采集 request headers、cookie、Authorization、request body。

建议提交：

```text
test: harden browser connector real browser validation
```

### 批次 B：线上部署 / CORS / Auth Cookie 验收

目标：确认 staging/线上域名部署后，插件仍能使用 AgentX 登录态安全发送数据，且 CORS 不放开到任意来源。

预计改动文件：

- `backend/app/main.py`
- `backend/app/api/auth_router.py`
- `backend/app/api/browser_connector.py`
- `backend/.env.production.example`
- `browser-extension/agentx-connector/manifest.deployment.example.json`
- `tests/api/test_browser_connector_cors_auth.py`
- `docs/browser-connector-deployment-runbook-2026-08-13.md`
- `docs/browser-connector-live-validation-and-business-rollout-plan-2026-08-13.md`
- `tests/performance/browser_connector_staging_probe.py`
- `tests/performance/test_browser_connector_staging_probe.py`
- `browser-extension/agentx-connector/tools/build_deployment_manifest.py`
- `tests/performance/test_browser_connector_manifest_builder.py`

执行项：

1. 明确 staging 和 production 的允许 origin。
2. 验证 httpOnly `access_token` Cookie 在 HTTPS 下可被后端认证依赖识别。
3. 验证未登录请求被拒绝。
4. 验证任意 origin 不被 CORS 反射。
5. 验证 extension background fetch 依赖 host permissions，不要求把 CORS 放成 wildcard。
6. 配置 `COOKIE_SAMESITE=none` + `COOKIE_SECURE=true` 以支持 extension background fetch 的登录态传输。
7. 记录 staging 验收环境变量和回滚步骤。
8. 用 secret-safe staging probe 复核 CORS 正负例、未登录拒绝和打包 manifest 权限。
9. 用 manifest builder 生成一次性打包 manifest，避免把私有 staging 域名写回源码。

验收标准：

- `POST /api/browser-connector/ingest` 必须登录。
- `tenant_id` / `company_id` / `user_id` 只能来自后端当前用户，客户端传入身份字段被忽略。
- credentialed CORS 不使用 wildcard production origin。
- `COOKIE_SAMESITE=none` 不能在非 Secure cookie 下启用。
- Staging 域名通过真实浏览器插件发送链路。
- Staging probe 生成 JSON 报告，且不包含 cookie/token/password 等 secret 值。

建议提交：

```text
docs: add browser connector deployment validation runbook
```

### 批次 C：真实平台样本落库与归一化扩展

目标：把真实平台响应样本补成 fixture，扩展规则，使系统能够稳定产出达人、知识、投放快照三类业务记录。

预计改动文件：

- `tests/performance/browser_connector_db_audit.py`
- `tests/performance/test_browser_connector_db_audit.py`
- `backend/app/services/browser_connector_rules.py`
- `backend/app/services/browser_connector_normalizer.py`
- `backend/app/services/browser_connector_schemas.py`
- `tests/api/test_browser_connector_normalization.py`
- `tests/fixtures/browser_connector/*.json`
- `docs/browser-connector-normalization-map-2026-08-13.md`

执行项：

1. 已建立第一批脱敏平台形状 fixture：达人、投放、知识、未映射。
2. 已按平台/记录类型拆出 `browser_connector_rules.py` 规则目录，不让业务模块直接依赖平台原始 JSON。
3. 已为规则目录和 fixture 补单元测试。
4. 未识别样本保留为 `unmapped_capture`，不丢数据。
5. 仍需从 staging 插件链路采集 2-3 类真实平台只读响应样本，人工脱敏审查后替换/补充 fixture。
6. 输出规则覆盖率清单：哪些平台/页面/字段已经支持，哪些仍待映射。
7. 用 `browser_connector_db_audit.py` 对 staging DB 做只读证据审计，确认采集事件已按租户落库、URL 只存 hash、payload 没有敏感字段、归一化能产生可审计 record kind。

验收标准：

- 每个脱敏平台形状样本都有测试 fixture。
- 真实 staging 样本回填前，不把 fixture 覆盖误称为真实平台验收完成。
- 归一化失败不影响 ingest。
- 不保存原始敏感 URL query。
- 数据按 company_id 隔离。
- DB 审计报告不输出数据库 URL、cookie、token、password 或平台原始 payload 值。

建议提交：

```text
test: add browser connector database audit
```

### 批次 D：达人库 / 知识库 / 投放分析用户验收

目标：证明连接器采集的数据能进入用户工作流，但仍然保持人工确认和只读边界。

预计改动文件：

- `frontend/src/pages/SettingsPage.jsx`
- `frontend/src/api/browserConnector.js`
- `frontend/src/__tests__/SettingsPage.test.jsx`
- `tests/api/test_browser_connector_business_integration.py`
- `docs/browser-connector-live-validation-and-business-rollout-plan-2026-08-13.md`

执行项：

1. 已实现：Settings 展示最近 connector 来源记录，不只展示数量。
2. 已实现：用户可选择具体记录后导入达人库或知识库，提交 `event_ids`。
3. 已实现：对 `campaign_metrics` 只展示分析快照，不提供平台执行按钮。
4. 已实现：UI 明确标注“浏览器连接器采集 / 只读来源”。
5. 保持 Chat、KOL、Knowledge 主页面不改，避免和公网 Demo 主线冲突。

验收标准：

- 达人候选可预览，可人工确认导入。
- 知识片段可预览，可人工确认写入。
- 投放快照可读，不触发任何平台操作。
- 前端测试覆盖已连接/未连接、摘要、预览、选择记录、确认动作。

建议提交：

```text
feat: add selective browser connector import review
```

### 批次 E：上线前安全与回归门禁

目标：把连接器变成可控试点功能，而不是默认开放能力。

预计改动文件：

- `backend/app/core/feature_flags.py`
- `backend/app/api/browser_connector.py`
- `backend/config/feature_flags.yaml`
- `frontend/src/api/browserConnector.js`
- `frontend/src/pages/SettingsPage.jsx`
- `frontend/src/__tests__/SettingsPage.test.jsx`
- `tests/api/test_browser_connector.py`
- `tests/api/test_browser_connector_cors_auth.py`
- `tests/api/test_browser_connector_storage.py`
- `tests/api/test_browser_connector_business_integration.py`
- `docs/browser-connector-security-boundaries-2026-08-12.md`
- `docs/browser-connector-live-validation-and-business-rollout-plan-2026-08-13.md`

执行项：

1. 已实现：复用 feature flag manager，新增 `browser_connector` 开关，默认关闭。
2. 已实现：支持 `FEATURE_BROWSER_CONNECTOR=true` 全局开启，以及 `FEATURE_BROWSER_CONNECTOR_TENANT_IDS` / `FEATURE_BROWSER_CONNECTOR_USER_IDS` 试点白名单。
3. 已实现：API 层对未开放租户返回 `403 browser_connector_disabled`，并提供 `GET /api/browser-connector/status` 给前端预判状态。
4. 已实现：敏感字段回归测试覆盖 cookie、token、authorization、password、captcha、payment、card、secret、credential、session。
5. 已实现：只读边界检查覆盖无平台写操作入口、无自动建联、无自动改预算。
6. 已实现：Settings 显示“后端试点：已开启/未开启”，未开启时不加载记录、不允许导入。
7. 已实现：输出上线前 checklist。

验收标准：

- 默认租户不可误用。
- 测试租户可完整跑通。
- 安全边界测试通过。
- 文档明确插件只读、人工确认、不可替代平台授权。

本地验证：

```powershell
python -m pytest tests/api/test_browser_connector.py tests/api/test_browser_connector_cors_auth.py tests/api/test_browser_connector_storage.py tests/api/test_browser_connector_normalization.py tests/api/test_browser_connector_business_integration.py -q
```

结果：`51 passed`。

建议提交：

```text
feat: gate browser connector rollout with safety checks
```

## 必跑验证命令

在每个实现批次提交前，至少运行与改动匹配的命令：

```powershell
python -m pytest tests/api/test_browser_connector.py tests/api/test_browser_connector_cors_auth.py tests/api/test_browser_connector_storage.py tests/api/test_browser_connector_normalization.py tests/api/test_browser_connector_business_integration.py -q
```

```powershell
python -m pytest tests/performance/test_browser_connector_db_audit.py -q
```

```powershell
python -m pytest tests/performance/test_browser_connector_live_evidence_template.py tests/performance/test_browser_connector_pilot_readiness_audit.py -q
```

```powershell
cd frontend
npm.cmd test -- SettingsPage.test.jsx
npm.cmd exec -- playwright test --config=playwright.browser-connector.config.js
npm.cmd run build
```

如 `npm.cmd run build` 在当前沙箱中遇到 Vite/esbuild 文件访问限制，可在明确记录原因后用提升权限重跑；不能把未验证构建当作通过。

## 线上验收记录模板

每次 staging 验收必须记录：

- 验收时间 generated_at：
- AgentX 前端域名：
- AgentX 后端域名：
- 插件版本/commit：
- 浏览器版本：
- 登录用户：
- 租户/company_id：
- 测试平台页面：
- 命中的白名单规则：
- ingest 响应：
- 数据库事件 id：
- 归一化记录类型：
- DB 审计报告路径：
- Pilot readiness audit 路径：
- 是否出现敏感字段：
- 是否触发平台写操作：
- 回归命令结果：

## 可交付给用户试用的最低门槛

只有同时满足以下条件，才可以说“可以给小范围真实用户试用”：

1. 隔离分支本地测试全部通过。
2. staging 域名完成真实 Chrome 插件链路验收。
3. 至少 1 个真实平台页面样本跑通捕获、去敏、落库、归一化、Settings 展示。
4. 数据库抽查或 DB audit 报告确认未保存 cookie、Authorization、token、密码、验证码、支付信息，且 API URL 只存 hash。
5. 业务接入只通过人工确认导入，不自动执行平台写操作。
6. feature flag 或租户白名单限制已生效。
7. 公网 Demo 主线没有被本功能污染。
8. staging probe、DB audit、manual live evidence 都是 72 小时内生成的当前证据。
9. `browser_connector_pilot_readiness_audit.py --require-pilot-ready` 返回成功。

## 暂不做

- 不做平台自动点击、自动私信、自动改预算、自动暂停广告、自动改商品。
- 不把连接器采集作为绕过平台授权的写操作通道。
- 不把未归一化的原始平台 JSON 直接塞进 Chat、KOL、Knowledge 主业务流。
- 不在公网 Demo 主线直接开发或提交连接器实验代码。
