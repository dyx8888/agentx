## ADDED Requirements

### Requirement: Token 用量 company_id 正确获取
系统 SHALL 在记录 Token 用量时，使用正确的机制获取当前请求的 company_id，而非从 `_quotas` 字典中用错误 key 类型取值。

#### Scenario: 非公司1的 Token 用量正确归属
- **WHEN** company_id=2 的用户发起 LLM 调用
- **THEN** Token 用量记录归属到 company_id=2，而非错误地归属到 1

### Requirement: 反馈数据表结构与 INSERT 语句一致
系统 SHALL 确保 `feedback.py` 中 `store_feedback()` 的 INSERT 语句列名与 `FeedbackDB.__init__()` 中 CREATE TABLE 的列名完全一致。

#### Scenario: 反馈数据成功写入
- **WHEN** 用户提交反馈
- **THEN** 数据成功写入 feedback 表，不报列不存在的错误

### Requirement: 进化日志表名与 ORM 模型一致
系统 SHALL 确保 `EvolutionLogger._persist_log()` 中写入的表名与 `models.py` 中 SQLAlchemy 模型定义的 `__tablename__` 一致。

#### Scenario: 进化日志成功持久化
- **WHEN** 进化引擎产生日志
- **THEN** 日志成功写入数据库表，不报表不存在的错误

### Requirement: 数据库模块消除 Pydantic/SQLAlchemy 模型命名冲突
系统 SHALL 确保 `database/__init__.py` 中不定义与 SQLAlchemy ORM 模型同名的 Pydantic 模型类。

#### Scenario: 导入 User 类型明确
- **WHEN** 其他模块执行 `from app.database import User`
- **THEN** 导入的是 SQLAlchemy ORM 模型，而非 Pydantic 模型