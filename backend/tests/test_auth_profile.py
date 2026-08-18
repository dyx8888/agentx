import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import auth_router


class _FakeSession:
    def __init__(self, company=None):
        self.company = company
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def query(self, _model):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.company

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _user(**overrides):
    data = {"id": 1, "username": "alice", "company_id": 7, "disabled": False}
    data.update(overrides)
    return SimpleNamespace(**data)


def test_profile_rejects_username_change_without_db_write(monkeypatch):
    def fail_get_session():
        raise AssertionError("username-only rejection should not touch the database")

    monkeypatch.setattr(auth_router, "db", SimpleNamespace(get_session=fail_get_session))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            auth_router.update_current_user_profile(
                auth_router.UserProfileUpdateRequest(username="bob"),
                current_user=_user(),
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "用户名暂不支持在资料页修改"


def test_profile_accepts_same_username_without_db_write(monkeypatch):
    def fail_get_session():
        raise AssertionError("same username should be ignored without a database write")

    monkeypatch.setattr(auth_router, "db", SimpleNamespace(get_session=fail_get_session))

    result = asyncio.run(
        auth_router.update_current_user_profile(
            auth_router.UserProfileUpdateRequest(username="alice"),
            current_user=_user(),
        )
    )

    assert result == {"success": True, "message": "资料已保存"}


def test_profile_still_updates_company_fields(monkeypatch):
    company = SimpleNamespace(name="Old Co", brand_name="Old Brand", category="old")
    session = _FakeSession(company=company)
    monkeypatch.setattr(auth_router, "db", SimpleNamespace(get_session=lambda: session))

    result = asyncio.run(
        auth_router.update_current_user_profile(
            auth_router.UserProfileUpdateRequest(
                company_name="New Co",
                brand_name="New Brand",
                category="beauty",
            ),
            current_user=_user(),
        )
    )

    assert result == {"success": True, "message": "资料已保存"}
    assert company.name == "New Co"
    assert company.brand_name == "New Brand"
    assert company.category == "beauty"
    assert session.commits == 1

