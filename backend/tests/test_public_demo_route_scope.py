import subprocess
import sys
from pathlib import Path


def test_public_demo_production_disables_evolution_routes_by_default():
    root = Path(__file__).resolve().parents[2]
    code = (
        "import os, sys; "
        "os.environ.update({"
        "'ENVIRONMENT':'production', "
        "'ENV':'prod', "
        "'COOKIE_SECURE':'true', "
        "'CORS_ORIGINS':'https://demo.example.com', "
        "'FRONTEND_URL':'https://demo.example.com', "
        "'JWT_SECRET_KEY':'test-secret', "
        "'ENABLE_PUBLIC_DOCS':'false', "
        "'ENABLE_EVOLUTION_API':'false'"
        "}); "
        "sys.path.insert(0, 'backend'); "
        "import app.main as main; "
        "routes = sorted(getattr(route, 'path', '') for route in main.app.routes); "
        "blocked = [path for path in routes if 'evolution' in path.lower() or 'lora' in path.lower()]; "
        "print('\\n'.join(blocked)); "
        "raise SystemExit(1 if blocked else 0)"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
