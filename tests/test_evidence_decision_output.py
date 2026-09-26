from __future__ import annotations

import json

from ci_retry_gate import (
    FAILURE_STEP_CONFIRMED,
    PROVENANCE_CONFIRMED,
    PROVENANCE_UNAVAILABLE,
    JobAssessment,
    build_evidence_decision,
)


def _assessment(
    *,
    category: str = "DEPENDENCY_NETWORK",
    confidence: str = "high",
    provenance_status: str = PROVENANCE_CONFIRMED,
    side_effect_risk: bool = False,
) -> JobAssessment:
    return JobAssessment(
        job_id=42,
        name="unit-tests",
        category=category,
        confidence=confidence,
        evidence=("curl: (28) operation timed out",),
        provenance_status=provenance_status,
        provenance_step="Install dependencies",
        provenance_command="pip install -r requirements.txt",
        provenance_evidence=("signal: curl: (28) operation timed out",),
        failure_step_status=FAILURE_STEP_CONFIRMED,
        failure_step="Install dependencies",
        failure_step_evidence=("failed step: Install dependencies",),
        side_effect_risk=side_effect_risk,
        side_effect_evidence=("deploy production",) if side_effect_risk else (),
        duration_minutes=2.5,
    )


def _run() -> dict:
    return {
        "head_sha": "abc123",
        "workflow_id": 99,
        "updated_at": "2026-09-22T20:10:00Z",
    }


def test_safe_decision_emits_sufficient_allow_contract() -> None:
    payload = build_evidence_decision(
        repo="owner/repo",
        run=_run(),
        run_id=123,
        run_attempt=1,
        max_attempts=2,
        assessments=[_assessment()],
        safe=True,
        reason="All failed jobs passed the rerun safety gate.",
        rerun_triggered=False,
    )

    assert payload["schema_version"] == "ci-retry-gate.evidence-decision.v1"
    assert payload["action"] == "rerun_ci"
    assert payload["decision"] == "ALLOW"
    assert payload["evidence_status"] == "SUFFICIENT"
    assert payload["confidence"] == "high"
    assert payload["observed_at"] == "2026-09-22T20:10:00Z"
    assert payload["fresh_until"] is None
    assert payload["scope"] == {
        "repository": "owner/repo",
        "run_id": 123,
        "run_attempt": 1,
        "head_sha": "abc123",
        "workflow_id": 99,
    }
    assert payload["contradictions"] == []
    assert payload["failed_jobs"][0]["provenance_status"] == PROVENANCE_CONFIRMED

    compact = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    assert "\n" not in compact


def test_side_effect_is_explicit_contradiction_and_blocks() -> None:
    payload = build_evidence_decision(
        repo="owner/repo",
        run=_run(),
        run_id=123,
        run_attempt=1,
        max_attempts=2,
        assessments=[_assessment(side_effect_risk=True)],
        safe=False,
        reason="At least one failed job contains a side-effect signal.",
        rerun_triggered=False,
    )

    assert payload["decision"] == "BLOCK"
    assert payload["evidence_status"] == "CONTRADICTED"
    assert payload["confidence"] == "high"
    assert "unit-tests: side_effect_risk" in payload["contradictions"]


def test_missing_provenance_stays_unknown_and_fail_closed() -> None:
    payload = build_evidence_decision(
        repo="owner/repo",
        run=_run(),
        run_id=123,
        run_attempt=1,
        max_attempts=2,
        assessments=[_assessment(provenance_status=PROVENANCE_UNAVAILABLE)],
        safe=False,
        reason="Execution provenance was not confirmed.",
        rerun_triggered=False,
    )

    assert payload["decision"] == "BLOCK"
    assert payload["evidence_status"] == "UNKNOWN"
    assert payload["confidence"] == "unknown"
    assert payload["contradictions"] == []


def test_retry_limit_policy_does_not_become_evidence_contradiction() -> None:
    payload = build_evidence_decision(
        repo="owner/repo",
        run=_run(),
        run_id=123,
        run_attempt=2,
        max_attempts=2,
        assessments=[_assessment()],
        safe=False,
        reason="Run attempt reached the configured retry limit.",
        rerun_triggered=False,
    )

    assert payload["decision"] == "BLOCK"
    assert payload["evidence_status"] == "UNKNOWN"
    assert not any(item.startswith("retry_limit_reached:") for item in payload["contradictions"])
