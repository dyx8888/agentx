import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tests" / "performance" / "start_docker_public_demo_runtime.ps1"
OVERLAY = ROOT / "backend" / "docker-compose.full-smoke.yml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _docker_invocations(script: str) -> list[tuple[str, ...]]:
    pattern = re.compile(r'Invoke-AllowedDocker\s+"docker"\s+@\((.*?)\)', re.DOTALL)
    invocations: list[tuple[str, ...]] = []
    for raw_args in pattern.findall(script):
        tokens = re.findall(r'"([^"]+)"|(\$ComposeFile|\$OverlayFile)', raw_args)
        normalized = tuple(quoted or variable for quoted, variable in tokens)
        invocations.append(normalized)
    return invocations


def test_public_demo_docker_precheck_allows_only_safe_config_commands():
    script = _read(SCRIPT)

    invocations = _docker_invocations(script)

    assert invocations[:3] == [
        ("--version",),
        ("compose", "version"),
        ("compose", "-f", "$ComposeFile", "config", "--services"),
    ]
    assert ("compose", "-f", "$ComposeFile", "-f", "$OverlayFile", "config", "--services") in invocations
    forbidden = {"up", "build", "pull", "down", "prune"}
    for invocation in invocations:
        assert forbidden.isdisjoint(invocation)
        if "compose" in invocation:
            assert "config" in invocation or "version" in invocation


def test_public_demo_planonly_returns_before_docker_commands():
    script = _read(SCRIPT)

    planonly_index = script.index("if ($PlanOnly)")
    first_docker_index = script.index('Invoke-AllowedDocker "docker"')

    assert planonly_index < first_docker_index
    assert "PlanOnly set; no docker command was executed." in script


def test_public_demo_docker_precheck_reports_env_files_without_reading_them():
    script = _read(SCRIPT)

    for expected in [
        "backend/.env",
        ".env",
        "frontend/.env.production",
        "frontend/.env.local",
    ]:
        assert expected in script

    assert "Test-Path" in script
    assert "Get-Content" not in script
    assert "ReadAllText" not in script
    assert "dotenv" not in script.lower()


def test_public_demo_docker_precheck_prints_compose_plan_boundaries():
    script = _read(SCRIPT)

    for expected in [
        "default_services",
        "published_ports",
        "named_volumes",
        "bind_mounts",
        "backend/.env -> /app/.env:ro",
        "heavy_services",
        "milvus",
        "etcd",
        "minio",
        "postgres",
        "redis",
        "apt-get",
        "pip install",
        "npm ci",
        "embedding model artifacts",
    ]:
        assert expected in script


def test_public_demo_docker_precheck_supports_overlay_config_parse():
    script = _read(SCRIPT)

    assert "CheckOverlay" in script
    assert "backend/docker-compose.full-smoke.yml" in script
    assert '("compose", "-f", $ComposeFile, "-f", $OverlayFile, "config", "--services")' in script
    assert "overlay_config_check" in script


def test_public_demo_full_smoke_overlay_uses_tmpfs_for_heavy_state():
    overlay = _read(OVERLAY)

    assert "target: /etcd" in overlay
    assert "target: /var/lib/milvus" in overlay
    assert overlay.count("type: tmpfs") >= 2
    assert "VECTOR_DB=milvus" in overlay
    assert "MILVUS_HOST=milvus" in overlay


def test_public_demo_docker_files_do_not_embed_real_credentials():
    combined = "\n".join([_read(SCRIPT), _read(OVERLAY)])

    disallowed_patterns = [
        r"AKIA[0-9A-Z]{16}",
        r"AIza[0-9A-Za-z_-]{35}",
        r"ghp_[0-9A-Za-z]{36}",
        r"sk-[A-Za-z0-9_-]{16,}",
        r"xox[baprs]-[0-9A-Za-z-]{10,}",
        r"Authorization\s*:",
        r"Bearer\s+[A-Za-z0-9._-]+",
        r"-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----",
    ]
    for pattern in disallowed_patterns:
        assert not re.search(pattern, combined)

    assert "TOKENRHYTHM" not in combined
    assert "OPENAI_API_KEY" not in combined
    assert "DEEPSEEK_API_KEY" not in combined
