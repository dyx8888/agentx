## ADDED Requirements

### Requirement: ModelGateway 全局单例线程安全
系统 SHALL 确保 `get_global_model_gateway()` 在任何并发场景下只创建一个 `ModelGateway` 实例。

#### Scenario: 并发调用只创建一个实例
- **WHEN** 多个线程同时调用 `get_global_model_gateway()`
- **THEN** 只有一个 `ModelGateway` 实例被创建，所有线程获得同一实例

### Requirement: 消除双重 ModelGateway 单例
系统 SHALL 确保项目中只存在一个 `get_global_model_gateway()` 函数定义，位于 `app.services.model_gateway` 模块中。`app.agent` 模块中的重复定义应被移除，改为引用统一实现。

#### Scenario: agent.py 使用统一的 ModelGateway 实例
- **WHEN** `app.agent` 模块获取 ModelGateway 实例
- **THEN** 调用 `app.services.model_gateway.get_global_model_gateway()` 获取与系统其他部分相同的实例

### Requirement: SessionStore 全局单例线程安全
系统 SHALL 确保 `get_session_store()` 在任何并发场景下只创建一个 `SessionStore` 实例。

#### Scenario: 并发调用只创建一个 SessionStore 实例
- **WHEN** 多个线程同时调用 `get_session_store()`
- **THEN** 只有一个 `SessionStore` 实例被创建