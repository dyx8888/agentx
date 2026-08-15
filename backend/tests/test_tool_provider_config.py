from pathlib import Path
from urllib.parse import urlparse

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILES = [
    REPO_ROOT / "backend" / "config" / "tool_providers.yaml",
    REPO_ROOT / "backend" / "config" / "tools.yaml",
]
SERVICE_HOSTS = {
    "kol-search",
    "outreach-server",
    "script-server",
    "report-server",
    "logistics-server",
}


def _config_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in CONFIG_FILES)


def _iter_url_templates():
    for path in CONFIG_FILES:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

        for provider in config.get("providers", []):
            if provider.get("type") == "http_endpoint" and provider.get("url"):
                yield provider["url"]

            fallback_url = (provider.get("degradation") or {}).get("fallback_url")
            if fallback_url:
                yield fallback_url

        for tool in config.get("tools", []):
            endpoint = tool.get("endpoint")
            if endpoint:
                yield endpoint


def _template_default(template: str) -> str:
    assert template.startswith("${")
    assert ":-" in template
    return template.split(":-", 1)[1].rstrip("}")


def test_tool_configs_do_not_use_localhost_service_urls():
    assert "http://localhost:810" not in _config_text()


def test_tool_http_urls_use_env_templates_with_service_defaults():
    templates = list(_iter_url_templates())
    assert templates

    for template in templates:
        assert template.startswith("${")
        assert ":-" in template
        parsed = urlparse(_template_default(template))
        assert parsed.scheme == "http"
        assert parsed.hostname in SERVICE_HOSTS
        assert parsed.port in {8101, 8103, 8104, 8105, 8106}
        assert parsed.path.startswith("/tools/")


def test_platform_tools_are_not_reenabled():
    config = yaml.safe_load(
        (REPO_ROOT / "backend" / "config" / "tool_providers.yaml").read_text(
            encoding="utf-8"
        )
    )

    provider_names = {provider.get("name") for provider in config.get("providers", [])}
    assert "platform_tools" not in provider_names

    capability_map = config.get("capability_map", {})
    mapped_providers = {
        provider
        for providers in capability_map.values()
        for provider in providers
    }
    assert "platform_tools" not in mapped_providers


def test_tool_configs_do_not_embed_sensitive_credentials():
    lowered = _config_text().lower()

    forbidden_terms = [
        "authori" + "zation",
        "bear" + "er",
        "coo" + "kie",
        "api" + "_" + "key",
        "api" + "key",
        "sec" + "ret",
        "access" + "_" + "tok" + "en",
        "refresh" + "_" + "tok" + "en",
    ]
    for term in forbidden_terms:
        assert term not in lowered
