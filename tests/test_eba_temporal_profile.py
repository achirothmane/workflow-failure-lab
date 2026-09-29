from __future__ import annotations

import json
from pathlib import Path

import pytest

from ci_assumption_profile import build_ci_retry_assumption_state
from ci_authority_profile import build_ci_authority_grant
from eba_integration_contract import (
    ContractViolation,
    _with_integrity,
    build_ci_action_request,
    build_decision_artifact,
    ensure_decision_allows_request,
)

VECTORS = json.loads(
    (Path(__file__).parents[1] / "conformance" / "eba-temporal-v1.json").read_text(
        encoding="utf-8"
    )
)


def _request(created_at: str = "2026-09-28T11:55:00Z"):
    return build_ci_action_request(
        repository="achirothmane/workflow-failure-lab",
        run_id=123,
        run_attempt=1,
        head_sha="abc123",
        workflow_id=77,
        created_at=created_at,
    )


def _source(*, fresh_until=None):
    return {
        "schema_version": "ci-retry-gate.evidence-decision.v1",
        "decision": "ALLOW",
        "evidence_status": "SUFFICIENT",
        "confidence": "high",
        "observed_at": "2026-09-28T11:54:00Z",
        "fresh_until": fresh_until,
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


def _bundle(*, fresh_until=None):
    request = _request()
    source = _source(fresh_until=fresh_until)
    assumption = build_ci_retry_assumption_state(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="a" * 64,
        created_at="2026-09-28T11:55:00Z",
    )
    authority = build_ci_authority_grant(
        action_request=request,
        created_at="2026-09-28T11:55:00Z",
        expires_at="2026-09-28T12:00:00Z",
    )
    decision = build_decision_artifact(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="a" * 64,
        assumption_states=[assumption],
        authority_grant=authority,
        require_authority=True,
        created_at="2026-09-28T11:55:00Z",
    )
    return request, assumption, authority, decision


def test_shared_temporal_vector_profile_is_versioned():
    assert VECTORS["profile"] == "eba.temporal/v1"
    ids = {case["id"] for case in VECTORS["cases"]}
    assert {
        "T01-assumption-before-expiry",
        "T02-assumption-at-expiry",
        "T06-authority-at-expiry",
        "T08-future-observation",
        "T09-budget-at-expiry",
        "T11-equal-instant-offset",
    } <= ids


def test_authority_uses_half_open_expiry_boundary():
    request, assumption, authority, decision = _bundle()
    ensure_decision_allows_request(
        decision,
        request,
        now="2026-09-28T11:59:59Z",
        assumption_states=[assumption],
        authority_grant=authority,
    )
    with pytest.raises(ContractViolation, match="AUTHORITY_EXPIRED"):
        ensure_decision_allows_request(
            decision,
            request,
            now="2026-09-28T12:00:00Z",
            assumption_states=[assumption],
            authority_grant=authority,
        )


def test_assumption_uses_half_open_expiry_boundary():
    request, assumption, authority, decision = _bundle(
        fresh_until="2026-09-28T12:00:00Z"
    )
    ensure_decision_allows_request(
        decision,
        request,
        now="2026-09-28T11:59:59Z",
        assumption_states=[assumption],
        authority_grant=authority,
    )
    with pytest.raises(ContractViolation, match="DECISION_EXPIRED|ASSUMPTION_STALE"):
        ensure_decision_allows_request(
            decision,
            request,
            now="2026-09-28T12:00:00Z",
            assumption_states=[assumption],
            authority_grant=authority,
        )


def test_malformed_assumption_timestamp_is_not_structurally_accepted():
    request, assumption, authority, decision = _bundle()
    malformed = dict(assumption)
    malformed["valid_until"] = 123
    malformed = _with_integrity(malformed)
    with pytest.raises(ContractViolation, match="ASSUMPTION_VALID_UNTIL_INVALID"):
        ensure_decision_allows_request(
            decision,
            request,
            now="2026-09-28T11:56:00Z",
            assumption_states=[malformed],
            authority_grant=authority,
        )


def test_future_checked_assumption_is_rejected():
    request, assumption, authority, decision = _bundle()
    future = dict(assumption)
    future["checked_at"] = "2026-09-28T12:01:00Z"
    future = _with_integrity(future)
    with pytest.raises(ContractViolation, match="ASSUMPTION_CHECKED_AT_FUTURE"):
        ensure_decision_allows_request(
            decision,
            request,
            now="2026-09-28T12:00:00Z",
            assumption_states=[future],
            authority_grant=authority,
        )




def test_equivalent_timezone_offsets_share_the_same_boundary():
    request = build_ci_action_request(
        repository="achirothmane/workflow-failure-lab",
        run_id=123,
        run_attempt=1,
        head_sha="abc123",
        workflow_id=77,
        created_at="2026-09-28T13:55:00+02:00",
    )
    source = _source()
    assumption = build_ci_retry_assumption_state(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="b" * 64,
        created_at="2026-09-28T13:55:00+02:00",
    )
    authority = build_ci_authority_grant(
        action_request=request,
        created_at="2026-09-28T13:55:00+02:00",
        expires_at="2026-09-28T14:00:00+02:00",
    )
    decision = build_decision_artifact(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="b" * 64,
        assumption_states=[assumption],
        authority_grant=authority,
        require_authority=True,
        created_at="2026-09-28T11:55:00Z",
    )
    ensure_decision_allows_request(
        decision,
        request,
        now="2026-09-28T11:59:59Z",
        assumption_states=[assumption],
        authority_grant=authority,
    )
    with pytest.raises(ContractViolation, match="AUTHORITY_EXPIRED"):
        ensure_decision_allows_request(
            decision,
            request,
            now="2026-09-28T12:00:00Z",
            assumption_states=[assumption],
            authority_grant=authority,
        )


def test_authority_expiry_is_finite_by_default():
    request = _request("2026-09-28T11:55:00Z")
    authority = build_ci_authority_grant(
        action_request=request,
        created_at="2026-09-28T11:55:00Z",
    )
    assert authority["expires_at"] == "2026-09-28T12:00:00Z"
