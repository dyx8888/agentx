from tests.performance.public_demo_deployment_template_audit import run_audit


BASE_FILES = {
    "render.yaml": "\n".join(
        [
            "services:",
            "  - type: web",
            "    name: agentx-backend-public-demo",
            "    runtime: python",
            "    rootDir: .",
            "    buildCommand: python -m pip install --upgrade pip && python -m pip install -r backend/requirements.txt",
            "    startCommand: PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port $PORT",
            "    healthCheckPath: /health",
            "    autoDeploy: false",
            "    envVars:",
            "      - key: ENVIRONMENT",
            "        value: production",
            "      - key: ENV",
            "        value: prod",
            "      - key: DATABASE_URL",
            "        sync: false",
            "      - key: JWT_SECRET_KEY",
            "        sync: false",
            "      - key: FRONTEND_URL",
            "        sync: false",
            "      - key: CORS_ORIGINS",
            "        sync: false",
            "      - key: COOKIE_SECURE",
            '        value: "true"',
            "      - key: ENABLE_PUBLIC_DOCS",
            '        value: "false"',
            "      - key: ENABLE_EVOLUTION_API",
            '        value: "false"',
            "      - key: REDIS_URL",
            "        sync: false",
            "      - key: MILVUS_HOST",
            "        sync: false",
            "      - key: SMTP_HOST",
            "        sync: false",
            "      - key: SMTP_USERNAME",
            "        sync: false",
            "      - key: SMTP_PASSWORD",
            "        sync: false",
            "      - key: SMTP_FROM",
            "        sync: false",
            "      - key: OAUTH_REDIRECT_BASE_URL",
            "        sync: false",
        ]
    ),
    "frontend/vercel.json": '{"framework":"vite","installCommand":"npm ci","buildCommand":"npm run build","outputDirectory":"dist","rewrites":[{"source":"/(.*)","destination":"/index.html"}]}',
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
    "frontend/.env.example": "\n".join(
        [
            "VITE_API_BASE_URL=/api",
            "VITE_WS_BASE=",
            "VITE_DEMO_ENABLED=false",
            "VITE_DEMO_PASSWORD=",
        ]
    ),
}


def _reader(files):
    def read(path):
        return files[path]

    return read


def _failed_names(report):
    return {check["name"] for check in report["checks"] if not check["passed"]}


def test_deployment_template_audit_passes_public_demo_baseline():
    report = run_audit(read=_reader(BASE_FILES))

    assert report["summary"]["passed"] is True


def test_deployment_template_audit_fails_when_render_secret_is_filled():
    files = {
        **BASE_FILES,
        "render.yaml": BASE_FILES["render.yaml"].replace(
            "      - key: JWT_SECRET_KEY\n        sync: false",
            "      - key: JWT_SECRET_KEY\n        value: real-secret",
        ),
    }

    report = run_audit(read=_reader(files))

    assert "Render blueprint externalized runtime values" in _failed_names(report)


def test_deployment_template_audit_fails_when_public_docs_are_enabled():
    files = {
        **BASE_FILES,
        "render.yaml": BASE_FILES["render.yaml"].replace(
            '      - key: ENABLE_PUBLIC_DOCS\n        value: "false"',
            '      - key: ENABLE_PUBLIC_DOCS\n        value: "true"',
        ),
    }

    report = run_audit(read=_reader(files))

    assert "Render blueprint production toggles" in _failed_names(report)


def test_deployment_template_audit_fails_invalid_vercel_spa_rewrite():
    files = {
        **BASE_FILES,
        "frontend/vercel.json": '{"framework":"vite","installCommand":"npm ci","buildCommand":"npm run build","outputDirectory":"dist"}',
    }

    report = run_audit(read=_reader(files))

    assert "Vercel config" in _failed_names(report)


def test_deployment_template_audit_fails_filled_backend_secret():
    files = {
        **BASE_FILES,
        "backend/.env.production.example": BASE_FILES["backend/.env.production.example"].replace(
            "JWT_SECRET_KEY=",
            "JWT_SECRET_KEY=real-secret",
        ),
    }

    report = run_audit(read=_reader(files))

    assert "Backend production env template" in _failed_names(report)


def test_deployment_template_audit_fails_frontend_demo_password():
    files = {
        **BASE_FILES,
        "frontend/.env.example": BASE_FILES["frontend/.env.example"].replace(
            "VITE_DEMO_PASSWORD=",
            "VITE_DEMO_PASSWORD=demo-password",
        ),
    }

    report = run_audit(read=_reader(files))

    assert "Frontend env template" in _failed_names(report)
