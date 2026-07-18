"""B3 example-corpus tests: each example file goes through the production path
parse → analyze → retry_policy; no business rule is re-implemented here.

payment-timeout.json keeps its dedicated test in test_vertical_slice.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from workflow_failure_lab.analysis import analyze
from workflow_failure_lab.domain import Classification
from workflow_failure_lab.parsing import InputError, load_execution
from workflow_failure_lab.reporting import render_report
from workflow_failure_lab.retry_policy import decide

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def test_successful_execution_example() -> None:
    execution = load_execution(EXAMPLES_DIR / "successful-execution.json")

    result = analyze(execution)
    decision = decide(result.classification)
    report = render_report(execution, result, decision)

    assert result.classification is Classification.SUCCEEDED
    assert result.evidence
    assert decision.retry_permitted is False
    assert decision.reconciliation_required is False
    assert "SUCCEEDED" in report
    assert "Retry: forbidden" in report
    assert "Reconciliation: not required" in report


def test_confirmed_api_rejection_example() -> None:
    execution = load_execution(EXAMPLES_DIR / "confirmed-api-rejection.json")

    result = analyze(execution)
    decision = decide(result.classification)
    report = render_report(execution, result, decision)

    assert result.classification is Classification.FAILED_CONFIRMED
    assert any("charge-card" in item.source for item in result.evidence)
    assert decision.retry_permitted is True
    assert decision.reconciliation_required is False
    assert "FAILED_CONFIRMED" in report
    assert "Retry: permitted" in report
    assert "Reconciliation: not required" in report


def test_malformed_execution_example_raises_input_error() -> None:
    with pytest.raises(InputError) as excinfo:
        load_execution(EXAMPLES_DIR / "malformed-execution.json")

    message = str(excinfo.value)
    assert "failed schema validation" in message
    assert "status" in message


def test_duplicate_retry_risk_example() -> None:
    execution = load_execution(EXAMPLES_DIR / "duplicate-retry-risk.json")

    result = analyze(execution)
    decision = decide(result.classification)
    report = render_report(execution, result, decision)

    assert result.classification is Classification.INDETERMINATE
    assert decision.retry_permitted is False
    assert decision.reconciliation_required is True

    side_effect_items = [
        item for item in result.evidence if item.source.endswith(".side_effect")
    ]
    assert side_effect_items
    assert any("duplicating" in item.detail for item in side_effect_items)

    assert "INDETERMINATE" in report
    assert "Retry: forbidden" in report
    assert "Reconciliation: required" in report
