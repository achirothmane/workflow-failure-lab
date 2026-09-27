from __future__ import annotations

import copy

import pytest

from ci_assumption_profile import build_ci_retry_assumption_state
from eba_integration_contract import (
    ContractViolation,
    build_ci_action_request,
    build_decision_artifact,
    build_execution_receipt,
    ensure_decision_allows_request,
)


NOW = "2026-09-27T16:00:00Z"


def _request():
    return build_ci_action_request(
        repository="achirothmane/workflow-failure-lab",
        run_id=123,
        run_attempt=1,
        head_sha="abc123",
        workflow_id=77,
        created_at=NOW,
    )


def _evidence_decision(*, decision="ALLOW", status="SUFFICIENT"):
    return {
        "schema_version": "ci-retry-gate.evidence-decision.v1",
        "decision": decision,
        "evidence_status": status,
        "confidence": "high" if status != "UNKNOWN" else "unknown",
        "fresh_until": None,
        "scope": {
            "repository": "achirothmane/workflow-failure-lab",
            "run_id": 123,
            "run_attempt": 1,
            "head_sha": "abc123",
            "workflow_id": 77,
        },
        "reasons": ["Evidence sufficient." if decision == "ALLOW" else "Evidence insufficient."],
        "contradictions": ["counterexample"] if status == "CONTRADICTED" else [],
    }


def test_profile_emits_valid_assumption_for_sufficient_allow():
    request = _request()
    state = build_ci_retry_assumption_state(
        action_request=request,
        evidence_decision=_evidence_decision(),
        evidence_sha256="a" * 64,
        created_at=NOW,
    )
    assert state["kind"] == "AssumptionState"
    assert state["status"] == "VALID"
    assert state["trace_id"] == request["trace_id"]
    assert state["evidence_refs"] == [f"sha256:{'a' * 64}"]


def test_contradicted_evidence_emits_contradicted_assumption():
    state = build_ci_retry_assumption_state(
        action_request=_request(),
        evidence_decision=_evidence_decision(decision="BLOCK", status="CONTRADICTED"),
        evidence_sha256="b" * 64,
        created_at=NOW,
    )
    assert state["status"] == "CONTRADICTED"
    assert state["invalidation_reasons"] == ["counterexample"]


def test_decision_contains_real_assumption_reference_and_enforces_it():
    request = _request()
    source = _evidence_decision()
    state = build_ci_retry_assumption_state(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="c" * 64,
        created_at=NOW,
    )
    decision = build_decision_artifact(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="c" * 64,
        assumption_states=[state],
        created_at=NOW,
    )

    assert decision["basis"]["assumption_refs"] == [state["id"]]
    ensure_decision_allows_request(decision, request, assumption_states=[state])


def test_missing_assumption_artifact_fails_execution_boundary():
    request = _request()
    source = _evidence_decision()
    state = build_ci_retry_assumption_state(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="d" * 64,
        created_at=NOW,
    )
    decision = build_decision_artifact(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="d" * 64,
        assumption_states=[state],
        created_at=NOW,
    )

    with pytest.raises(ContractViolation, match="ASSUMPTION_REFERENCE_MISSING"):
        ensure_decision_allows_request(decision, request)


def test_tampered_assumption_fails_execution_boundary():
    request = _request()
    source = _evidence_decision()
    state = build_ci_retry_assumption_state(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="e" * 64,
        created_at=NOW,
    )
    decision = build_decision_artifact(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="e" * 64,
        assumption_states=[state],
        created_at=NOW,
    )
    tampered = copy.deepcopy(state)
    tampered["proposition"] = "mutated"

    with pytest.raises(ContractViolation, match="ASSUMPTION_INTEGRITY_INVALID"):
        ensure_decision_allows_request(decision, request, assumption_states=[tampered])


def test_non_valid_assumption_turns_allow_into_block():
    request = _request()
    source = _evidence_decision(decision="ALLOW", status="UNKNOWN")
    state = build_ci_retry_assumption_state(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="f" * 64,
        created_at=NOW,
    )
    decision = build_decision_artifact(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="f" * 64,
        assumption_states=[state],
        created_at=NOW,
    )
    assert decision["decision"] == "BLOCK"
    assert decision["reason_codes"] == ["ASSUMPTION_INVALID"]


def test_receipt_revalidates_assumption_when_execution_occurred():
    request = _request()
    source = _evidence_decision()
    state = build_ci_retry_assumption_state(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="1" * 64,
        created_at=NOW,
    )
    decision = build_decision_artifact(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="1" * 64,
        assumption_states=[state],
        created_at=NOW,
    )
    receipt = build_execution_receipt(
        action_request=request,
        decision_artifact=decision,
        assumption_states=[state],
        rerun_triggered=True,
        created_at=NOW,
    )
    assert receipt["decision_ref"] == decision["id"]
    assert receipt["outcome"] == "SUCCEEDED"
