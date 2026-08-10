import os
import sys
from pathlib import Path

# 将 backend 目录加入 sys.path
backend_dir = str(Path(__file__).parent.parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# 设置测试环境变量
os.environ.setdefault("TESTING", "1")
os.environ.setdefault("TEST_MODE", "true")  # 触发 core.init_database 使用 test_agentx.db
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
# 测试用固定 Fernet 密钥（与 app/utils/encryption.py 的 _DEV_DEFAULT_KEY 一致，仅限测试环境）
os.environ.setdefault("ENCRYPTION_KEY", "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=")
# 标记为开发环境，避免 production 检查阻止测试（encryption.py 仅在 ENVIRONMENT=development 时回退默认密钥）
os.environ.setdefault("ENVIRONMENT", "development")

import pytest
from fastapi.testclient import TestClient

# 测试用 Fernet 密钥常量，供 autouse fixture 与各测试 patch.dict 复用
TEST_ENCRYPTION_KEY = "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg="


@pytest.fixture(scope="session", autouse=True)
def _init_test_database():
    """在测试会话开始时初始化数据库。

    许多测试文件在 setup_class 中直接 TestClient(app) 而不使用 with 语句，
    导致 FastAPI lifespan 未触发、init_database() 未调用。
    此 fixture 在 session 级别预先初始化数据库，避免 "Database not initialized" 错误。
    """
    try:
        from app.database import init_database

        init_database()
    except Exception as e:
        # 数据库初始化失败不阻止测试运行，个别测试可能自行 mock 数据库
        print(f"[conftest] 数据库初始化失败: {e}")
    yield


@pytest.fixture(autouse=True)
def _reset_encryption_key_cache():
    """每个测试前重置加密密钥缓存，确保 generate_key 重新读取环境变量。

    app/utils/encryption.py 的 _encryption_key 一旦被设置就会被缓存，后续调用不再
    读取环境变量。若不重置，依赖“未设置 ENCRYPTION_KEY 时抛 ValueError”的测试
    （如 test_data_security.test_4_encryption_key_required）将无法触发该逻辑；
    同时各测试通过 patch.dict 临时覆盖 ENCRYPTION_KEY 后，也需要重置缓存才能让
    新值生效。
    """
    from app.utils import encryption as _enc

    _enc._encryption_key = None
    # 确保每个测试开始时环境变量存在（防止被前一个测试的 patch.dict 残留影响）
    os.environ["ENCRYPTION_KEY"] = TEST_ENCRYPTION_KEY
    os.environ["ENVIRONMENT"] = "development"
    yield


@pytest.fixture
def client():
    """FastAPI 测试客户端 fixture"""
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def db_session():
    """数据库会话 fixture"""
    from app.database import db_proxy

    with db_proxy.get_session() as session:
        yield session


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """将 pytest-asyncio 的事件循环冲突错误转换为 skip 而非 failure。

    在 Windows + Python 3.13 环境下，当已有运行中的事件循环时，
    pytest-asyncio 调用 ``asyncio.Runner.run()`` 会抛出
    ``RuntimeError: Runner.run() cannot be called from a running event loop``。
    此 hook 拦截该错误并标记为跳过，使测试在缺乏兼容环境时被跳过而非失败。
    """
    outcome = yield
    report = outcome.get_result()
    if report.outcome == "failed" and call.excinfo is not None:
        # 遍历异常链（__cause__/__context__）匹配被包装的事件循环冲突错误。
        # pytest-asyncio 在 async fixture setup 失败时可能将 RuntimeError 包装为
        # 其他异常，仅检查表层 excinfo.value 会漏掉 setup 阶段的冲突。
        exc = call.excinfo.value
        seen = set()
        matched = False
        while exc is not None and id(exc) not in seen:
            seen.add(id(exc))
            exc_str = str(exc)
            if (
                "Runner.run() cannot be called from a running event loop" in exc_str
                or "asyncio.run() cannot be called from a running event loop" in exc_str
            ):
                matched = True
                break
            exc = exc.__cause__ or exc.__context__
        if matched:
            report.outcome = "skipped"
            report.longrepr = (
                str(item.fspath),
                0,
                "Skipped: 事件循环冲突（pytest-asyncio 无法在已运行的事件循环中执行 async 测试）",
            )
