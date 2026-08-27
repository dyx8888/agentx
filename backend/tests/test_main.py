import asyncio
import inspect
import sys
import types
from unittest.mock import MagicMock

import pytest
from sqlalchemy.sql.elements import TextClause


def _patch_health_dependencies(monkeypatch, *, milvus_module=None):
    class FakeRedisClient:
        def ping(self):
            return True

        def close(self):
            return None

    fake_redis = types.SimpleNamespace(
        from_url=lambda *args, **kwargs: FakeRedisClient()
    )
    monkeypatch.setitem(sys.modules, "redis", fake_redis)

    if milvus_module is not None:
        monkeypatch.setitem(sys.modules, "pymilvus", milvus_module)

    fake_worker = types.SimpleNamespace(is_running=True)
    fake_worker_module = types.SimpleNamespace(get_task_worker=lambda: fake_worker)
    monkeypatch.setitem(sys.modules, "app.tasks.worker", fake_worker_module)


def test_health_check_is_sync_function():
    import app.main as main

    assert inspect.iscoroutinefunction(main.health_check) is False


def test_health_check_uses_sqlalchemy_text_for_database_probe(monkeypatch):
    import app.database as database
    import app.database.core as database_core
    import app.main as main

    execute = MagicMock()

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement):
            execute(statement)

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    class FakeMilvusClient:
        def list_collections(self):
            return []

        def close(self):
            return None

    _patch_health_dependencies(
        monkeypatch,
        milvus_module=types.SimpleNamespace(MilvusClient=FakeMilvusClient),
    )
    monkeypatch.setattr(database, "db", object())
    monkeypatch.setattr(database_core, "get_engine", lambda: FakeEngine())

    result = main.health_check()

    assert result["checks"]["database"] == "healthy"
    execute.assert_called_once()
    statement = execute.call_args.args[0]
    assert isinstance(statement, TextClause)
    assert str(statement) == "SELECT 1"


def test_health_check_uses_short_lived_milvus_client(monkeypatch):
    import app.database as database
    import app.main as main

    class FakeConnection:
        def close(self):
            return None

    fake_db = types.SimpleNamespace(get_connection=lambda: FakeConnection())
    monkeypatch.setattr(database, "db", fake_db)
    monkeypatch.setenv("MILVUS_HOST", "milvus.local")
    monkeypatch.setenv("MILVUS_PORT", "19530")

    clients = []

    class FakeMilvusClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.list_collections = MagicMock(return_value=[])
            self.close = MagicMock()
            clients.append(self)

    fake_connections = types.SimpleNamespace(connect=MagicMock(), disconnect=MagicMock())
    fake_milvus = types.SimpleNamespace(
        MilvusClient=FakeMilvusClient,
        connections=fake_connections,
    )
    _patch_health_dependencies(monkeypatch, milvus_module=fake_milvus)

    result = main.health_check()

    assert result["checks"]["milvus"] == "healthy"
    assert len(clients) == 1
    assert clients[0].kwargs == {"uri": "http://milvus.local:19530", "timeout": 2}
    clients[0].list_collections.assert_called_once()
    clients[0].close.assert_called_once()
    fake_connections.connect.assert_not_called()
    fake_connections.disconnect.assert_not_called()


def test_health_check_marks_missing_model_config_as_degraded(monkeypatch):
    import app.database as database
    import app.main as main

    class FakeConnection:
        def close(self):
            return None

    class FakeMilvusClient:
        def list_collections(self):
            return []

        def close(self):
            return None

    _patch_health_dependencies(
        monkeypatch,
        milvus_module=types.SimpleNamespace(MilvusClient=FakeMilvusClient),
    )
    monkeypatch.setattr(database, "db", types.SimpleNamespace(get_connection=lambda: FakeConnection()))
    monkeypatch.setattr(main, "_runtime_model_status", {"status": "model_config_required"})

    result = main.health_check()

    assert result["status"] == "degraded"
    assert result["checks"]["model_gateway"] == "model_config_required"


def _set_config_secrets(monkeypatch, *, env, jwt_secret, encryption_key):
    import app.core.config as config

    monkeypatch.setenv("ENV", env)
    monkeypatch.setattr(config, "JWT_SECRET_KEY", jwt_secret)
    monkeypatch.setattr(config, "ENCRYPTION_KEY", encryption_key)
    return config


