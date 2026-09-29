from __future__ import annotations

import copy
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

NOW = "2026-09-29T20:00:00Z"
VECTORS = json.loads(
    (Path(__file__).parents[1] / "conformance" / "eba-context-v1.json").read_text(
        encoding="utf-8"
    )
)


def _request(repository: str = "achirothmane/workflow-failure-lab"):
    return build_ci_action_request(
        repository=repository,
        run_id=123,
        run_attempt=1,
        head_sha="abc123",
        workflow_id=77,
        created_at=NOW,
    )


def _source(repository: str = "achirothmane/workflow-failure-lab"):
    return {
        "schema_version": "ci-retry-gate.evidence-decision.v1",
        "decision": "ALLOW",
        "evidence_status": "SUFFICIENT",
        "confidence": "high",
        "fresh_until": None,
        "scope": {
            "repository": repository,
            "run_id": 123,
            "run_attempt": 1,
            "head_sha": "abc123",
            "workflow_id": 77,
        },
        "reasons": ["Evidence sufficient."],
        "contradictions": [],
    }


def _bundle():
    request = _request()
    source = _source()
    assumption = build_ci_retry_assumption_state(
        action_request=request,
        evidence_decision=source,
        evidence_sha256="a" * 64,
        created_at=NOW,
    )
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
    return request, assumption, authority, decision


def test_context_profile_vectors_are_versioned():
    assert VECTORS["profile"] == "eba.context/v1"
    assert len(VECTORS["cases"]) >= 10


def test_exact_local_context_is_accepted():
    request, assumption, authority, decision = _bundle()
    ensure_decision_allows_request(
        decision,
        request,
        now=NOW,
        assumption_states=[assumption],
        authority_grant=authority,
    )


@pytest.mark.parametrize(
    ("artifact_name", "mutate", "error"),
    [
        (
            "authority",
            lambda a: a["principal"].update({"id": "other-agent"}),
            "AUTHORITY_PRINCIPAL_MISMATCH",
        ),
        (
            "authority",
            lambda a: a.update({"trace_id": "tr_other"}),
            "AUTHORITY_TRACE_MISMATCH",
        ),
        (
            "authority",
            lambda a: a["trust"].update({"namespace": "github-repository:other/repo"}),
            "AUTHORITY_NAMESPACE_MISMATCH",
        ),
        (
            "authority",
            lambda a: a["trust"].update({"audience": "other-consumer"}),
            "AUTHORITY_AUDIENCE_MISMATCH",
        ),
        (
            "assumption",
            lambda a: a.update({"trace_id": "tr_other"}),
            "ASSUMPTION_TRACE_MISMATCH",
        ),
        (
            "assumption",
            lambda a: a.update({"evidence_refs": ["sha256:" + "b" * 64]}),
            "ASSUMPTION_EVIDENCE_BINDING_MISMATCH",
        ),
        (
            "assumption",
            lambda a: a["trust"].update({"namespace": "github-repository:other/repo"}),
            "ASSUMPTION_NAMESPACE_MISMATCH",
        ),
    ],
)
def test_rehashed_context_substitution_still_rejects(artifact_name, mutate, error):
    request, assumption, authority, decision = _bundle()
    if artifact_name == "authority":
        edited = copy.deepcopy(authority)
        mutate(edited)
        edited = _with_integrity(edited)
        with pytest.raises(ContractViolation, match=error):
            ensure_decision_allows_request(
                decision,
                request,
                now=NOW,
                assumption_states=[assumption],
                authority_grant=edited,
            )
    else:
        edited = copy.deepcopy(assumption)
        mutate(edited)
        edited = _with_integrity(edited)
        with pytest.raises(ContractViolation, match=error):
            ensure_decision_allows_request(
                decision,
                request,
                now=NOW,
                assumption_states=[edited],
                authority_grant=authority,
            )


def test_self_hash_without_explicit_trust_envelope_does_not_authorize():
    request, assumption, authority, decision = _bundle()
    edited = copy.deepcopy(authority)
    edited.pop("trust")
    edited = _with_integrity(edited)
    with pytest.raises(ContractViolation, match="AUTHORITY_TRUST_ENVELOPE_MISSING"):
        ensure_decision_allows_request(
            decision,
            request,
            now=NOW,
            assumption_states=[assumption],
            authority_grant=edited,
        )


def test_identical_resource_text_in_distinct_namespace_is_not_same_authority():
    request, assumption, authority, decision = _bundle()
    changed = copy.deepcopy(request)
    changed["context"]["namespace"] = "github-repository:other/tenant"
    changed = _with_integrity(changed)
    with pytest.raises(ContractViolation):
        ensure_decision_allows_request(
            decision,
            changed,
            now=NOW,
            assumption_states=[assumption],
            authority_grant=authority,
        )
