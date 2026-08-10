from tests.performance.deployment_readiness_check import check_env
from tests.performance.deployment_readiness_check import check_health


BASE_ENV = {
    "ENVIRONMENT": "production",
    "ENV": "prod",
    "JWT_SECRET_KEY": "x" * 32,
    "FRONTEND_URL": "https://app.agentx.ai",
    "CORS_ORIGINS": "https://app.agentx.ai",
    "DATABASE_URL": "postgresql://agentx:secret@postgres:5432/agentx",
    "COOKIE_SECURE": "true",
    "ENABLE_PUBLIC_DOCS": "false",
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
        issue["severity"] == "P1" and issue["key"] == "TOKENRHYTHM_API_KEY"
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
        issue["severity"] == "P1" and issue["key"] == "SMTP_HOST"
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
            "url": "http://backend/health",
            "status_code": 200,
            "body": {
                "overall": "healthy",
                "database": {"status": "healthy"},
                "redis": {"status": "not_configured"},
                "environment": {"database_configured": True},
            },
        }
    )

    assert not issues


def test_readiness_probe_flags_503_body_details():
    issues = check_health(
        {
            "url": "http://backend/health",
            "status_code": 503,
            "body": {
                "overall": "unhealthy",
                "database": {"status": "unhealthy"},
                "redis": {"status": "not_configured"},
                "environment": {"database_configured": True},
            },
        }
    )

    keys = {issue["key"] for issue in issues}
    assert "/health" in keys
    assert "database" in keys
