from tests.performance.public_demo_cloud_prereq_audit import run_audit


def _commands(names):
    return lambda command: command in names


def _env(values):
    return lambda name: values.get(name)


def _by_name(report):
    return {check["name"]: check for check in report["checks"]}


def test_cloud_prereq_audit_reports_missing_provider_access_as_pending():
    report = run_audit(has_command=_commands(set()), get_env=_env({}))

    assert report["summary"]["ready_for_automated_cloud_deploy"] is False
    assert report["summary"]["failure_count"] == 0
    assert report["summary"]["pending_external_count"] == 4
    checks = _by_name(report)
    assert checks["Vercel access"]["status"] == "pending_external"
    assert checks["Render access"]["status"] == "pending_external"
    assert checks["Managed Postgres access"]["status"] == "pending_external"
    assert checks["Production runtime env"]["status"] == "pending_external"


def test_cloud_prereq_audit_passes_when_cli_or_safe_env_is_available():
    report = run_audit(
        has_command=_commands({"vercel", "render"}),
        get_env=_env(
            {
                "NEON_API_KEY": "secret-never-printed",
                "DATABASE_URL": "postgresql://user:secret@example.neon.tech/agentx",
                "JWT_SECRET_KEY": "secret-never-printed",
                "FRONTEND_URL": "https://agentx.example.com",
                "CORS_ORIGINS": "https://agentx.example.com",
            }
        ),
    )

    assert report["summary"]["ready_for_automated_cloud_deploy"] is True
    assert report["summary"]["failure_count"] == 0
    assert report["summary"]["pending_external_count"] == 0


def test_cloud_prereq_audit_does_not_print_secret_values():
    report = run_audit(
        has_command=_commands({"vercel", "render"}),
        get_env=_env(
            {
                "NEON_API_KEY": "actual-neon-secret",
                "DATABASE_URL": "postgresql://user:actual-password@example.neon.tech/agentx",
                "JWT_SECRET_KEY": "actual-jwt-secret",
                "FRONTEND_URL": "https://agentx.example.com",
                "CORS_ORIGINS": "https://agentx.example.com",
            }
        ),
    )
    rendered = str(report)

    assert "actual-neon-secret" not in rendered
    assert "actual-password" not in rendered
    assert "actual-jwt-secret" not in rendered


def test_cloud_prereq_audit_fails_unsafe_public_cors():
    report = run_audit(
        has_command=_commands({"vercel", "render", "neon"}),
        get_env=_env(
            {
                "DATABASE_URL": "postgresql://user:secret@example.neon.tech/agentx",
                "JWT_SECRET_KEY": "secret-never-printed",
                "FRONTEND_URL": "https://agentx.example.com",
                "CORS_ORIGINS": "*",
            }
        ),
    )

    checks = _by_name(report)
    assert report["summary"]["ready_for_automated_cloud_deploy"] is False
    assert checks["Production runtime env"]["status"] == "fail"
    assert "wildcard" in checks["Production runtime env"]["detail"]
