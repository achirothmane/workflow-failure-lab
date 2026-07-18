"""B2 vertical-slice tests: one per certainty term (ADR-0001).

Each test runs the production path parse → analyze → retry_policy; no rule is
re-implemented here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from workflow_failure_lab.analysis import analyze
from workflow_failure_lab.domain import Classification
from workflow_failure_lab.parsing import load_execution
from workflow_failure_lab.reporting import render_report
from workflow_failure_lab.retry_policy import decide

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _write(tmp_path: Path, payload: dict[str, Any]) -> Path:
    file = tmp_path / "execution.json"
    file.write_text(json.dumps(payload), encoding="utf-8")
    return file


def test_succeeded_execution_permits_no_retry(tmp_path: Path) -> None:
    payload = {
        "execution": {
            "id": "exec-1",
            "workflow_name": "nightly-export",
            "started_at": "2026-07-17T01:00:00Z",
            "finished_at": "2026-07-17T01:05:00Z",
            "status": "succeeded",
        },
        "steps": [
            {
                "id": "step-1",
                "name": "export-rows",
                "started_at": "2026-07-17T01:00:00Z",
                "finished_at": "2026-07-17T01:04:00Z",
                "status": "succeeded",
                "attempt": 1,
            },
            {
                "id": "step-2",
                "name": "upload-file",
                "started_at": "2026-07-17T01:04:00Z",
                "finished_at": "2026-07-17T01:05:00Z",
                "status": "completed",
                "attempt": 1,
            },
        ],
    }

    result = analyze(load_execution(_write(tmp_path, payload)))
    decision = decide(result.classification)

    assert result.classification is Classification.SUCCEEDED
    assert result.evidence
    assert decision.retry_permitted is False
    assert decision.reconciliation_required is False


def test_failed_confirmed_execution_permits_retry(tmp_path: Path) -> None:
    payload = {
        "execution": {
            "id": "exec-2",
            "workflow_name": "nightly-export",
            "started_at": "2026-07-17T01:00:00Z",
            "finished_at": "2026-07-17T01:02:00Z",
            "status": "failed",
        },
        "steps": [
            {
                "id": "step-1",
                "name": "export-rows",
                "started_at": "2026-07-17T01:00:00Z",
                "finished_at": "2026-07-17T01:01:00Z",
                "status": "succeeded",
                "attempt": 1,
            },
            {
                "id": "step-2",
                "name": "upload-file",
                "started_at": "2026-07-17T01:01:00Z",
                "finished_at": "2026-07-17T01:02:00Z",
                "status": "failed",
                "attempt": 1,
                "error": {"message": "destination bucket does not exist", "kind": "config"},
            },
        ],
    }

    result = analyze(load_execution(_write(tmp_path, payload)))
    decision = decide(result.classification)

    assert result.classification is Classification.FAILED_CONFIRMED
    assert any("upload-file" in item.source for item in result.evidence)
    assert decision.retry_permitted is True
    assert decision.reconciliation_required is False


def test_payment_timeout_example_is_indeterminate() -> None:
    execution = load_execution(EXAMPLES_DIR / "payment-timeout.json")

    result = analyze(execution)
    decision = decide(result.classification)
    report = render_report(execution, result, decision)

    assert result.classification is Classification.INDETERMINATE
    assert decision.retry_permitted is False
    assert decision.reconciliation_required is True
    assert "INDETERMINATE" in report
    assert "Retry: forbidden" in report
    assert "Reconciliation: required" in report
