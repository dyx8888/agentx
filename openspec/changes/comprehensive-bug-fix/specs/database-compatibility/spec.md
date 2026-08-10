## ADDED Requirements

### Requirement: 原始 SQL 使用 PostgreSQL 兼容占位符
系统 SHALL 在所有通过 `cursor.execute()` 执行的原始 SQL 语句中使用 `%s` 占位符，与 `psycopg2` 兼容。

#### Scenario: 企业 API Key 查询使用正确占位符
- **WHEN** `_lookup_company_api_key` 执行 SQL 查询
- **THEN** SQL 语句中使用 `%s` 占位符，查询成功执行不报语法错误

#### Scenario: 企业上下文构建使用正确占位符
- **WHEN** `_build_company_context_from_db` 执行 SQL 查询
- **THEN** SQL 语句中使用 `%s` 占位符，查询成功执行

#### Scenario: Token 用量持久化使用正确占位符
- **WHEN** `TokenUsagePersistence.record()` 执行 INSERT 语句
- **THEN** SQL 语句中使用 `%s` 占位符，数据成功写入

#### Scenario: 进化日志持久化使用正确占位符
- **WHEN** `EvolutionLogger._persist_log()` 执行 INSERT 语句
- **THEN** SQL 语句中使用 `%s` 占位符，日志成功写入

### Requirement: 数据库连接在所有路径中正确关闭
系统 SHALL 确保所有通过 `db.get_connection()` 获取的数据库连接在异常路径中也能被正确关闭。

#### Scenario: company_id 类型转换失败时连接被关闭
- **WHEN** `int(company_id)` 抛出 `ValueError`
- **THEN** 数据库连接在 `finally` 块中被关闭，不泄漏连接

#### Scenario: SQL 执行失败时连接被关闭
- **WHEN** SQL 查询因任何原因失败
- **THEN** 数据库连接在 `finally` 块中被关闭