from __future__ import annotations

import json

import pytest

from decision_record import (
    DecisionRecordError,
    build_decision_record,
    decision_parent_ref,
    read_decision_record,
    seal_decision_record,
    verify_decision_record,
    write_decision_record,
)


EVIDENCE_SHA = "a" * 64


def _decision(*, attempt: int, decision: str = "ALLOW") -> dict:
    return {
        "decision": decision,
        "evidence_status": "SUFFICIENT" if decision == "ALLOW" else "UNKNOWN",
        "reasons": ["bounded retry evidence accepted" if decision == "ALLOW" else "insufficient evidence"],
        "scope": {
            "repository": "owner/repo",
            "run_id": 123,
            "run_attempt": attempt,
            "head_sha": "abc123",
            "workflow_id": 99,
        },
    }


def _record(
    *,
    attempt: int,
    decision: str = "ALLOW",
    parent: dict | None = None,
    event_id: str,
) -> dict:
    return build_decision_record(
        evidence_decision=_decision(attempt=attempt, decision=decision),
        evidence_bundle_sha256=EVIDENCE_SHA,
        policy_ref="ci-retry-gate.production.v1",
        authorization_path="POLICY",
        next_action="RERUN_ALLOWED" if decision == "ALLOW" else "INVESTIGATE_FAILURE",
        identities={
            "workflow_actor": {
                "raw": "alice",
                "identity_type": "human",
            },
            "decision_engine": {
                "raw": "achirothmane/workflow-failure-lab",
                "identity_type": "unknown",
            },
        },
        parent_decision=parent,
        event_id=event_id,
        recorded_at=f"2026-10-02T0{attempt}:00:00Z",
    )


def test_decision_record_round_trip_is_canonical_and_verified(tmp_path) -> None:
    path = tmp_path / "decision.json"
    record = _record(attempt=1, event_id="evt-1")

    digest = write_decision_record(path, record)
    loaded = read_decision_record(path, expected_sha256=digest)

    assert loaded["schema_version"] == "ci-retry-gate.decision-record.v1"
    assert loaded["decision"] == "ALLOW"
    assert loaded["evidence_bundle_sha256"] == EVIDENCE_SHA
    assert loaded["policy_ref"] == "ci-retry-gate.production.v1"
    assert loaded["authorization_path"] == "POLICY"
    assert loaded["next_action"] == "RERUN_ALLOWED"
    assert loaded["record_sha256"] == digest
    assert "outcome" not in loaded
    assert "log_excerpt" not in loaded
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_semantic_tamper_is_rejected_before_record_use(tmp_path) -> None:
    path = tmp_path / "decision.json"
    digest = write_decision_record(path, _record(attempt=1, event_id="evt-1"))

    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["decision"] = "BLOCK"
    path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(DecisionRecordError, match="SHA-256 mismatch"):
        read_decision_record(path, expected_sha256=digest)


def test_external_expected_digest_rejects_resealed_rewrite(tmp_path) -> None:
    path = tmp_path / "decision.json"
    original_digest = write_decision_record(
        path,
        _record(attempt=1, event_id="evt-1"),
    )

    rewritten = _record(attempt=1, decision="BLOCK", event_id="evt-1")
    rewritten_sealed = seal_decision_record(rewritten)
    path.write_text(
        json.dumps(rewritten_sealed, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    # The attacker can recompute the embedded digest, but not the independently
    # retained expected digest from the original decision.
    verify_decision_record(rewritten_sealed)
    with pytest.raises(DecisionRecordError, match="expected"):
        read_decision_record(path, expected_sha256=original_digest)


def test_human_override_requires_reason_and_preserves_raw_identity() -> None:
    with pytest.raises(DecisionRecordError, match="non-empty reason"):
        build_decision_record(
            evidence_decision=_decision(attempt=2, decision="ALLOW"),
            evidence_bundle_sha256=EVIDENCE_SHA,
            policy_ref="ci-retry-gate.production.v1",
            authorization_path="HUMAN_OVERRIDE",
            next_action="RERUN_ALLOWED",
            identities={
                "decision_engine": {
                    "raw": "achirothmane/workflow-failure-lab",
                    "identity_type": "unknown",
                }
            },
            override={
                "actor": {
                    "raw": "github-actions[bot]",
                    "identity_type": "bot",
                },
                "reason": "",
                "original_decision_event_id": "evt-blocked",
            },
            event_id="evt-override",
            recorded_at="2026-10-02T02:00:00Z",
        )

    record = build_decision_record(
        evidence_decision=_decision(attempt=2, decision="ALLOW"),
        evidence_bundle_sha256=EVIDENCE_SHA,
        policy_ref="ci-retry-gate.production.v1",
        authorization_path="HUMAN_OVERRIDE",
        next_action="RERUN_ALLOWED",
        identities={
            "decision_engine": {
                "raw": "achirothmane/workflow-failure-lab",
                "identity_type": "unknown",
            }
        },
        override={
            "actor": {
                "raw": "maintainer-login",
                "identity_type": "human",
            },
            "reason": "incident mitigation approved by maintainer",
            "authority_source": "repository-maintainer",
            "original_decision_event_id": "evt-blocked",
        },
        event_id="evt-override",
        recorded_at="2026-10-02T02:00:00Z",
    )

    sealed = seal_decision_record(record)
    verify_decision_record(sealed)
    assert sealed["decision"] == "ALLOW"
    assert sealed["authorization_path"] == "HUMAN_OVERRIDE"
    assert sealed["override"]["actor"] == {
        "raw": "maintainer-login",
        "identity_type": "human",
    }


def test_three_attempt_chain_links_records_without_inheriting_authority() -> None:
    first = seal_decision_record(_record(attempt=1, event_id="evt-1"))
    second = seal_decision_record(
        _record(
            attempt=2,
            decision="BLOCK",
            parent=decision_parent_ref(first),
            event_id="evt-2",
        )
    )
    third = seal_decision_record(
        _record(
            attempt=3,
            parent=decision_parent_ref(second),
            event_id="evt-3",
        )
    )

    verify_decision_record(first)
    verify_decision_record(second)
    verify_decision_record(third)

    assert second["parent_decision"] == {
        "event_id": "evt-1",
        "record_sha256": first["record_sha256"],
        "run_attempt": 1,
    }
    assert third["parent_decision"] == {
        "event_id": "evt-2",
        "record_sha256": second["record_sha256"],
        "run_attempt": 2,
    }

    # Linkage records history only: a BLOCK parent does not force the fresh
    # attempt's independently evaluated decision.
    assert second["decision"] == "BLOCK"
    assert third["decision"] == "ALLOW"
