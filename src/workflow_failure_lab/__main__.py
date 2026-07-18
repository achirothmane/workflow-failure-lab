"""Minimal module entry point for the B2 vertical slice.

Wires: parse → validate → domain model → analyze → retry_policy → render.
The full CLI (subcommands, documented exit codes) is deferred to B4.
"""

from __future__ import annotations

import sys

from workflow_failure_lab.analysis import analyze
from workflow_failure_lab.parsing import InputError, load_execution
from workflow_failure_lab.reporting import render_report
from workflow_failure_lab.retry_policy import decide


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        raise SystemExit("usage: python -m workflow_failure_lab <execution.json>")

    try:
        execution = load_execution(args[0])
    except InputError as exc:
        raise SystemExit(f"error: {exc}") from exc

    result = analyze(execution)
    decision = decide(result.classification)
    print(render_report(execution, result, decision), end="")


if __name__ == "__main__":
    main()
