from tests.performance.public_demo_completion_audit import GitResult
from tests.performance.public_demo_completion_audit import REQUIRED_TRACKED_FILES
from tests.performance.public_demo_completion_audit import run_audit


BASE_TEXT = {
    "README.md": "\n".join(
        [
            "This repository should be treated as a public-demo candidate.",
            "- Online demo: not deployed yet.",
            "- Public smoke test: not verified yet.",
            "- Selected first deployment path: Vercel frontend, Render backend, Neon Postgres.",
            "- Backend trusted-path/API regression gate: `39 passed, 85 skipped`",
            "- Backend schema/model/runtime/readiness/public-demo audit gate: `38 passed, 5 skipped, 1 warning`",
            "- Frontend tests: `12 passed files / 71 passed tests`",
            "- Filled sensitive config placeholder count: `0`",
        ]
    ),
    "docs/public-demo-readiness-2026-08-11.md": "Not Yet Proven\nDeferred Items\n2fa89b9",
    "docs/public-demo-deployment-runbook-2026-08-11.md": "Completion Rule\nVercel\nRender\nNeon\ndocs/public-demo-visual-evidence-plan-2026-08-11.md\n60-90 second recording",
    "docs/public-demo-cloud-handoff-2026-08-11.md": "Verified Input Baseline\nAccess Required\nUser-Side Cloud Steps\nMigration Verification\nCodex Verification After URLs Exist\nStop Conditions",
    "docs/public-demo-smoke-template-2026-08-11.md": "Frontend URL: `TBD`\nBackend URL: `TBD`\nHigh-risk action",
    "docs/public-demo-visual-evidence-plan-2026-08-11.md": "Capture Rules\nRequired Screenshots\nRecording Script",
    "docs/interview-demo-guide-2026-08-11.md": "3-Minute Version\n10-Minute Version\nScreenshot",
    "docs/demo-data/README.md": "fictional demo data\nDo not use real customers",
    "deploy/render.example.yaml": "\n".join(
        [
            "runtime: python",
            "rootDir: .",
            "buildCommand: python -m pip install --upgrade pip && python -m pip install -r backend/requirements.txt",
            "startCommand: PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port $PORT",
            "healthCheckPath: /health",
            "key: DATABASE_URL",
            "key: JWT_SECRET_KEY",
            "key: CORS_ORIGINS",
            "key: COOKIE_SECURE",
            'value: "true"',
            "key: ENABLE_PUBLIC_DOCS",
            'value: "false"',
            "key: ENABLE_EVOLUTION_API",
            'value: "false"',
        ]
    ),
    "render.yaml": "\n".join(
        [
            "runtime: python",
            "rootDir: .",
            "buildCommand: python -m pip install --upgrade pip && python -m pip install -r backend/requirements.txt",
            "startCommand: PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port $PORT",
            "healthCheckPath: /health",
            "autoDeploy: false",
            "key: DATABASE_URL",
            "key: JWT_SECRET_KEY",
            "key: FRONTEND_URL",
            "key: CORS_ORIGINS",
            "key: COOKIE_SECURE",
            'value: "true"',
            "key: ENABLE_PUBLIC_DOCS",
            'value: "false"',
            "key: ENABLE_EVOLUTION_API",
            'value: "false"',
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
    "frontend/.env.example": "\n".join(
        [
            "VITE_API_BASE_URL=/api",
            "VITE_WS_BASE=",
            "VITE_DEMO_ENABLED=false",
            "VITE_DEMO_PASSWORD=",
        ]
    ),
    "frontend/vercel.json": '{"framework":"vite","installCommand":"npm ci","buildCommand":"npm run build","outputDirectory":"dist","rewrites":[{"source":"/(.*)","destination":"/index.html"}]}',
}


def _fake_git(
    files=None,
    dirty="",
    branch="codex/public-demo-20260810",
    head="abc123",
    tag_target="abc123",
    remote_pushed=True,
):
    tracked = sorted(files or REQUIRED_TRACKED_FILES)

    def run(args):
        key = tuple(args)
        if key == ("ls-files",):
            return GitResult(0, "\n".join(tracked), "")
        if key == ("branch", "--show-current"):
            return GitResult(0, branch, "")
        if key == ("status", "--porcelain=v1"):
            return GitResult(0, dirty, "")
        if key == ("rev-parse", "HEAD"):
            return GitResult(0, head, "")
        if key == ("rev-list", "-n", "1", "public-demo-local-20260811-v10"):
            return GitResult(0, tag_target, "")
        if key == ("rev-list", "--objects", "HEAD"):
            return GitResult(0, "abc123 README.md\nabc124 backend/app/main.py", "")
        if key == ("ls-remote", "--heads", "origin", "codex/public-demo-20260810"):
            if remote_pushed:
                return GitResult(0, f"{head}\trefs/heads/codex/public-demo-20260810", "")
            return GitResult(2, "", "remote branch missing")
        if key == ("ls-remote", "--tags", "origin", "public-demo-local-20260811-v10"):
            if remote_pushed:
                return GitResult(0, f"{tag_target}\trefs/tags/public-demo-local-20260811-v10", "")
            return GitResult(2, "", "remote tag missing")
        return GitResult(0, "", "")

    return run


def _reader(texts=None):
    values = texts or BASE_TEXT

    def read(path):
        return values[path]

    return read


def test_completion_audit_passes_local_ready_with_external_pending():
    report = run_audit(
        expected_branch="codex/public-demo-20260810",
        baseline_tag="public-demo-local-20260811-v10",
        git=_fake_git(),
        read_text=_reader(),
    )

    assert report["summary"]["local_ready"] is True
    assert report["summary"]["public_complete"] is False
    assert report["summary"]["pending_external_count"] > 0
    pending = {check["name"] for check in report["checks"] if check["status"] == "pending_external"}
    assert "display branch push" not in pending
    passed = {check["name"] for check in report["checks"] if check["status"] == "pass"}
    assert "display branch push" in passed


def test_completion_audit_keeps_push_pending_when_remote_refs_are_missing():
    report = run_audit(
        expected_branch="codex/public-demo-20260810",
        baseline_tag="public-demo-local-20260811-v10",
        git=_fake_git(remote_pushed=False),
        read_text=_reader(),
    )

    pending = {check["name"] for check in report["checks"] if check["status"] == "pending_external"}
    assert "display branch push" in pending


def test_completion_audit_fails_missing_required_artifact():
    files = set(REQUIRED_TRACKED_FILES)
    files.remove("frontend/vercel.json")

    report = run_audit(
        expected_branch="codex/public-demo-20260810",
        baseline_tag="public-demo-local-20260811-v10",
        git=_fake_git(files=files),
        read_text=_reader(),
    )

    failed = {check["name"] for check in report["checks"] if check["status"] == "fail"}
    assert "required demo artifacts tracked" in failed
    assert report["summary"]["local_ready"] is False


def test_completion_audit_fails_dirty_worktree():
    report = run_audit(
        expected_branch="codex/public-demo-20260810",
        baseline_tag="public-demo-local-20260811-v10",
        git=_fake_git(dirty=" M README.md"),
        read_text=_reader(),
    )

    failed = {check["name"] for check in report["checks"] if check["status"] == "fail"}
    assert "clean worktree" in failed
    assert report["summary"]["local_ready"] is False


def test_completion_audit_fails_when_debug_or_generated_file_is_tracked():
    files = set(REQUIRED_TRACKED_FILES)
    files.add("frontend/test-output.txt")

    report = run_audit(
        expected_branch="codex/public-demo-20260810",
        baseline_tag="public-demo-local-20260811-v10",
        git=_fake_git(files=files),
        read_text=_reader(),
    )

    failed = {check["name"] for check in report["checks"] if check["status"] == "fail"}
    assert "debug/generated public-demo files" in failed
    assert report["summary"]["local_ready"] is False


def test_completion_audit_fails_when_runtime_artifact_is_reachable_in_history():
    def git(args):
        key = tuple(args)
        if key == ("rev-list", "--objects", "HEAD"):
            return GitResult(0, "abc123 backend/data/agentx.db", "")
        return _fake_git()(args)

    report = run_audit(
        expected_branch="codex/public-demo-20260810",
        baseline_tag="public-demo-local-20260811-v10",
        git=git,
        read_text=_reader(),
    )

    failed = {check["name"] for check in report["checks"] if check["status"] == "fail"}
    assert "runtime artifact history" in failed
    assert report["summary"]["local_ready"] is False


def test_completion_audit_fails_when_render_template_is_unsafe():
    texts = {
        **BASE_TEXT,
        "deploy/render.example.yaml": BASE_TEXT["deploy/render.example.yaml"].replace(
            'value: "false"', 'value: "true"'
        ),
    }

    report = run_audit(
        expected_branch="codex/public-demo-20260810",
        baseline_tag="public-demo-local-20260811-v10",
        git=_fake_git(),
        read_text=_reader(texts),
    )

    failed = {check["name"] for check in report["checks"] if check["status"] == "fail"}
    assert "deployment template: Render" in failed
    assert report["summary"]["local_ready"] is False


def test_completion_audit_fails_when_vercel_template_is_invalid():
    texts = {**BASE_TEXT, "frontend/vercel.json": '{"framework":"vite","buildCommand":"npm run build"}'}

    report = run_audit(
        expected_branch="codex/public-demo-20260810",
        baseline_tag="public-demo-local-20260811-v10",
        git=_fake_git(),
        read_text=_reader(texts),
    )

    failed = {check["name"] for check in report["checks"] if check["status"] == "fail"}
    assert "deployment template: Vercel" in failed
    assert report["summary"]["local_ready"] is False


