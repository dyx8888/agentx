from app.services.model_gateway import ModelGateway


def test_tokenrhythm_provider_uses_tokenrhythm_env(monkeypatch):
    monkeypatch.setenv("TOKENRHYTHM_API_KEY", "test-tokenrhythm-key")
    monkeypatch.delenv("TOKENRHYTHM_API_KEY_API_KEY", raising=False)

    gateway = ModelGateway()

    assert gateway._get_env_api_key("tokenrhythm") == "test-tokenrhythm-key"
