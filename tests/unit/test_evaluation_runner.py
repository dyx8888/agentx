import json
import subprocess
import sys
from pathlib import Path


def test_expand_message_supports_compact_long_input_case():
    repo_root = Path(__file__).resolve().parents[2]
    with (repo_root / "tests/evaluation/cases/ben.json").open(encoding="utf-8") as file:
        cases = json.load(file)["cases"]
    case = next(
        item for item in cases if item["scenario"] == "error_extremely_long_input"
    )

    message = case["message"] * case["message_repeat"]

    assert message == "A" * 20000


def test_all_evaluation_case_files_are_valid():
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "tests.evaluation.runner", "--validate-cases"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Validated 40 evaluation cases." in result.stdout
