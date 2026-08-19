import pytest

import app.services.model_gateway as model_gateway


class FakeChatOpenAI:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = dict(kwargs)
        FakeChatOpenAI.instances.append(self.kwargs)


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
    fallback_models: []
""".strip(),
        encoding="utf-8",
    )
    return config_path


@pytest.fixture
def gateway_factory(monkeypatch, tmp_path):
    FakeChatOpenAI.instances = []
    monkeypatch.setattr(model_gateway, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(model_gateway, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setenv("AGENT_EVAL_BASE_URL", "https://proxy.example.com/v1")
    monkeypatch.setenv("AGENT_EVAL_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_EVAL_MODEL_NAME", "test-model")
    monkeypatch.delenv("AGENTX_SMOKE_MODEL_MAX_RETRIES", raising=False)
    monkeypatch.delenv("AGENTX_SMOKE_DISABLE_MODEL_RETRY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    def build():
        return model_gateway.ModelGateway(config_path=str(_write_config(tmp_path)))

    return build


def test_eval_proxy_smoke_model_max_retries_zero(gateway_factory, monkeypatch):
    monkeypatch.setenv("AGENTX_SMOKE_MODEL_MAX_RETRIES", "0")

    gateway = gateway_factory()
    gateway.get_llm("eval_proxy")

    assert FakeChatOpenAI.instances[0]["max_retries"] == 0


def test_eval_proxy_disable_model_retry_sets_zero(gateway_factory, monkeypatch):
    monkeypatch.setenv("AGENTX_SMOKE_DISABLE_MODEL_RETRY", "1")

    gateway = gateway_factory()
    gateway.get_llm("eval_proxy")

    assert FakeChatOpenAI.instances[0]["max_retries"] == 0


def test_eval_proxy_without_smoke_retry_env_uses_sdk_default(gateway_factory):
    gateway = gateway_factory()
    gateway.get_llm("eval_proxy")

    assert "max_retries" not in FakeChatOpenAI.instances[0]


def test_non_eval_proxy_ignores_smoke_retry_env(gateway_factory, monkeypatch):
    monkeypatch.setenv("AGENTX_SMOKE_MODEL_MAX_RETRIES", "0")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")

    gateway = gateway_factory()
    gateway.get_llm("deepseek")

    assert "max_retries" not in FakeChatOpenAI.instances[0]


def test_invalid_smoke_model_max_retries_is_ignored(gateway_factory, monkeypatch):
    monkeypatch.setenv("AGENTX_SMOKE_MODEL_MAX_RETRIES", "not-an-int")

    gateway = gateway_factory()
    gateway.get_llm("eval_proxy")

    assert "max_retries" not in FakeChatOpenAI.instances[0]
