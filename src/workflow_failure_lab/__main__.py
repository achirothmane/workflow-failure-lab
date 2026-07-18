"""Command-line interface for the B4 contract.

Wires the processing path in the fixed order:
load_execution → analyze → decide → render_report → stdout.

Exit codes:
  0 — report produced (classification never affects the exit code)
  1 — internal error: uncaught exception, Python's default behavior
  2 — usage error: argparse's default behavior
  3 — invalid input: parsing.InputError, reported on stderr
"""

from __future__ import annotations

import argparse
import sys

from workflow_failure_lab.analysis import analyze
from workflow_failure_lab.parsing import InputError, load_execution
from workflow_failure_lab.reporting import render_report
from workflow_failure_lab.retry_policy import decide


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m workflow_failure_lab",
        description=(
            "Analyze one workflow execution file and print a Markdown "
            "incident report."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    report = subparsers.add_parser(
        "report", help="render an incident report for one execution JSON file"
    )
    report.add_argument("path", help="path to the execution JSON file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        execution = load_execution(args.path)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    result = analyze(execution)
    decision = decide(result.classification)
    print(render_report(execution, result, decision), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
