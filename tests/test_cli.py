"""B4 CLI-contract tests: exercise the real command through subprocess.

Only the CLI contract is asserted here — exit codes, stream separation,
determinism. What each example *means* (classification, evidence, retry
decision) is already covered by tests/test_examples.py and is not repeated.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"

VALID_EXAMPLES = [
    "successful-execution.json",
    "confirmed-api-rejection.json",
    "payment-timeout.json",
    "duplicate-retry-risk.json",
]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "workflow_failure_lab", *args],
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("example", VALID_EXAMPLES)
def test_report_on_valid_example_exits_zero(example: str) -> None:
    completed = run_cli("report", str(EXAMPLES_DIR / example))

    assert completed.returncode == 0
    assert completed.stdout.startswith("# Incident Report:")
    assert completed.stderr == ""


def test_report_output_is_deterministic() -> None:
    path = str(EXAMPLES_DIR / "payment-timeout.json")

    first = run_cli("report", path)
    second = run_cli("report", path)

    assert first.returncode == 0
    assert second.returncode == 0
    assert first.stdout == second.stdout


def test_report_on_malformed_input_exits_three() -> None:
    completed = run_cli("report", str(EXAMPLES_DIR / "malformed-execution.json"))

    assert completed.returncode == 3
    assert completed.stdout == ""
    assert "error:" in completed.stderr
    assert "failed schema validation" in completed.stderr


def test_report_on_missing_file_exits_three(tmp_path: Path) -> None:
    completed = run_cli("report", str(tmp_path / "does-not-exist.json"))

    assert completed.returncode == 3
    assert completed.stdout == ""
    assert "error:" in completed.stderr


def test_no_arguments_is_a_usage_error() -> None:
    completed = run_cli()

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "usage:" in completed.stderr


def test_unknown_subcommand_is_a_usage_error() -> None:
    completed = run_cli("analyze")

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "usage:" in completed.stderr
