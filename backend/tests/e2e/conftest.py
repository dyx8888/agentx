import os
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

BACKEND_URL = "http://localhost:8000"
BACKEND_API_URL = f"{BACKEND_URL}/api"
FRONTEND_URL = "http://localhost:5173"
EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

os.environ["TEST_MODE"] = "true"

# playwright 未安装时跳过所有 e2e 测试（避免 fixture 导入失败）
pytest.importorskip("playwright")


def _is_backend_running(url: str) -> bool:
    try:
        resp = httpx.get(f"{url}/health", timeout=2.0)
        return resp.status_code in (200, 503)
    except Exception:
        return False


def _is_frontend_running(url: str) -> bool:
    try:
        resp = httpx.get(url, timeout=2.0)
        return resp.status_code < 500
    except Exception:
        return False


@pytest.fixture(scope="session", autouse=True)
def _require_e2e_environment():
    """如果前端开发服务器（5173）不可达，自动跳过所有 e2e 测试。"""
    if not _is_frontend_running(FRONTEND_URL):
        pytest.skip(
            f"前端开发服务器不可达（{FRONTEND_URL}），跳过 e2e 测试。"
            "请先启动前端开发服务器：cd frontend && npm run dev"
        )


@pytest.fixture(scope="session")
def backend_server():
    if _is_backend_running(BACKEND_URL):
        yield BACKEND_URL
        return

    backend_dir = Path(__file__).parent.parent.parent
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
        cwd=str(backend_dir),
        env={**os.environ, "TEST_MODE": "true"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)
    for _ in range(30):
        if _is_backend_running(BACKEND_URL):
            break
        time.sleep(1)
    else:
        proc.terminate()
        proc.wait()
        pytest.skip("后端服务未能在超时时间内启动，跳过 e2e 测试")

    yield BACKEND_URL

    proc.terminate()
    proc.wait()


@pytest.fixture(scope="session")
def backend_base_url(backend_server: str) -> str:
    return BACKEND_API_URL


@pytest.fixture(scope="session")
def api_client(backend_base_url: str) -> httpx.Client:
    client = httpx.Client(base_url=backend_base_url, timeout=30.0)
    yield client
    client.close()


@pytest.fixture(scope="session")
def test_user(api_client: httpx.Client) -> dict:
    from tests.e2e.factories.user_factory import register_test_user

    user = register_test_user(api_client)
    yield user


@pytest.fixture(scope="session")
def auth_token(api_client: httpx.Client, test_user: dict) -> str:
    from tests.e2e.factories.user_factory import login_test_user

    result = login_test_user(api_client, test_user["username"], test_user["password"])
    return result["access_token"]


@pytest.fixture(scope="session")
def auth_headers(auth_token: str) -> dict:
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        launch_options = {"headless": True}
        if Path(EDGE_PATH).exists():
            launch_options["executable_path"] = EDGE_PATH
        browser = p.chromium.launch(**launch_options)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def authenticated_page(browser):
    context = browser.new_context()
    page = context.new_page()
    page.route(
        "**/api/auth/users/me",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "id": 1,
                    "username": "e2e_user",
                    "company_id": 1,
                    "disabled": False,
                    "email": "e2e@example.com",
                    "company_name": "E2E Company",
                    "brand_name": "E2E Brand",
                    "category": "test",
                    "is_admin": False,
                    "avatar_url": None,
                    "bio": None,
                }
            ),
        ),
    )

    yield page

    context.close()
