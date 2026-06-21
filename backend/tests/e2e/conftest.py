import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

BACKEND_URL = "http://localhost:8000"

os.environ["TEST_MODE"] = "true"


def _is_backend_running(url: str) -> bool:
    try:
        resp = httpx.get(f"{url}/health", timeout=2.0)
        return resp.status_code in (200, 503)
    except Exception:
        return False


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
        pytest.fail("Backend server did not start within timeout")

    yield BACKEND_URL

    proc.terminate()
    proc.wait()


@pytest.fixture(scope="session")
def backend_base_url(backend_server: str) -> str:
    return backend_server


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
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()


FRONTEND_URL = "http://localhost:5173"


@pytest.fixture(scope="session")
def authenticated_page(browser, test_user: dict, auth_token: str):
    context = browser.new_context()
    page = context.new_page()

    page.goto(FRONTEND_URL)
    page.evaluate(
        """([token, refresh]) => {
            localStorage.setItem('access_token', token);
            localStorage.setItem('refresh_token', refresh || token);
        }""",
        [auth_token, auth_token],
    )

    yield page

    context.close()