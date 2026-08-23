from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import auth_router
from app.core import config


def _public_user() -> auth_router.UserCreate:
    return auth_router.UserCreate(
        username="public_user",
        password="password123",
        email="public_user@example.com",
    )


def test_public_registration_flag_defaults_to_disabled(monkeypatch):
    monkeypatch.delenv("PUBLIC_REGISTRATION_ENABLED", raising=False)

    assert config.is_public_registration_enabled() is False


def test_public_registration_flag_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("PUBLIC_REGISTRATION_ENABLED", "false")
    assert config.is_public_registration_enabled() is False

    monkeypatch.setenv("PUBLIC_REGISTRATION_ENABLED", "true")
    assert config.is_public_registration_enabled() is True


@pytest.mark.asyncio
async def test_public_registration_endpoint_rejects_by_default(monkeypatch):
    monkeypatch.delenv("PUBLIC_REGISTRATION_ENABLED", raising=False)

    def fail_if_database_is_reached(username):
        raise AssertionError("registration policy should reject before database lookup")

    monkeypatch.setattr(
        auth_router.db,
        "_instance",
        SimpleNamespace(get_user_by_username=fail_if_database_is_reached),
        raising=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        await auth_router.register_user(_public_user())

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Public registration is disabled for this demo"
