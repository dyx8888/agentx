import json
from types import SimpleNamespace

import pytest

import app.database as database_module
import app.services.model_gateway as model_gateway


class FakeChatOpenAI:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = dict(kwargs)
        FakeChatOpenAI.instances.append(self.kwargs)


class FakeDB:
    def __init__(self, company):
        self.company = company
        self.company_ids = []

    def get_company(self, company_id):
        self.company_ids.append(company_id)
        return self.company


def _company(llm_config):
    return SimpleNamespace(id=239, llm_api_key=json.dumps(llm_config))


def _write_config(tmp_path):
    config_path = tmp_path / "model_config.yaml"
    config_path.write_text(
        """
default_model: deepseek
models:
  deepseek:
    provider: deepseek
    base_url: https://api.deepseek.com/v1
    model_name: deepseek-chat
    temperature: 0.7
    max_tokens: 2048
    fallback_models:
      - deepseek_volc
  deepseek_volc:
    provider: volcano
    base_url: https://ark.cn-beijing.volces.com/api/v3
    model_name: deepseek-chat
    temperature: 0.7
    max_tokens: 2048
""".strip(),
        encoding="utf-8",
    )
    return config_path


@pytest.fixture
def gateway_factory(monkeypatch, tmp_path):
    FakeChatOpenAI.instances = []
    monkeypatch.setattr(model_gateway, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(model_gateway, "ChatOpenAI", FakeChatOpenAI)

    def build(llm_config):
        fake_db = FakeDB(_company(llm_config))
        monkeypatch.setattr(database_module, "db", fake_db)
        gateway = model_gateway.ModelGateway(config_path=str(_write_config(tmp_path)))

        async def fake_audit_log(*args, **kwargs):
            return None

        gateway.audit_logger = SimpleNamespace(log=fake_audit_log)
        return gateway, fake_db

    return build


@pytest.mark.asyncio
async def test_company_provider_config_drives_get_llm_for_task_without_network(
    monkeypatch, gateway_factory
):
    gateway, fake_db = gateway_factory(
        {
            "custom_proxy": {
                "providerType": "openai_compatible",
                "baseUrl": "https://proxy.example.com/v1",
                "modelName": "company-chat-model",
                "apiKey": "sk-company-secret",
                "enabled": True,
                "preferredTasks": ["chat"],
            }
        }
    )
    monkeypatch.setattr(
        gateway,
        "_get_env_api_key",
        lambda provider: (_ for _ in ()).throw(AssertionError("env key should not be read")),
    )

    llm = await gateway.get_llm_for_task("chat", company_id=239)

    assert llm.model_key == "custom_proxy"
    assert llm.fallback_models == []
    assert len(llm.models) == 1
    assert FakeChatOpenAI.instances == [
        {
            "model": "company-chat-model",
            "api_key": "sk-company-secret",
            "temperature": 0.7,
            "base_url": "https://proxy.example.com/v1",
        }
    ]
    assert fake_db.company_ids


def test_get_llm_can_create_direct_company_provider(monkeypatch, gateway_factory):
    gateway, _fake_db = gateway_factory(
        {
            "custom_proxy": {
                "providerType": "openai_compatible",
                "baseUrl": "https://proxy.example.com/v1",
                "modelName": "company-chat-model",
                "apiKey": "sk-company-secret",
                "enabled": True,
            }
        }
    )
    monkeypatch.setattr(
        gateway,
        "_get_env_api_key",
        lambda provider: (_ for _ in ()).throw(AssertionError("env key should not be read")),
    )

    llm = gateway.get_llm("custom_proxy", company_id=239)

    assert llm.model_key == "custom_proxy"
    assert llm.fallback_models == []
    assert len(FakeChatOpenAI.instances) == 1
    assert FakeChatOpenAI.instances[0]["model"] == "company-chat-model"
    assert FakeChatOpenAI.instances[0]["api_key"] == "sk-company-secret"
    assert FakeChatOpenAI.instances[0]["base_url"] == "https://proxy.example.com/v1"


def test_static_provider_uses_company_key_from_llm_api_key(monkeypatch, gateway_factory):
    gateway, _fake_db = gateway_factory({"deepseek": {"apiKey": "sk-company-deepseek"}})
    monkeypatch.setattr(
        gateway,
        "_get_env_api_key",
        lambda provider: (_ for _ in ()).throw(AssertionError("env key should not be read")),
    )

    llm = gateway.get_llm("deepseek", company_id=239)

    assert llm.model_key == "deepseek"
    assert FakeChatOpenAI.instances[0]["model"] == "deepseek-chat"
    assert FakeChatOpenAI.instances[0]["api_key"] == "sk-company-deepseek"
    assert FakeChatOpenAI.instances[0]["base_url"] == "https://api.deepseek.com/v1"

def test_static_provider_disabled_config_fails_closed(monkeypatch, gateway_factory):
    gateway, _fake_db = gateway_factory(
        {"deepseek": {"apiKey": "sk-company-deepseek", "enabled": False}}
    )
    monkeypatch.setattr(
        gateway,
        "_get_env_api_key",
        lambda provider: (_ for _ in ()).throw(AssertionError("env key should not be read")),
    )

    with pytest.raises(model_gateway.ModelProviderConfigError) as exc_info:
        gateway.get_llm("deepseek", company_id=239)

    assert "provider is disabled" in str(exc_info.value)
    assert FakeChatOpenAI.instances == []

@pytest.mark.parametrize(
    "provider_patch, expected_reason",
    [
        ({"enabled": False}, "provider is disabled"),
        ({"apiKey": ""}, "apiKey is required"),
        ({"baseUrl": ""}, "baseUrl is required"),
        ({"modelName": ""}, "modelName is required"),
        ({"baseUrl": "http://proxy.example.com/v1"}, "baseUrl must be an https URL"),
        ({"baseUrl": "https://127.0.0.1/v1"}, "baseUrl must not target private"),
    ],
)
def test_company_provider_invalid_config_fails_closed(
    monkeypatch, gateway_factory, provider_patch, expected_reason
):
    provider = {
        "providerType": "openai_compatible",
        "baseUrl": "https://proxy.example.com/v1",
        "modelName": "company-chat-model",
        "apiKey": "sk-company-secret",
        "enabled": True,
    }
    provider.update(provider_patch)
    gateway, _fake_db = gateway_factory({"custom_proxy": provider})
    monkeypatch.setattr(
        gateway,
        "_get_env_api_key",
        lambda provider: (_ for _ in ()).throw(AssertionError("env key should not be read")),
    )

    with pytest.raises(model_gateway.ModelProviderConfigError) as exc_info:
        gateway.get_llm("custom_proxy", company_id=239)

    assert expected_reason in str(exc_info.value)
    assert FakeChatOpenAI.instances == []


@pytest.mark.asyncio
async def test_disabled_task_provider_fails_closed_instead_of_defaulting(
    monkeypatch, gateway_factory
):
    gateway, _fake_db = gateway_factory(
        {
            "custom_proxy": {
                "providerType": "openai_compatible",
                "baseUrl": "https://proxy.example.com/v1",
                "modelName": "company-chat-model",
                "apiKey": "sk-company-secret",
                "enabled": False,
                "preferredTasks": ["chat"],
            }
        }
    )
    monkeypatch.setattr(
        gateway,
        "_get_env_api_key",
        lambda provider: (_ for _ in ()).throw(AssertionError("env key should not be read")),
    )

    with pytest.raises(model_gateway.ModelProviderConfigError):
        await gateway.get_llm_for_task("chat", company_id=239)

    assert FakeChatOpenAI.instances == []