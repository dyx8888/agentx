import uuid

import httpx


def generate_unique_username(prefix: str = "testuser") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def generate_test_password() -> str:
    return "TestPass123!"


def register_test_user(
    client: httpx.Client,
    username: str | None = None,
    password: str | None = None,
) -> dict:
    username = username or generate_unique_username()
    password = password or generate_test_password()

    response = client.post(
        "/auth/users/register",
        json={"username": username, "password": password},
    )
    response.raise_for_status()
    data = response.json()
    data["password"] = password
    return data


def login_test_user(
    client: httpx.Client,
    username: str,
    password: str,
) -> dict:
    response = client.post(
        "/auth/token",
        data={"username": username, "password": password},
    )
    response.raise_for_status()
    return response.json()