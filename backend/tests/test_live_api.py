"""Deterministic tests for live-platform adapters and unavailable states."""

import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import platforms
from app.mcp_servers.kol_search_server import search_kols
from app.platforms.base import PlatformAdapterUnavailable
from app.platforms.douyin_star import DouyinStarAdapter


class TestLiveAPI:
    """Exercise verified success and fail-closed platform contracts without live calls."""

    @classmethod
    def setup_class(cls):
        cls.test_category = "beauty"
        cls.test_count = 3

    def test_1_missing_credentials_are_structured_in_prod(self, monkeypatch):
        monkeypatch.setenv("ENV", "production")
        monkeypatch.delenv("ALLOW_PLATFORM_MOCK_FALLBACK", raising=False)
        monkeypatch.setattr(platforms, "get_platform_adapter", lambda *_args, **_kwargs: None)

        result = json.loads(
            asyncio.run(search_kols(self.test_category, self.test_count))
        )

        assert result["status"] == "error"
        assert "mock fallback is disabled" in result["message"]

    def test_2_verified_adapter_response_is_parsed(self, monkeypatch):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "data": {"creators": [{"id": "creator-1", "nickname": "公开达人"}]}
        }
        monkeypatch.setattr(
            "app.platforms.douyin_star.requests.get", lambda *_args, **_kwargs: response
        )

        adapter = DouyinStarAdapter(api_key="configured", api_secret="configured")
        result = adapter.search_creators(self.test_category, self.test_count)

        assert result == [{"id": "creator-1", "nickname": "公开达人"}]

    def test_3_invalid_credentials_fail_closed(self, monkeypatch):
        class FailedResponse:
            status_code = 401
            text = "Unauthorized"

        monkeypatch.setenv("ENV", "production")
        monkeypatch.delenv("ALLOW_PLATFORM_MOCK_FALLBACK", raising=False)
        monkeypatch.setattr(
            "app.platforms.douyin_star.requests.get",
            lambda *_args, **_kwargs: FailedResponse(),
        )

        adapter = DouyinStarAdapter(api_key="configured", api_secret="configured")
        with pytest.raises(PlatformAdapterUnavailable) as exc_info:
            adapter.search_creators(self.test_category, self.test_count)

        payload = exc_info.value.to_payload()
        assert payload["status"] == "unavailable"
        assert payload["code"] == "mock_fallback_blocked"
        assert payload["requires_config"] is False

    def test_4_network_timeout_fails_closed_without_long_wait(self, monkeypatch):
        monkeypatch.setenv("ENV", "dev")
        monkeypatch.setattr(
            "app.platforms.douyin_star.requests.get",
            MagicMock(side_effect=requests.exceptions.Timeout("timed out")),
        )

        adapter = DouyinStarAdapter(api_key="configured", api_secret="configured")
        adapter.timeout = 0.001
        started = time.monotonic()
        with pytest.raises(PlatformAdapterUnavailable) as exc_info:
            adapter.search_creators(self.test_category, self.test_count)

        assert time.monotonic() - started < 5.0
        assert exc_info.value.to_payload()["code"] == "external_api_unavailable"
