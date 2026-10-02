from __future__ import annotations

import hashlib
import json

import pytest

from decision_record import build_decision_record, seal_decision_record
from eba_integration_contract import RECEIPT_KIND, canonical_json_bytes
from outcome_record import (
    OutcomeRecordError,
    bind_parent_decision_to_attempt,
    build_outcome_record,
    build_reconciliation_record,
    seal_audit_record,
    verify_outcome_record,
    verify_reconciliation_record,
)


def _parent(*, decision: str = "ALLOW") -> dict:
    record = build_decision_record(
        evidence_decision={
            "decision": decision,
            "evidence_status": "SUFFICIENT" if decision == "ALLOW" else "UNKNOWN",
            "reasons": ["test"],
            "scope": {
                "repository": "owner/repo",
                "run_id": 123,
                "run_attempt": 1,
                "head_sha": "abc123",
                "workflow_id": 99,
            },
        },
        evidence_bundle_sha256="a" * 64,
        policy_ref="ci-retry-gate.production.v1",
        authorization_path="POLICY",
        next_action="RERUN_ALLOWED" if decision == "ALLOW" else "INVESTIGATE_FAILURE",
        identities={
            "decision_engine": {
                "raw": "achirothmane/workflow-failure-lab",
                "identity_type": "unknown",
            }
        },
        event_id="evt-parent",
        recorded_at="2026-10-02T01:00:00Z",
    )
    return seal_decision_record(record)


def _run(*, attempt: int = 2, head_sha: str = "abc123") -> dict:
    return {
        "run_attempt": attempt,
        "head_sha": head_sha,
        "workflow_id": 99,
        "status": "completed",
        "conclusion": "success",
    }


def _receipt() -> dict:
    receipt = {
        "kind": RECEIPT_KIND,
        "outcome": "SUCCEEDED",
        "decision_ref": "eba-decision-1",
    }
    digest = hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
    receipt["integrity"] = {"algorithm": "sha256", "digest": digest}
    return receipt


def test_parent_binds_only_to_exact_next_attempt_state() -> None:
    parent = _parent()

    bound, reason = bind_parent_decision_to_attempt(
        parent_decision=parent,
        repository="owner/repo",
        run_id=123,
        current_run=_run(),
        current_attempt=2,
    )
    assert bound is True
    assert reason == "BOUND_TO_NEXT_ATTEMPT"

    bound, reason = bind_parent_decision_to_attempt(
        parent_decision=parent,
        repository="owner/repo",
        run_id=123,
        current_run=_run(head_sha="different"),
        current_attempt=2,
    )
    assert bound is False
    assert "head_sha" in reason


def test_confirmed_gate_dispatch_reconciles_recovery() -> None:
    parent = _parent()
    outcome = build_outcome_record(
        parent_decision=parent,
        current_run=_run(),
        previous_jobs=[{"name": "unit-tests", "conclusion": "failure"}],
        current_jobs=[{"name": "unit-tests", "conclusion": "success"}],
        execution_receipt=_receipt(),
        event_id="evt-outcome",
        recorded_at="2026-10-02T02:00:00Z",
    )
    outcome = seal_audit_record(outcome)
    verify_outcome_record(outcome)

    reconciliation = build_reconciliation_record(
        parent_decision=parent,
        outcome_record=outcome,
        event_id="evt-reconcile",
        recorded_at="2026-10-02T02:00:01Z",
    )
    reconciliation = seal_audit_record(reconciliation)
    verify_reconciliation_record(reconciliation)

    assert outcome["observation"]["effect_attribution"] == "GATE_DISPATCH_CONFIRMED"
    assert outcome["observation"]["recovered_jobs"] == ["unit-tests"]
    assert reconciliation["status"] == "RECOVERED_AFTER_RERUN"


def test_block_with_later_attempt_is_observed_without_claiming_block_wrong() -> None:
    parent = _parent(decision="BLOCK")
    outcome = build_outcome_record(
        parent_decision=parent,
        current_run=_run(),
        previous_jobs=[{"name": "unit-tests", "conclusion": "failure"}],
        current_jobs=[{"name": "unit-tests", "conclusion": "success"}],
        execution_receipt=None,
        event_id="evt-outcome",
        recorded_at="2026-10-02T02:00:00Z",
    )
    outcome = seal_audit_record(outcome)
    reconciliation = build_reconciliation_record(
        parent_decision=parent,
        outcome_record=outcome,
        event_id="evt-reconcile",
        recorded_at="2026-10-02T02:00:01Z",
    )
    reconciliation = seal_audit_record(reconciliation)

    assert reconciliation["status"] == "SUBSEQUENT_ATTEMPT_AFTER_BLOCK"
    assert "does not prove" in reconciliation["reason"]


def test_outcome_tamper_is_detected() -> None:
    outcome = build_outcome_record(
        parent_decision=_parent(),
        current_run=_run(),
        previous_jobs=[{"name": "unit-tests", "conclusion": "failure"}],
        current_jobs=[{"name": "unit-tests", "conclusion": "success"}],
        execution_receipt=_receipt(),
        event_id="evt-outcome",
        recorded_at="2026-10-02T02:00:00Z",
    )
    sealed = seal_audit_record(outcome)
    tampered = json.loads(json.dumps(sealed))
    tampered["observation"]["workflow_conclusion"] = "failure"

    with pytest.raises(OutcomeRecordError, match="SHA-256 mismatch"):
        verify_outcome_record(tampered)
