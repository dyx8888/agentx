from tests.performance.public_demo_security_audit import GitResult
from tests.performance.public_demo_security_audit import run_audit


BASE_FILES = {
    "backend/.env.example": "\n".join(
        [
            "DATABASE_URL=postgresql://user:password@localhost:5432/agentx",
            "DEEPSEEK_API_KEY=your_key_here",
        ]
    ),
    "backend/.env.production.example": "\n".join(
        [
            "ENVIRONMENT=production",
            "ENV=prod",
            "DATABASE_URL=",
            "JWT_SECRET_KEY=",
            "FRONTEND_URL=https://your-frontend.example.com",
            "CORS_ORIGINS=https://your-frontend.example.com",
            "COOKIE_SECURE=true",
            "ENABLE_PUBLIC_DOCS=false",
            "ENABLE_EVOLUTION_API=false",
        ]
    ),
    "backend/config/.env.example": "JWT_SECRET=your-secret-key-here",
    "backend/docker-compose.yml": "\n".join(
        [
            "DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}",
            "DATABASE_URL=${DATABASE_URL:-postgresql://agentx:change-me-local-only@postgres:5432/agentx}",
            "REDIS_URL=redis://redis:6379/0",
        ]
    ),
    "deploy/render.example.yaml": "\n".join(
        [
            "- key: DATABASE_URL",
            "  sync: false",
            "- key: JWT_SECRET_KEY",
            "  sync: false",
        ]
    ),
    "frontend/.env.example": "\n".join(
        [
            "VITE_API_BASE_URL=/api",
            "VITE_DEMO_ENABLED=false",
            "VITE_DEMO_PASSWORD=",
        ]
    ),
    "README.md": "Online demo: not deployed yet.",
}


def _git_with_files(paths):
    return lambda args: GitResult(0, "\n".join(paths) if args == ["ls-files"] else "", "")


def _reader(files):
    def read(path):
        return files[path]

    return read


def test_security_audit_passes_public_demo_baseline():
    report = run_audit(
        git=_git_with_files(BASE_FILES),
        read_text=_reader(BASE_FILES),
    )

    assert report["summary"]["passed"] is True


def test_security_audit_fails_tracked_runtime_data():
    files = {**BASE_FILES, "backend/data/agentx.db": "binary"}

    report = run_audit(
        git=_git_with_files(files),
        read_text=_reader(files),
    )

    failed = {check["name"] for check in report["checks"] if not check["passed"]}
    assert "runtime artifacts not tracked" in failed


def test_security_audit_fails_debug_or_generated_public_demo_file():
    files = {**BASE_FILES, "backend/debug_agent.py": "print('debug')"}

    report = run_audit(
        git=_git_with_files(files),
        read_text=_reader(files),
    )

    failed = {check["name"] for check in report["checks"] if not check["passed"]}
    assert "debug and generated public-demo files not tracked" in failed


def test_security_audit_fails_filled_production_secret():
    files = {
        **BASE_FILES,
        "backend/.env.production.example": BASE_FILES["backend/.env.production.example"].replace(
            "JWT_SECRET_KEY=", "JWT_SECRET_KEY=real-looking-secret-value"
        ),
    }

    report = run_audit(
        git=_git_with_files(files),
        read_text=_reader(files),
    )

    failed = {check["name"] for check in report["checks"] if not check["passed"]}
    assert "production secrets are not filled" in failed


def test_security_audit_fails_when_production_evolution_api_enabled():
    files = {
        **BASE_FILES,
        "backend/.env.production.example": BASE_FILES["backend/.env.production.example"].replace(
            "ENABLE_EVOLUTION_API=false", "ENABLE_EVOLUTION_API=true"
        ),
    }

    report = run_audit(
        git=_git_with_files(files),
        read_text=_reader(files),
    )

    failed = {check["name"] for check in report["checks"] if not check["passed"]}
    assert "production evolution api disabled by default" in failed


def test_security_audit_fails_filled_sensitive_config_value():
    files = {
        **BASE_FILES,
        "backend/.env.example": BASE_FILES["backend/.env.example"].replace(
            "DEEPSEEK_API_KEY=your_key_here",
            "DEEPSEEK_API_KEY=real-provider-key-12345",
        ),
    }

    report = run_audit(
        git=_git_with_files(files),
        read_text=_reader(files),
    )

    failed = {check["name"] for check in report["checks"] if not check["passed"]}
    assert "sensitive config placeholders are not filled" in failed


def test_security_audit_fails_credentialed_redis_url():
    files = {
        **BASE_FILES,
        "backend/docker-compose.yml": BASE_FILES["backend/docker-compose.yml"].replace(
            "REDIS_URL=redis://redis:6379/0",
            "REDIS_URL=redis://user:real-password@redis:6379/0",
        ),
    }

    report = run_audit(
        git=_git_with_files(files),
        read_text=_reader(files),
    )

    failed = {check["name"] for check in report["checks"] if not check["passed"]}
    assert "sensitive config placeholders are not filled" in failed


def test_security_audit_fails_unexpected_env_file():
    files = {**BASE_FILES, ".env": "JWT_SECRET_KEY=local-secret"}

    report = run_audit(
        git=_git_with_files(files),
        read_text=_reader(files),
    )

    failed = {check["name"] for check in report["checks"] if not check["passed"]}
    assert "only env templates tracked" in failed


def test_security_audit_fails_high_confidence_secret_pattern():
    files = {**BASE_FILES, "docs/leak.txt": "ghp_" + "a" * 36}

    report = run_audit(
        git=_git_with_files(files),
        read_text=_reader(files),
    )

    failed = {check["name"] for check in report["checks"] if not check["passed"]}
    assert "high-confidence secret patterns" in failed
