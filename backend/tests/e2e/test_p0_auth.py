import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.e2e.factories.user_factory import generate_unique_username, generate_test_password


class TestP0Auth:
    @pytest.mark.p0
    def test_register_user_success(self, api_client: httpx.Client):
        username = generate_unique_username("p0reg")
        response = api_client.post(
            "/auth/users/register",
            json={"username": username, "password": generate_test_password()},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == username
        assert "id" in data

    @pytest.mark.p0
    def test_register_duplicate_user_fails(self, api_client: httpx.Client):
        username = generate_unique_username("p0dup")
        response = api_client.post(
            "/auth/users/register",
            json={"username": username, "password": generate_test_password()},
        )
        assert response.status_code == 200

        response = api_client.post(
            "/auth/users/register",
            json={"username": username, "password": "AnotherPass123!"},
        )
        assert response.status_code == 400

    @pytest.mark.p0
    def test_login_success(self, api_client: httpx.Client):
        username = generate_unique_username("p0login")
        password = generate_test_password()
        response = api_client.post(
            "/auth/users/register",
            json={"username": username, "password": password},
        )
        assert response.status_code == 200

        response = api_client.post(
            "/auth/token",
            data={"username": username, "password": password},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.p0
    def test_login_invalid_credentials(self, api_client: httpx.Client):
        response = api_client.post(
            "/auth/token",
            data={"username": "nonexistent_user", "password": "WrongPass123!"},
        )
        assert response.status_code == 401

    @pytest.mark.p0
    def test_get_current_user_with_valid_token(self, api_client: httpx.Client):
        username = generate_unique_username("p0me")
        password = generate_test_password()
        response = api_client.post(
            "/auth/users/register",
            json={"username": username, "password": password},
        )
        assert response.status_code == 200

        login_resp = api_client.post(
            "/auth/token",
            data={"username": username, "password": password},
        )
        token = login_resp.json()["access_token"]

        response = api_client.get(
            "/auth/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == username

    @pytest.mark.p0
    def test_get_current_user_without_token(self, api_client: httpx.Client):
        response = api_client.get("/auth/users/me")
        assert response.status_code == 401

    @pytest.mark.p0
    def test_get_current_user_with_invalid_token(self, api_client: httpx.Client):
        response = api_client.get(
            "/auth/users/me",
            headers={"Authorization": "Bearer invalid_token_here"},
        )
        assert response.status_code == 401

    @pytest.mark.p3
    def test_register_short_password_fails(self, api_client: httpx.Client):
        username = generate_unique_username("p0short")
        response = api_client.post(
            "/auth/users/register",
            json={"username": username, "password": "short"},
        )
        assert response.status_code == 422