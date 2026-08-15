import inspect
import sys
import types
from unittest.mock import MagicMock

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
