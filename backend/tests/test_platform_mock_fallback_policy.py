import asyncio
import json

from app import platforms
from app.mcp_servers.kol_search_server import search_kols
from app.mcp_servers.mock_policy import mock_fallback_blocked_result, mock_fallback_enabled


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
