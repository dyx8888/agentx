from tests.performance.public_demo_pre_push_audit import GitResult
from tests.performance.public_demo_pre_push_audit import run_audit


EXPECTED_BRANCH = "codex/public-demo-20260810"
SECRET_SCAN_ARGS = (
    "grep",
    "-n",
    "-I",
    "-E",
    "(AKIA[0-9A-Z]{16})|(AIza[0-9A-Za-z_-]{35})|(xox[baprs]-[0-9A-Za-z-]{10,})|(ghp_[0-9A-Za-z]{36})|(-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----)",
)
PUBLIC_DEMO_BRANCH_ARGS = (
    "grep",
    "-n",
    EXPECTED_BRANCH,
    ".github/workflows/public-demo-quick-gates.yml",
)
PUBLIC_DEMO_DOCKER_ARGS = (
    "grep",
    "-n",
    "-I",
    "-E",
    "docker|compose|down -v|prune|no-cache",
    ".github/workflows/public-demo-quick-gates.yml",
)
LEGACY_BRANCH_ARGS = (
    "grep",
    "-n",
    EXPECTED_BRANCH,
    ".github/workflows/backend-ci.yml",
    ".github/workflows/evaluation.yml",
)


def _fake_git(mapping):
    def run(args):
        key = tuple(args)
        value = mapping.get(key)
        if value is None:
            return GitResult(0, "", "")
        if isinstance(value, GitResult):
            return value
        return GitResult(0, value, "")

    return run


def _base_mapping(overrides=None):
    mapping = {
        ("branch", "--show-current"): EXPECTED_BRANCH,
        ("status", "--porcelain=v1"): "",
        ("rev-parse", "HEAD"): "abc123",
        ("rev-list", "-n", "1", "public-demo-local-20260811-v4"): "abc123",
        ("ls-files",): "README.md\nbackend/app/main.py",
        ("rev-list", "--objects", "HEAD"): "abc123 README.md\nabc124 backend/app/main.py",
        SECRET_SCAN_ARGS: GitResult(1, "", ""),
        ("grep", "-n", "Online demo: not deployed yet.", "README.md"): "README.md:7:- Online demo: not deployed yet.",
        PUBLIC_DEMO_BRANCH_ARGS: ".github/workflows/public-demo-quick-gates.yml:5:      - codex/public-demo-20260810",
        PUBLIC_DEMO_DOCKER_ARGS: GitResult(1, "", ""),
        LEGACY_BRANCH_ARGS: GitResult(1, "", ""),
    }
    if overrides:
        mapping.update(overrides)
    return mapping


def test_pre_push_audit_passes_clean_public_demo_branch():
    git = _fake_git(_base_mapping())

    report = run_audit(
        expected_branch=EXPECTED_BRANCH,
        baseline_tag="public-demo-local-20260811-v4",
        git=git,
    )

    assert report["summary"]["passed"] is True


def test_pre_push_audit_fails_when_tag_does_not_match_head():
    git = _fake_git(
        _base_mapping({("rev-list", "-n", "1", "public-demo-local-20260811-v4"): "def456"})
    )

    report = run_audit(
        expected_branch=EXPECTED_BRANCH,
        baseline_tag="public-demo-local-20260811-v4",
        git=git,
    )

    failed = {check["name"] for check in report["checks"] if not check["passed"]}
    assert "baseline tag points to HEAD" in failed


def test_pre_push_audit_fails_when_runtime_artifact_is_tracked():
    git = _fake_git(
        _base_mapping({("ls-files",): "README.md\nbackend/data/agentx.db"})
    )

    report = run_audit(
        expected_branch=EXPECTED_BRANCH,
        baseline_tag="public-demo-local-20260811-v4",
        git=git,
    )

    failed = {check["name"] for check in report["checks"] if not check["passed"]}
    assert "runtime artifacts not tracked" in failed


def test_pre_push_audit_fails_when_debug_or_generated_file_is_tracked():
    git = _fake_git(
        _base_mapping({("ls-files",): "README.md\nbackend/debug_agent.py"})
    )

    report = run_audit(
        expected_branch=EXPECTED_BRANCH,
        baseline_tag="public-demo-local-20260811-v4",
        git=git,
    )

    failed = {check["name"] for check in report["checks"] if not check["passed"]}
    assert "debug and generated public-demo files not tracked" in failed


def test_pre_push_audit_fails_when_runtime_artifact_is_in_history():
    git = _fake_git(
        _base_mapping({("rev-list", "--objects", "HEAD"): "abc123 backend/data/agentx.db"})
    )

    report = run_audit(
        expected_branch=EXPECTED_BRANCH,
        baseline_tag="public-demo-local-20260811-v4",
        git=git,
    )

    failed = {check["name"] for check in report["checks"] if not check["passed"]}
    assert "runtime artifacts not reachable in branch history" in failed


def test_pre_push_audit_fails_when_public_demo_workflow_uses_docker():
    git = _fake_git(
        _base_mapping(
            {PUBLIC_DEMO_DOCKER_ARGS: ".github/workflows/public-demo-quick-gates.yml:10: docker build ."}
        )
    )

    report = run_audit(
        expected_branch=EXPECTED_BRANCH,
        baseline_tag="public-demo-local-20260811-v4",
        git=git,
    )

    failed = {check["name"] for check in report["checks"] if not check["passed"]}
    assert "public-demo workflow scope" in failed


def test_pre_push_audit_fails_when_legacy_workflow_targets_display_branch():
    git = _fake_git(
        _base_mapping(
            {LEGACY_BRANCH_ARGS: ".github/workflows/backend-ci.yml:20:      - codex/public-demo-20260810"}
        )
    )

    report = run_audit(
        expected_branch=EXPECTED_BRANCH,
        baseline_tag="public-demo-local-20260811-v4",
        git=git,
    )

    failed = {check["name"] for check in report["checks"] if not check["passed"]}
    assert "legacy heavy workflows skip display branch" in failed
