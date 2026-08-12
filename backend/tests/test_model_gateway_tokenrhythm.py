import pytest

from app.services.model_gateway import ModelGateway


def test_tokenrhythm_provider_uses_tokenrhythm_env(monkeypatch):
    monkeypatch.setenv("TOKENRHYTHM_API_KEY", "test-tokenrhythm-key")
    monkeypatch.delenv("TOKENRHYTHM_API_KEY_API_KEY", raising=False)

    gateway = ModelGateway()

    assert gateway._get_env_api_key("tokenrhythm") == "test-tokenrhythm-key"


def test_missing_default_model_key_does_not_fail_until_invocation(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("VOLCANO_API_KEY", raising=False)

    gateway = ModelGateway()
    llm = gateway.get_llm()

    assert llm.models == []
    with pytest.raises(ValueError, match="No API key available"):
        llm._ensure_models()
