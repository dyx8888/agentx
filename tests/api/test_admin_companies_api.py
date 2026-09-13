import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.companies as companies_api


class FakeCompaniesDB:
    def __init__(self, companies=None, *, fail_reads=False, fail_writes=False):
        self.companies = dict(companies or {})
        self.fail_reads = fail_reads
        self.fail_writes = fail_writes

    def get_all_companies(self):
        if self.fail_reads:
            raise RuntimeError("companies schema unavailable")
        return list(self.companies.values())

    def get_company(self, company_id):
        if self.fail_reads:
            raise RuntimeError("companies schema unavailable")
        return self.companies.get(company_id)

    def update_company_platform_credentials(self, company_id, credentials_json):
        if self.fail_writes:
            return False
        company = self.companies.get(company_id)
        if company is None:
            return False
        company.platform_credentials = credentials_json
        return True


def _company(company_id, name, *, platform_credentials=None, llm_api_key=None):
    return SimpleNamespace(
        id=company_id,
        name=name,
        brand_name=f"{name} Brand",
        category="beauty",
        platforms_json="douyin_star,xiaohongshu",
        platform_credentials=platform_credentials,
        llm_api_key=llm_api_key,
        access_token="company-object-access-token",
        api_secret="company-object-api-secret",
        created_at="2026-08-13T00:00:00Z",
    )


def _user(*, company_id=1, is_admin=False):
    return SimpleNamespace(id=99, username="tester", company_id=company_id, is_admin=is_admin)


@pytest.fixture
def companies_db():
    return FakeCompaniesDB(
        {
            1: _company(
                1,
                "Alpha",
                platform_credentials=json.dumps(
                    {
                        "douyin_star": {
                            "credentials": {
                                "app_id": "alpha-app-id",
                                "app_secret": "alpha-super-secret",
                                "access_token": "alpha-access-token",
                                "advertiser_id": "alpha-advertiser",
                            },
                            "_meta": {
                                "last_verified": "2026-08-13T00:00:00Z",
                                "last_verify_valid": True,
                            },
                        }
                    }
                ),
                llm_api_key=json.dumps({"deepseek": {"apiKey": "sk-alpha-secret"}}),
            ),
            2: _company(2, "Beta"),
        }
    )


def _client(monkeypatch, fake_db, current_user):
    app = FastAPI()
    app.dependency_overrides[companies_api.get_current_active_user] = lambda: current_user
    app.dependency_overrides[companies_api.admin_required] = lambda: current_user
    monkeypatch.setattr(companies_api, "db", fake_db)
    app.include_router(companies_api.router, prefix="/api/admin/companies")
    return TestClient(app)


def _serialized(payload):
    return json.dumps(payload, ensure_ascii=False)


def test_admin_companies_list_is_available_for_admin(monkeypatch, companies_db):
    client = _client(monkeypatch, companies_db, _user(company_id=1, is_admin=True))

    response = client.get("/api/admin/companies/")

    assert response.status_code == 200
    payload = response.json()
    assert [company["id"] for company in payload] == [1, 2]
    serialized = _serialized(payload)
    assert "platform_credentials" not in serialized
    assert "llm_api_key" not in serialized
    assert "access_token" not in serialized
    assert "api_secret" not in serialized
    assert "alpha-super-secret" not in serialized
    assert "sk-alpha-secret" not in serialized


def test_regular_user_companies_list_is_tenant_scoped(monkeypatch, companies_db):
    client = _client(monkeypatch, companies_db, _user(company_id=1, is_admin=False))

    response = client.get("/api/admin/companies/")

    assert response.status_code == 200
    assert [company["id"] for company in response.json()] == [1]
    assert "Beta" not in _serialized(response.json())


def test_regular_user_cannot_read_other_company(monkeypatch, companies_db):
    client = _client(monkeypatch, companies_db, _user(company_id=1, is_admin=False))

    response = client.get("/api/admin/companies/2")

    assert response.status_code == 403
    assert "Beta" not in _serialized(response.json())


def test_companies_list_degrades_to_empty_when_db_unavailable(monkeypatch):
    client = _client(
        monkeypatch,
        FakeCompaniesDB(fail_reads=True),
        _user(company_id=1, is_admin=True),
    )

    response = client.get("/api/admin/companies/")

    assert response.status_code == 200
    assert response.json() == []


def test_bind_platform_credentials_missing_fields_returns_client_error(
    monkeypatch,
    companies_db,
):
    client = _client(monkeypatch, companies_db, _user(company_id=1, is_admin=True))

    response = client.post(
        "/api/admin/companies/1/credentials",
        json={"platform": "douyin_star", "credentials": {"app_id": "alpha-app-id"}},
    )

    assert response.status_code == 422
    assert "Missing required credential fields" in response.json()["detail"]


def test_list_platform_credentials_returns_masked_status_only(monkeypatch, companies_db):
    client = _client(monkeypatch, companies_db, _user(company_id=1, is_admin=False))

    response = client.get("/api/admin/companies/1/credentials")

    assert response.status_code == 200
    payload = response.json()
    douyin = next(item for item in payload if item["platform"] == "douyin_star")
    assert douyin == {
        "platform": "douyin_star",
        "bound": True,
        "last_verified": "2026-08-13T00:00:00Z",
        "last_verify_valid": True,
    }
    serialized = _serialized(payload)
    assert "credentials" not in serialized
    assert "app_secret" not in serialized
    assert "access_token" not in serialized
    assert "alpha-super-secret" not in serialized
    assert "alpha-access-token" not in serialized


def test_verify_platform_credentials_is_paused(monkeypatch, companies_db):
    client = _client(monkeypatch, companies_db, _user(company_id=2, is_admin=False))

    response = client.post("/api/admin/companies/2/credentials/douyin_star/verify")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "platform_api_paused"


def test_bind_platform_credentials_write_failure_is_not_success(monkeypatch, companies_db):
    companies_db.fail_writes = True
    client = _client(monkeypatch, companies_db, _user(company_id=1, is_admin=True))

    response = client.post(
        "/api/admin/companies/1/credentials",
        json={
            "platform": "douyin_star",
            "credentials": {
                "app_id": "alpha-app-id",
                "app_secret": "alpha-super-secret",
                "access_token": "alpha-access-token",
                "advertiser_id": "alpha-advertiser",
            },
        },
    )

    assert response.status_code == 500
    assert "updated successfully" not in _serialized(response.json())
