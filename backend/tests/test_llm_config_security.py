import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.companies as companies_api


class FakeCompaniesDB:
    def __init__(self, companies):
        self.companies = dict(companies)
        self.saved_configs = []

    def get_company(self, company_id):
        return self.companies.get(company_id)

    def update_company_llm_config(self, company_id, config_json):
        company = self.companies.get(company_id)
        if company is None:
            return False
        company.llm_api_key = config_json
        self.saved_configs.append((company_id, config_json))
        return True


def _company(company_id, llm_api_key=None):
    return SimpleNamespace(
        id=company_id,
        name=f"Company {company_id}",
        brand_name=f"Brand {company_id}",
        category="beauty",
        platforms_json="douyin_star",
        platform_credentials=None,
        llm_api_key=llm_api_key,
        created_at="2026-08-15T00:00:00Z",
    )


def _user(*, company_id=1, is_admin=False):
    return SimpleNamespace(id=7, username="tester", company_id=company_id, is_admin=is_admin)


def _client(monkeypatch, fake_db, current_user):
    app = FastAPI()
    app.dependency_overrides[companies_api.get_current_active_user] = lambda: current_user
    monkeypatch.setattr(companies_api, "db", fake_db)
    app.include_router(companies_api.router, prefix="/api/admin/companies")
    return TestClient(app)


def _serialized(payload):
    return json.dumps(payload, ensure_ascii=False)