def _patch_lifespan_dependencies(
    monkeypatch,
    events,
    *,
    runtime_cls=None,
    session_init_error=None,
    session_close_error=None,
):
    import app.database as database
    import app.main as main

    monkeypatch.setattr(database, "init_database", lambda: events.append("database"))
    monkeypatch.setattr(
        main.registry,
        "initialize_from_config",
        lambda: events.append("tools"),
    )
    monkeypatch.setattr(
        main.skill_registry,
        "load_from_config",
        lambda: events.append("skills"),
    )
    monkeypatch.setattr(main, "EVOLUTION_API_ENABLED", False)

    class FakeRuntime:
        async def initialize(self):
            events.append("runtime")

    monkeypatch.setattr(main, "AgentRuntime", runtime_cls or FakeRuntime)

    class FakeSessionStore:
        async def init(self):
            events.append("session_init")
            if session_init_error:
                raise session_init_error

        async def close(self):
            events.append("session_close")
            if session_close_error:
                raise session_close_error

    fake_store = FakeSessionStore()
    monkeypatch.setitem(
        sys.modules,
        "app.services.session_store",
        types.SimpleNamespace(get_session_store=lambda: fake_store),
    )
    return main


async def _enter_lifespan(main):
    app = types.SimpleNamespace(state=types.SimpleNamespace())
    context = main.lifespan(app)
    await context.__aenter__()
    await context.__aexit__(None, None, None)
    return app


def test_lifespan_blocks_prod_default_jwt_before_startup(monkeypatch):
    config = _set_config_secrets(
        monkeypatch,
        env="prod",
        jwt_secret="default",
        encryption_key="safe-encryption-key-for-startup-test",
    )
    events = []
    original_validate = config.validate_secrets_on_startup

    def wrapped_validate():
        events.append("validate")
        return original_validate()

    monkeypatch.setattr(config, "validate_secrets_on_startup", wrapped_validate)
    main = _patch_lifespan_dependencies(monkeypatch, events)

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        asyncio.run(_enter_lifespan(main))

    assert events == ["validate"]


def test_lifespan_blocks_prod_missing_encryption_key_before_startup(monkeypatch):
    config = _set_config_secrets(
        monkeypatch,
        env="prod",
        jwt_secret="safe-jwt-secret-for-startup-test",
        encryption_key=None,
    )
    events = []
    original_validate = config.validate_secrets_on_startup

    def wrapped_validate():
        events.append("validate")
        return original_validate()

    monkeypatch.setattr(config, "validate_secrets_on_startup", wrapped_validate)
    main = _patch_lifespan_dependencies(monkeypatch, events)

    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
        asyncio.run(_enter_lifespan(main))

    assert events == ["validate"]


def test_lifespan_allows_dev_missing_secrets_and_validates_first(monkeypatch):
    config = _set_config_secrets(
        monkeypatch,
        env="dev",
        jwt_secret=None,
        encryption_key=None,
    )
    events = []
    original_validate = config.validate_secrets_on_startup

    def wrapped_validate():
        events.append("validate")
        return original_validate()

    monkeypatch.setattr(config, "validate_secrets_on_startup", wrapped_validate)
    main = _patch_lifespan_dependencies(monkeypatch, events)

    asyncio.run(_enter_lifespan(main))

    assert events[:6] == ["validate", "database", "tools", "skills", "runtime", "session_init"]
    assert "runtime" in events
    assert events[-1] == "session_close"


def test_lifespan_backend_lightweight_smoke_skips_runtime_in_dev(monkeypatch):
    config = _set_config_secrets(
        monkeypatch,
        env="dev",
        jwt_secret=None,
        encryption_key=None,
    )
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AGENTX_BACKEND_LIGHTWEIGHT_SMOKE", "1")
    events = []
    original_validate = config.validate_secrets_on_startup

    def wrapped_validate():
        events.append("validate")
        return original_validate()

    class RuntimeMustNotStart:
        def __init__(self):
            raise AssertionError("AgentRuntime must not be constructed in lightweight smoke")

    monkeypatch.setattr(config, "validate_secrets_on_startup", wrapped_validate)
    main = _patch_lifespan_dependencies(monkeypatch, events, runtime_cls=RuntimeMustNotStart)

    app = asyncio.run(_enter_lifespan(main))

    assert events == ["validate", "database", "tools", "skills", "session_init", "session_close"]
    assert app.state.runtime is None


def test_lifespan_backend_lightweight_smoke_fails_closed_in_prod(monkeypatch):
    config = _set_config_secrets(
        monkeypatch,
        env="prod",
        jwt_secret="safe-jwt-secret-for-startup-test",
        encryption_key="safe-encryption-key-for-startup-test",
    )
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AGENTX_BACKEND_LIGHTWEIGHT_SMOKE", "1")
    events = []
    original_validate = config.validate_secrets_on_startup

    def wrapped_validate():
        events.append("validate")
        return original_validate()

    monkeypatch.setattr(config, "validate_secrets_on_startup", wrapped_validate)
    main = _patch_lifespan_dependencies(monkeypatch, events)

    with pytest.raises(RuntimeError, match="AGENTX_BACKEND_LIGHTWEIGHT_SMOKE"):
        asyncio.run(_enter_lifespan(main))

    assert events == ["validate"]


