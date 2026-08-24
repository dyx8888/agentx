from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import auth_router
from app.auth import hash_password
from app.database.models import Base, Company, User


class FakeAuthDB:
    def __init__(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    @contextmanager
    def get_session(self):
        session = self.Session()
        try:
            yield session
        finally:
            session.close()

    def get_user_by_username(self, username):
        with self.get_session() as session:
            return session.query(User).filter(User.username == username).first()

    def get_user_by_id(self, user_id):
        with self.get_session() as session:
            return session.query(User).filter(User.id == user_id).first()

    def get_company(self, company_id):
        with self.get_session() as session:
            return session.query(Company).filter(Company.id == company_id).first()

    def create_company(self, company):
        with self.get_session() as session:
            session.add(company)
            session.commit()
            return company.id


def _user_create(username="verify_user", email="verify@example.com"):
    return auth_router.UserCreate(
        username=username,
        password="password123",
        email=email,
        company_name="Verify Co",
        brand_name="Verify",
        category="beauty",
    )


@pytest.fixture
def auth_db(monkeypatch):
    fake = FakeAuthDB()
    monkeypatch.setattr(auth_router.db, "_instance", fake, raising=False)
    monkeypatch.setattr(auth_router, "_get_secret_key", lambda: "test-secret-key")
    monkeypatch.setattr(auth_router, "is_public_registration_enabled", lambda: True)
    return fake


@pytest.mark.asyncio
async def test_register_creates_pending_user_and_sends_verification_code(auth_db, monkeypatch):
    sent = []

    async def fake_send(email, username, code):
        sent.append((email, username, code))
        return True

    monkeypatch.setattr(auth_router, "_send_email_verification_code", fake_send)
    monkeypatch.setattr(auth_router, "_generate_email_verification_code", lambda: "123456")

    result = await auth_router.register_user(_user_create(email="Verify@Example.com"))

    assert result.email_verification_required is True
    assert result.email_verified is False
    assert result.masked_email == "ve***@example.com"
    assert result.disabled is True
    assert sent == [("verify@example.com", "verify_user", "123456")]

    with auth_db.get_session() as session:
        user = session.query(User).filter(User.username == "verify_user").one()
        assert user.email == "verify@example.com"
        assert user.email_verified is False
        assert user.disabled is True
        assert user.is_active is False
        assert user.email_verification_code_hash is not None
        assert user.email_verification_code_hash != "123456"
        assert user.email_verification_attempts == 0


@pytest.mark.asyncio
async def test_unverified_user_cannot_login_until_code_verified(auth_db, monkeypatch):
    async def fake_send(email, username, code):
        return True

    monkeypatch.setattr(auth_router, "_send_email_verification_code", fake_send)
    monkeypatch.setattr(auth_router, "_generate_email_verification_code", lambda: "654321")

    await auth_router.register_user(_user_create(username="blocked", email="blocked@example.com"))

    form = SimpleNamespace(username="blocked", password="password123")
    with pytest.raises(HTTPException) as exc_info:
        await auth_router.login_for_access_token(Response(), form)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Email verification required"

    verified = await auth_router.verify_email_code(
        auth_router.EmailVerifyCodeRequest(email="blocked@example.com", code="654321")
    )
    assert verified["success"] is True

    login_result = await auth_router.login_for_access_token(Response(), form)
    assert login_result["access_token"]


@pytest.mark.asyncio
async def test_wrong_code_increments_attempts_without_activation(auth_db, monkeypatch):
    async def fake_send(email, username, code):
        return True

    monkeypatch.setattr(auth_router, "_send_email_verification_code", fake_send)
    monkeypatch.setattr(auth_router, "_generate_email_verification_code", lambda: "111111")
    await auth_router.register_user(_user_create(username="wrong", email="wrong@example.com"))

    with pytest.raises(HTTPException):
        await auth_router.verify_email_code(
            auth_router.EmailVerifyCodeRequest(email="wrong@example.com", code="222222")
        )

    with auth_db.get_session() as session:
        user = session.query(User).filter(User.username == "wrong").one()
        assert user.email_verification_attempts == 1
        assert user.email_verified is False
        assert user.disabled is True


@pytest.mark.asyncio
async def test_resend_code_updates_hash_and_uses_uniform_response(auth_db, monkeypatch):
    codes = iter(["111111", "222222"])
    sent = []

    async def fake_send(email, username, code):
        sent.append((email, username, code))
        return True

    monkeypatch.setattr(auth_router, "_send_email_verification_code", fake_send)
    monkeypatch.setattr(auth_router, "_generate_email_verification_code", lambda: next(codes))
    monkeypatch.setattr(auth_router, "EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS", 0)

    await auth_router.register_user(_user_create(username="resend", email="resend@example.com"))
    with auth_db.get_session() as session:
        before = session.query(User).filter(User.username == "resend").one().email_verification_code_hash

    response = await auth_router.resend_email_code(
        auth_router.EmailResendCodeRequest(email="resend@example.com")
    )

    assert response["success"] is True
    assert sent[-1] == ("resend@example.com", "resend", "222222")
    with auth_db.get_session() as session:
        after = session.query(User).filter(User.username == "resend").one().email_verification_code_hash
    assert after != before

    missing = await auth_router.resend_email_code(
        auth_router.EmailResendCodeRequest(email="missing@example.com")
    )
    assert missing == response


@pytest.mark.asyncio
async def test_verified_user_verify_code_is_idempotent(auth_db, monkeypatch):
    async def fake_send(email, username, code):
        return True

    monkeypatch.setattr(auth_router, "_send_email_verification_code", fake_send)
    monkeypatch.setattr(auth_router, "_generate_email_verification_code", lambda: "333333")
    await auth_router.register_user(_user_create(username="done", email="done@example.com"))
    await auth_router.verify_email_code(
        auth_router.EmailVerifyCodeRequest(email="done@example.com", code="333333")
    )

    response = await auth_router.verify_email_code(
        auth_router.EmailVerifyCodeRequest(email="done@example.com", code="333333")
    )
    assert response["success"] is True
    assert response["message"] == "邮箱已验证"
