from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_POSITIVE_INT_RE = re.compile(r"^[1-9][0-9]*$")


def _field(body: str, heading: str) -> str:
    pattern = re.compile(
        rf"(?ms)^### {re.escape(heading)}\s*\n(.*?)(?=^### |\Z)"
    )
    match = pattern.search(body)
    if not match:
        return ""
    value = match.group(1).strip()
    if value in {"_No response_", "No response"}:
        return ""
    return value


def parse_request(event: dict) -> tuple[bool, str, str, str, str]:
    issue = event.get("issue") or {}
    body = str(issue.get("body") or "")
    repository = _field(body, "Public repository")
    run_id = _field(body, "Workflow run ID")
    run_attempt = _field(body, "Run attempt (optional)")

    if not _REPOSITORY_RE.fullmatch(repository):
        return False, "", "", "", "Repository must use owner/repo form."
    if not _POSITIVE_INT_RE.fullmatch(run_id):
        return False, "", "", "", "Workflow run ID must be a positive integer."
    if run_attempt and not _POSITIVE_INT_RE.fullmatch(run_attempt):
        return False, "", "", "", "Run attempt must be empty or a positive integer."

    return True, repository, run_id, run_attempt, ""


def _write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        print(f"{name}={value}")
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: parse_public_run_request.py EVENT_JSON", file=sys.stderr)
        return 2

    event = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    valid, repository, run_id, run_attempt, error = parse_request(event)
    _write_output("valid", "true" if valid else "false")
    _write_output("repository", repository)
    _write_output("run-id", run_id)
    _write_output("run-attempt", run_attempt)
    _write_output("error", error)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