def test_lifespan_allows_prod_missing_global_llm_key_with_degraded_runtime(monkeypatch):
    from app.services.model_gateway import ModelApiKeyMissingError

    config = _set_config_secrets(
        monkeypatch,
        env="prod",
        jwt_secret="safe-jwt-secret-for-startup-test",
        encryption_key="safe-encryption-key-for-startup-test",
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    events = []
    original_validate = config.validate_secrets_on_startup

    def wrapped_validate():
        events.append("validate")
        return original_validate()

    class RuntimeMissingGlobalLlmKey:
        def __init__(self):
            self.model_status = {"status": "not_initialized"}

        async def initialize(self):
            events.append("runtime")
            try:
                raise ModelApiKeyMissingError(
                    model_key="deepseek",
                    provider="deepseek",
                    env_keys=("DEEPSEEK_API_KEY",),
                )
            except ModelApiKeyMissingError as exc:
                self.model_status = {
                    "status": "model_config_required",
                    "code": exc.code,
                    "model": exc.model_key,
                    "provider": exc.provider,
                    "env_keys": list(exc.env_keys),
                }

    monkeypatch.setattr(config, "validate_secrets_on_startup", wrapped_validate)
    main = _patch_lifespan_dependencies(
        monkeypatch,
        events,
        runtime_cls=RuntimeMissingGlobalLlmKey,
    )
    monkeypatch.setattr(main, "_runtime_model_status", {"status": "not_initialized"})

    app = asyncio.run(_enter_lifespan(main))

    assert events == ["validate", "database", "tools", "skills", "runtime", "session_init", "session_close"]
    assert app.state.runtime.model_status["status"] == "model_config_required"
    assert main._runtime_model_status["status"] == "model_config_required"


def test_lifespan_session_store_init_failure_falls_back_to_memory(monkeypatch):
    config = _set_config_secrets(
        monkeypatch,
        env="dev",
        jwt_secret=None,
        encryption_key=None,
    )
    events = []
    original_validate = config.validate_secrets_on_startup

    def wrapped_validate():
        events.append("validate")
        return original_validate()

    monkeypatch.setattr(config, "validate_secrets_on_startup", wrapped_validate)
    main = _patch_lifespan_dependencies(
        monkeypatch,
        events,
        session_init_error=RuntimeError("redis unavailable"),
    )

    asyncio.run(_enter_lifespan(main))

    assert "session_init" in events
    assert "session_close" in events


def test_lifespan_session_store_close_failure_does_not_crash(monkeypatch):
    config = _set_config_secrets(
        monkeypatch,
        env="dev",
        jwt_secret=None,
        encryption_key=None,
    )
    events = []
    original_validate = config.validate_secrets_on_startup

    def wrapped_validate():
        events.append("validate")
        return original_validate()

    monkeypatch.setattr(config, "validate_secrets_on_startup", wrapped_validate)
    main = _patch_lifespan_dependencies(
        monkeypatch,
        events,
        session_close_error=RuntimeError("close failed"),
    )

    asyncio.run(_enter_lifespan(main))

    assert "session_init" in events
    assert "session_close" in events


def test_http_exception_handler_logs_4xx_without_traceback(monkeypatch):
    import app.main as main
    from fastapi import HTTPException

    logged = []

    def fail_log_error(*_args, **_kwargs):
        raise AssertionError("4xx HTTPException should not use traceback logging")

    monkeypatch.setattr(main, "log_error", fail_log_error)
    monkeypatch.setattr(main.logger, "info", lambda event, **kwargs: logged.append((event, kwargs)))

    request = types.SimpleNamespace(method="GET", url="http://testserver/api/auth/users/me")
    response = asyncio.run(
        main.http_exception_handler(
            request,
            HTTPException(status_code=401, detail="Could not validate credentials"),
        )
    )

    assert response.status_code == 401
    assert logged == [
        (
            "http_exception",
            {
                "request_method": "GET",
                "request_url": "http://testserver/api/auth/users/me",
                "status_code": 401,
                "detail": "Could not validate credentials",
            },
        )
    ]


def test_general_exception_handler_still_uses_traceback_logging(monkeypatch):
    import app.main as main

    logged = []
    monkeypatch.setattr(main, "log_error", lambda exc, context: logged.append((exc, context)))

    request = types.SimpleNamespace(method="GET", url="http://testserver/broken")
    error = RuntimeError("boom")
    response = asyncio.run(main.general_exception_handler(request, error))

    assert response.status_code == 500
    assert logged == [
        (
            error,
            {
                "request_method": "GET",
                "request_url": "http://testserver/broken",
                "exception_type": "RuntimeError",
            },
        )
    ]
