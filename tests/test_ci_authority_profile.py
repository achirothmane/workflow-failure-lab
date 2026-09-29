from __future__ import annotations

import copy

import pytest

from ci_assumption_profile import build_ci_retry_assumption_state
from ci_authority_profile import (
    AuthorityProfileError,
    build_ci_authority_grant,
)
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


def _source():
    return {
        "schema_version": "ci-retry-gate.evidence-decision.v1",
        "decision": "ALLOW",
        "evidence_status": "SUFFICIENT",
        "confidence": "high",
        "fresh_until": None,
        "scope": {
            "repository": "achirothmane/workflow-failure-lab",
            "run_id": 123,
            "run_attempt": 1,
            "head_sha": "abc123",
            "workflow_id": 77,
        },
        "reasons": ["Evidence sufficient."],
        "contradictions": [],
    }


def _assumption(request, source):
    return build_ci_retry_assumption_state(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="a" * 64,
        created_at=NOW,
    )


def test_profile_emits_agent_action_guard_authority_grant():
    request = _request()
    grant = build_ci_authority_grant(action_request=request, created_at=NOW)

    assert grant["kind"] == "AuthorityGrant"
    assert grant["producer"] == "agent-action-guard/ci-retry-profile"
    assert grant["principal"]["id"] == "ci-retry-gate"
    assert grant["allowed_actions"][0]["operation"] == "rerun_failed_jobs"
    assert grant["resource_scope"] == [
        "github://achirothmane/workflow-failure-lab/actions/runs/123"
    ]
    assert grant["matched_allow_rule_ids"] == [
        "allow-ci-retry-rerun-failed-jobs"
    ]


def test_profile_rejects_wrong_principal():
    request = _request()
    request["principal"]["id"] = "other-agent"
    with pytest.raises(AuthorityProfileError, match="PRINCIPAL"):
        build_ci_authority_grant(action_request=request, created_at=NOW)


def test_profile_rejects_resource_not_bound_to_context():
    request = _request()
    request["action"]["resource"] = "github://other/repo/actions/runs/999"
    with pytest.raises(AuthorityProfileError, match="RESOURCE"):
        build_ci_authority_grant(action_request=request, created_at=NOW)


def test_decision_contains_authority_ref_and_execution_enforces_it():
    request = _request()
    source = _source()
    assumption = _assumption(request, source)
    authority = build_ci_authority_grant(action_request=request, created_at=NOW)

    decision = build_decision_artifact(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="a" * 64,
        assumption_states=[assumption],
        authority_grant=authority,
        require_authority=True,
        created_at=NOW,
    )
    assert decision["basis"]["authority_ref"] == authority["id"]

    ensure_decision_allows_request(
        decision,
        request,
        now=NOW,
        assumption_states=[assumption],
        authority_grant=authority,
    )


def test_missing_authority_artifact_fails_execution_boundary():
    request = _request()
    source = _source()
    assumption = _assumption(request, source)
    authority = build_ci_authority_grant(action_request=request, created_at=NOW)
    decision = build_decision_artifact(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="a" * 64,
        assumption_states=[assumption],
        authority_grant=authority,
        require_authority=True,
        created_at=NOW,
    )

    with pytest.raises(ContractViolation, match="AUTHORITY_REFERENCE_MISSING"):
        ensure_decision_allows_request(
            decision,
            request,
            now=NOW,
            assumption_states=[assumption],
        )


def test_tampered_authority_fails_integrity():
    request = _request()
    source = _source()
    assumption = _assumption(request, source)
    authority = build_ci_authority_grant(action_request=request, created_at=NOW)
    decision = build_decision_artifact(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="a" * 64,
        assumption_states=[assumption],
        authority_grant=authority,
        require_authority=True,
        created_at=NOW,
    )
    tampered = copy.deepcopy(authority)
    tampered["resource_scope"] = ["github://other/repo/actions/runs/999"]

    with pytest.raises(ContractViolation, match="AUTHORITY_INTEGRITY_INVALID"):
        ensure_decision_allows_request(
            decision,
            request,
            now=NOW,
            assumption_states=[assumption],
            authority_grant=tampered,
        )


def test_authority_scope_mismatch_fails_closed():
    request = _request()
    source = _source()
    assumption = _assumption(request, source)
    authority = build_ci_authority_grant(action_request=request, created_at=NOW)
    decision = build_decision_artifact(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="a" * 64,
        assumption_states=[assumption],
        authority_grant=authority,
        require_authority=True,
        created_at=NOW,
    )

    changed = copy.deepcopy(request)
    changed["context"]["run_id"] = 999
    changed["action"]["resource"] = (
        "github://achirothmane/workflow-failure-lab/actions/runs/999"
    )

    with pytest.raises(ContractViolation):
        ensure_decision_allows_request(
            decision,
            changed,
            now=NOW,
            assumption_states=[assumption],
            authority_grant=authority,
        )


def test_require_authority_without_grant_turns_allow_into_block():
    request = _request()
    source = _source()
    assumption = _assumption(request, source)
    decision = build_decision_artifact(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="a" * 64,
        assumption_states=[assumption],
        authority_grant=None,
        require_authority=True,
        created_at=NOW,
    )
    assert decision["decision"] == "BLOCK"
    assert decision["reason_codes"] == ["AUTHORITY_MISSING"]


def test_receipt_revalidates_authority_on_execution():
    request = _request()
    source = _source()
    assumption = _assumption(request, source)
    authority = build_ci_authority_grant(action_request=request, created_at=NOW)
    decision = build_decision_artifact(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="a" * 64,
        assumption_states=[assumption],
        authority_grant=authority,
        require_authority=True,
        created_at=NOW,
    )
    receipt = build_execution_receipt(
        action_request=request,
        decision_artifact=decision,
        assumption_states=[assumption],
        authority_grant=authority,
        rerun_triggered=True,
        created_at=NOW,
    )
    assert receipt["outcome"] == "SUCCEEDED"
