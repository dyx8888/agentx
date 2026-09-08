import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILDER_PATH = PROJECT_ROOT / "browser-extension" / "agentx-connector" / "tools" / "build_deployment_manifest.py"
SOURCE_MANIFEST = PROJECT_ROOT / "browser-extension" / "agentx-connector" / "manifest.json"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_deployment_manifest", BUILDER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_manifest_uses_exact_https_backend_permission():
    builder = _load_builder()
    source = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))

    manifest = builder.build_manifest(source, "https://api-staging.example.com/path/ignored")

    assert manifest["host_permissions"] == ["https://api-staging.example.com/*"]
    assert "https://*/*" in manifest["content_scripts"][0]["matches"]
    assert "https://*/*" in manifest["web_accessible_resources"][0]["matches"]
    assert "https://*/*" not in manifest["host_permissions"]
    assert "http://localhost/*" not in manifest["host_permissions"]


@pytest.mark.parametrize(
    "backend_url",
    [
        "http://api-staging.example.com",
        "https://user:pass@api-staging.example.com",
        "https://api-staging.example.com?token=secret",
        "https://api-staging.example.com#fragment",
        "not-a-url",
    ],
)
def test_build_manifest_rejects_unsafe_backend_urls(backend_url):
    builder = _load_builder()
    source = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))

    with pytest.raises(ValueError):
        builder.build_manifest(source, backend_url)


def test_build_manifest_allows_local_http_only_with_explicit_flag():
    builder = _load_builder()
    source = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))

    manifest = builder.build_manifest(source, "http://127.0.0.1:8000", allow_http_local=True)

    assert manifest["host_permissions"] == ["http://127.0.0.1:8000/*"]


def test_builder_cli_writes_manifest_without_mutating_source(tmp_path):
    out = tmp_path / "manifest.json"
    before = SOURCE_MANIFEST.read_text(encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(BUILDER_PATH),
            "--backend",
            "https://api-staging.example.com",
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "backend permission: https://api-staging.example.com/*" in result.stdout
    assert SOURCE_MANIFEST.read_text(encoding="utf-8") == before
    generated = json.loads(out.read_text(encoding="utf-8"))
    assert generated["host_permissions"] == ["https://api-staging.example.com/*"]
