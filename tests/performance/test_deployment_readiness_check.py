from tests.performance.deployment_readiness_check import check_env
from tests.performance.deployment_readiness_check import check_health


BASE_ENV = {
    "ENV": "prod",
    "JWT_SECRET_KEY": "x" * 32,
    "ENCRYPTION_KEY": "y" * 32,
    "CORS_ORIGINS": "https://app.agentx.ai",
    "DATABASE_URL": "postgresql://agentx:secret@postgres:5432/agentx",
    "REDIS_URL": "redis://redis:6379/0",
    "VECTOR_DB": "milvus",
    "MILVUS_HOST": "milvus",
    "MILVUS_PORT": "19530",
    "MILVUS_COLLECTION": "agentx_vectors",
    "ALLOW_PLATFORM_MOCK_FALLBACK": "false",
    "ALLOW_ENTERPRISE_MOCK_INTEGRATIONS": "false",
    "COOKIE_SECURE": "true",
    "SMTP_HOST": "smtp.agentx.ai",
    "SMTP_PORT": "587",
    "SMTP_USER": "notify@agentx.ai",
    "SMTP_PASSWORD": "smtp-password-with-length",
    "SMTP_FROM": "notify@agentx.ai",
}


def test_deepseek_default_does_not_require_tokenrhythm():
    issues = check_env(
        {**BASE_ENV, "MODEL_GATEWAY_DEFAULT": "deepseek"},
        counts={},
        target="cloud",
        runtime_secrets={"DEEPSEEK_API_KEY"},
    )

    assert not any(issue["key"] == "TOKENRHYTHM_API_KEY" for issue in issues)
    assert not any(issue["severity"] == "P0" for issue in issues)


def test_tokenrhythm_model_requires_tokenrhythm_key():
    issues = check_env(
        {**BASE_ENV, "MODEL_GATEWAY_DEFAULT": "glm52"},
        counts={},
        target="cloud",
        runtime_secrets={"DEEPSEEK_API_KEY"},
    )

    assert any(
        issue["severity"] == "P0" and issue["key"] == "TOKENRHYTHM_API_KEY"
        for issue in issues
    )


def test_cloud_rejects_mailhog_smtp():
    issues = check_env(
        {**BASE_ENV, "SMTP_HOST": "mailhog", "SMTP_PORT": "1025"},
        counts={},
        target="cloud",
        runtime_secrets={"DEEPSEEK_API_KEY"},
    )

    assert any(
        issue["severity"] == "P0" and issue["key"] == "SMTP_HOST"
        for issue in issues
    )


def test_cloud_rejects_enterprise_mock_integrations():
    issues = check_env(
        {**BASE_ENV, "ALLOW_ENTERPRISE_MOCK_INTEGRATIONS": "true"},
        counts={},
        target="cloud",
        runtime_secrets={"DEEPSEEK_API_KEY"},
    )

    assert any(
        issue["severity"] == "P0" and issue["key"] == "ALLOW_ENTERPRISE_MOCK_INTEGRATIONS"
        for issue in issues
    )


def test_readiness_probe_passes_only_on_ready_response():
    issues = check_health(
        {
            "url": "http://backend/ready",
            "status_code": 200,
            "body": {
                "ready": True,
                "overall": "healthy",
                "database": {"status": "healthy"},
                "redis": {"status": "healthy"},
                "milvus": {"status": "healthy"},
                "chat_agent": {"status": "ready"},
                "environment": {"vector_db": "milvus", "milvus_configured": True},
            },
        }
    )

    assert not issues


def test_readiness_probe_flags_503_body_details():
    issues = check_health(
        {
            "url": "http://backend/ready",
            "status_code": 503,
            "body": {
                "ready": False,
                "overall": "degraded",
                "database": {"status": "healthy"},
                "redis": {"status": "healthy"},
                "milvus": {"status": "not_configured"},
                "chat_agent": {"status": "not_initialized"},
                "environment": {"vector_db": "milvus", "milvus_configured": False},
            },
        }
    )

    keys = {issue["key"] for issue in issues}
    assert "/ready" in keys
    assert "milvus" in keys
    assert "chat_agent" in keys