def test_admin_can_store_custom_llm_provider_without_returning_plain_api_key(monkeypatch):
    fake_db = FakeCompaniesDB({1: _company(1)})
    client = _client(monkeypatch, fake_db, _user(company_id=1, is_admin=True))

    response = client.put(
        "/api/admin/companies/1/llm-config",
        json={
            "providers": {
                "custom_proxy": {
                    "providerType": "openai_compatible",
                    "baseUrl": "https://proxy.example.com/v1",
                    "modelName": "custom-chat-model",
                    "enabled": True,
                    "preferredTasks": ["chat", "analysis", "chat"],
                    "apiKey": "sk-test-secret-123456",
                    "tpm": {"limit": 120000},
                    "warnAt90": True,
                }
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    provider = payload["providers"]["custom_proxy"]
    assert provider["providerType"] == "openai_compatible"
    assert provider["baseUrl"] == "https://proxy.example.com/v1"
    assert provider["gateway"] == "https://proxy.example.com/v1"
    assert provider["modelName"] == "custom-chat-model"
    assert provider["enabled"] is True
    assert provider["preferredTasks"] == ["chat", "analysis"]
    assert provider["apiKeyMasked"] == "sk-****3456"
    assert "apiKey" not in provider
    assert "sk-test-secret-123456" not in _serialized(payload)

    stored = json.loads(fake_db.companies[1].llm_api_key)
    stored_provider = stored["custom_proxy"]
    assert stored_provider["apiKey"] == "sk-test-secret-123456"
    assert stored_provider["baseUrl"] == "https://proxy.example.com/v1"
    assert stored_provider["gateway"] == "https://proxy.example.com/v1"
    assert stored_provider["preferredTasks"] == ["chat", "analysis"]
    assert stored_provider["preferred_tasks"] == ["chat", "analysis"]


def test_empty_api_key_preserves_existing_secret(monkeypatch):
    fake_db = FakeCompaniesDB(
        {
            1: _company(
                1,
                json.dumps(
                    {
                        "custom_proxy": {
                            "providerType": "openai_compatible",
                            "baseUrl": "https://old-proxy.example.com/v1",
                            "gateway": "https://old-proxy.example.com/v1",
                            "modelName": "old-model",
                            "apiKey": "sk-existing-secret",
                        }
                    }
                ),
            )
        }
    )
    client = _client(monkeypatch, fake_db, _user(company_id=1, is_admin=True))

    response = client.put(
        "/api/admin/companies/1/llm-config",
        json={
            "providers": {
                "custom_proxy": {
                    "baseUrl": "https://new-proxy.example.com/v1",
                    "modelName": "new-model",
                    "apiKey": "",
                }
            }
        },
    )

    assert response.status_code == 200
    assert "sk-existing-secret" not in _serialized(response.json())
    stored = json.loads(fake_db.companies[1].llm_api_key)
    assert stored["custom_proxy"]["apiKey"] == "sk-existing-secret"
    assert stored["custom_proxy"]["baseUrl"] == "https://new-proxy.example.com/v1"
    assert stored["custom_proxy"]["modelName"] == "new-model"


def test_get_llm_config_masks_stored_api_key(monkeypatch):
    fake_db = FakeCompaniesDB(
        {
            1: _company(
                1,
                json.dumps(
                    {
                        "custom_proxy": {
                            "providerType": "openai_compatible",
                            "baseUrl": "https://proxy.example.com/v1",
                            "apiKey": "sk-stored-secret-9999",
                            "enabled": True,
                            "preferredTasks": ["chat"],
                        }
                    }
                ),
            )
        }
    )
    client = _client(monkeypatch, fake_db, _user(company_id=1, is_admin=False))

    response = client.get("/api/admin/companies/1/llm-config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["providers"]["custom_proxy"]["apiKeyMasked"] == "sk-****9999"
    assert "apiKey" not in payload["providers"]["custom_proxy"]
    assert "sk-stored-secret-9999" not in _serialized(payload)


def test_regular_user_can_update_llm_config_for_own_company(monkeypatch):
    fake_db = FakeCompaniesDB({1: _company(1)})
    client = _client(monkeypatch, fake_db, _user(company_id=1, is_admin=False))

    response = client.put(
        "/api/admin/companies/1/llm-config",
        json={
            "providers": {
                "custom_proxy": {
                    "baseUrl": "https://proxy.example.com/v1",
                    "apiKey": "sk-user-secret",
                }
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    provider = payload["providers"]["custom_proxy"]
    assert provider["baseUrl"] == "https://proxy.example.com/v1"
    assert provider["apiKeyMasked"]
    assert "apiKey" not in provider
    assert "sk-user-secret" not in _serialized(payload)

    stored = json.loads(fake_db.companies[1].llm_api_key)
    assert stored["custom_proxy"]["apiKey"] == "sk-user-secret"
    assert fake_db.saved_configs


def test_regular_user_cannot_update_other_company_llm_config(monkeypatch):
    fake_db = FakeCompaniesDB({1: _company(1), 2: _company(2)})
    client = _client(monkeypatch, fake_db, _user(company_id=1, is_admin=False))

    response = client.put(
        "/api/admin/companies/2/llm-config",
        json={
            "providers": {
                "custom_proxy": {
                    "baseUrl": "https://proxy.example.com/v1",
                    "apiKey": "sk-user-secret",
                }
            }
        },
    )

    assert response.status_code == 403
    assert fake_db.companies[2].llm_api_key is None
    assert fake_db.saved_configs == []


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://proxy.example.com/v1",
        "https://localhost/v1",
        "https://127.0.0.1/v1",
        "https://[::1]/v1",
        "https://10.0.0.1/v1",
        "https://192.168.1.10/v1",
        "https://169.254.169.254/latest/meta-data",
        "https://proxy.example.com/v1?token=x",
        "https://proxy.example.com/v1#fragment",
        "https://user:pass@proxy.example.com/v1",
    ],
)
def test_llm_base_url_rejects_ssrf_risky_targets(monkeypatch, unsafe_url):
    fake_db = FakeCompaniesDB({1: _company(1)})
    client = _client(monkeypatch, fake_db, _user(company_id=1, is_admin=True))

    response = client.put(
        "/api/admin/companies/1/llm-config",
        json={
            "providers": {
                "custom_proxy": {
                    "providerType": "openai_compatible",
                    "baseUrl": unsafe_url,
                    "apiKey": "sk-test-secret",
                }
            }
        },
    )

    assert response.status_code == 422
    assert fake_db.companies[1].llm_api_key is None
    assert fake_db.saved_configs == []
