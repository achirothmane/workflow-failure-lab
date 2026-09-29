from __future__ import annotations

import copy

import pytest

from eba_integration_contract import (
    CONTRACT_VERSION,
    ContractViolation,
    action_digest,
    build_ci_action_request,
    build_decision_artifact,
    build_execution_receipt,
    ensure_decision_allows_request,
)


def _request():
    return build_ci_action_request(
        repository="achirothmane/workflow-failure-lab",
        run_id=123,
        run_attempt=1,
        head_sha="abc123",
        workflow_id=77,
        created_at="2026-09-27T16:00:00Z",
    )


def _legacy(decision="ALLOW", reason="Evidence sufficient."):
    return {
        "schema_version": "ci-retry-gate.evidence-decision.v1",
        "decision": decision,
        "evidence_status": "SUFFICIENT" if decision == "ALLOW" else "UNKNOWN",
        "confidence": "high" if decision == "ALLOW" else "unknown",
        "fresh_until": None,
        "scope": {
            "repository": "achirothmane/workflow-failure-lab",
            "run_id": 123,
            "run_attempt": 1,
            "head_sha": "abc123",
            "workflow_id": 77,
        },
        "reasons": [reason],
    }


def test_action_digest_is_stable_and_context_bound():
    request = _request()
    assert request["contract_version"] == CONTRACT_VERSION
    first = action_digest(request)
    assert first == action_digest(copy.deepcopy(request))

    mutated = copy.deepcopy(request)
    mutated["context"]["head_sha"] = "different"
    assert action_digest(mutated) != first


def test_allow_decision_authorizes_exact_request():
    request = _request()
    decision = build_decision_artifact(
        action_request=request,
        evidence_decision=_legacy(),
        evidence_sha256="f" * 64,
        created_at="2026-09-27T16:00:01Z",
    )
    ensure_decision_allows_request(decision, request, now="2026-09-27T16:00:02Z")
    assert decision["decision"] == "ALLOW"
    assert decision["reason_codes"] == ["ALL_REQUIRED_GATES_SATISFIED"]


def test_block_decision_fails_closed():
    request = _request()
    decision = build_decision_artifact(
        action_request=request,
        evidence_decision=_legacy("BLOCK", "EVIDENCE_MISSING: no causal evidence."),
        evidence_sha256="e" * 64,
        created_at="2026-09-27T16:00:01Z",
    )
    with pytest.raises(ContractViolation, match="ALLOW"):
        ensure_decision_allows_request(decision, request, now="2026-09-27T16:00:02Z")
    assert decision["reason_codes"] == ["EVIDENCE_MISSING"]


def test_mutation_after_decision_is_rejected():
    request = _request()
    decision = build_decision_artifact(
        action_request=request,
        evidence_decision=_legacy(),
        evidence_sha256="d" * 64,
        created_at="2026-09-27T16:00:01Z",
    )

    mutated = copy.deepcopy(request)
    mutated["action"]["resource"] += "?other=true"

    with pytest.raises(ContractViolation):
        ensure_decision_allows_request(decision, mutated)


def test_receipt_is_bound_to_decision_and_request():
    request = _request()
    decision = build_decision_artifact(
        action_request=request,
        evidence_decision=_legacy(),
        evidence_sha256="c" * 64,
        created_at="2026-09-27T16:00:01Z",
    )
    receipt = build_execution_receipt(
        action_request=request,
        decision_artifact=decision,
        rerun_triggered=True,
        created_at="2026-09-27T16:00:02Z",
    )

    assert receipt["decision_ref"] == decision["id"]
    assert receipt["request_ref"] == request["id"]
    assert receipt["action_digest"] == decision["action_digest"]
    assert receipt["outcome"] == "SUCCEEDED"
    assert receipt["resource_changes"][0]["result"] == "dispatch-accepted"


def test_allow_with_mismatched_evidence_scope_becomes_block():
    request = _request()
    legacy = _legacy()
    legacy["scope"]["head_sha"] = "other-sha"

    decision = build_decision_artifact(
        action_request=request,
        evidence_decision=legacy,
        evidence_sha256="b" * 64,
        created_at="2026-09-27T16:00:01Z",
    )

    assert decision["decision"] == "BLOCK"
    assert decision["reason_codes"] == ["CONTEXT_MISMATCH"]
    with pytest.raises(ContractViolation, match="ALLOW"):
        ensure_decision_allows_request(decision, request, now="2026-09-27T16:00:02Z")
