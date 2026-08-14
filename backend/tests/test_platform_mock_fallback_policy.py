import asyncio
import json

import pytest

from app import platforms
from app.mcp_servers.kol_search_server import search_kols
from app.mcp_servers.mock_policy import mock_fallback_blocked_result, mock_fallback_enabled
from app.platforms.base import PlatformAdapterUnavailable


def test_platform_mock_fallback_allowed_in_dev(monkeypatch):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.delenv("ALLOW_PLATFORM_MOCK_FALLBACK", raising=False)

    assert mock_fallback_enabled() is True


def test_platform_mock_fallback_blocked_in_prod(monkeypatch):
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.delenv("ALLOW_PLATFORM_MOCK_FALLBACK", raising=False)

    result = json.loads(mock_fallback_blocked_result("KOL search"))

    assert mock_fallback_enabled() is False
    assert result["status"] == "error"
    assert "mock fallback is disabled" in result["message"]


def test_platform_mock_fallback_can_be_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("ALLOW_PLATFORM_MOCK_FALLBACK", "true")

    assert mock_fallback_enabled() is True


def test_kol_search_server_blocks_mock_fallback_in_prod(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("ALLOW_PLATFORM_MOCK_FALLBACK", raising=False)
    monkeypatch.setattr(platforms, "get_platform_adapter", lambda *_args, **_kwargs: None)

    result = json.loads(asyncio.run(search_kols("beauty", count=1)))

    assert result["status"] == "error"
    assert "mock fallback is disabled" in result["message"]


@pytest.mark.parametrize(
    ("adapter_factory", "operation"),
    [
        (
            lambda: __import__(
                "app.platforms.douyin_star", fromlist=["DouyinStarAdapter"]
            ).DouyinStarAdapter(),
            lambda adapter: adapter.search_creators("beauty", 1),
        ),
        (
            lambda: __import__(
                "app.platforms.chanmama", fromlist=["ChanMamaAdapter"]
            ).ChanMamaAdapter(),
            lambda adapter: adapter.search_kols("beauty", limit=1),
        ),
        (
            lambda: __import__(
                "app.platforms.douyin_shop", fromlist=["DouyinShopAdapter"]
            ).DouyinShopAdapter(),
            lambda adapter: adapter.get_product_list(page=1, size=1),
        ),
        (
            lambda: __import__(
                "app.platforms.taobao", fromlist=["TaobaoAdapter"]
            ).TaobaoAdapter(),
            lambda adapter: adapter.get_shop_metrics("2026-08-14"),
        ),
    ],
)
def test_platform_adapters_require_credentials_before_mock_data(
    monkeypatch, adapter_factory, operation
):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.delenv("ALLOW_PLATFORM_MOCK_FALLBACK", raising=False)

    with pytest.raises(PlatformAdapterUnavailable) as exc_info:
        operation(adapter_factory())

    payload = exc_info.value.to_payload()
    assert payload["status"] == "unavailable"
    assert payload["code"] == "requires_config"
    assert payload["requires_config"] is True


def test_douyin_star_api_failure_blocks_mock_creator_results_in_prod(monkeypatch):
    from app.platforms.douyin_star import DouyinStarAdapter

    class FailedResponse:
        status_code = 401
        text = "Unauthorized"

        def json(self):
            return {"code": 401, "message": "Unauthorized"}

    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("ALLOW_PLATFORM_MOCK_FALLBACK", raising=False)
    monkeypatch.setattr(
        "app.platforms.douyin_star.requests.get",
        lambda *_args, **_kwargs: FailedResponse(),
    )

    adapter = DouyinStarAdapter(api_key="key", api_secret="secret")
    with pytest.raises(PlatformAdapterUnavailable) as exc_info:
        adapter.search_creators("beauty", 2)

    payload = exc_info.value.to_payload()
    assert payload["status"] == "unavailable"
    assert payload["code"] == "mock_fallback_blocked"
    assert payload["requires_config"] is False


@pytest.mark.parametrize(
    ("adapter", "operation"),
    [
        (
            __import__("app.platforms.chanmama", fromlist=["ChanMamaAdapter"]).ChanMamaAdapter(
                api_key="key"
            ),
            lambda adapter: adapter.get_shop_data("shop-1"),
        ),
        (
            __import__(
                "app.platforms.douyin_shop", fromlist=["DouyinShopAdapter"]
            ).DouyinShopAdapter(api_key="key", api_secret="secret", shop_id="shop-1"),
            lambda adapter: adapter.get_shop_data("shop-1"),
        ),
        (
            __import__("app.platforms.taobao", fromlist=["TaobaoAdapter"]).TaobaoAdapter(
                app_key="key", app_secret="secret", session_key="session"
            ),
            lambda adapter: adapter.get_shop_data("shop-1"),
        ),
    ],
)
def test_configured_adapters_do_not_return_unimplemented_demo_shop_data_in_prod(
    monkeypatch, adapter, operation
):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("ALLOW_PLATFORM_MOCK_FALLBACK", raising=False)

    with pytest.raises(PlatformAdapterUnavailable) as exc_info:
        operation(adapter)

    payload = exc_info.value.to_payload()
    assert payload["status"] == "unavailable"
    assert payload["code"] == "mock_fallback_blocked"
    assert payload["requires_config"] is False
