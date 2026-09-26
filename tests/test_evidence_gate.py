from __future__ import annotations

from copy import deepcopy

from ci_retry_gate import (
    FAILURE_STEP_CONFIRMED,
    PROVENANCE_CONFIRMED,
    JobAssessment,
)
from evidence_gate import (
    assess_ci_retry_evidence,
    decide_ci_retry,
    evidence_contradictions,
)
from evidence_producer import produce_ci_evidence_bundle


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
        provenance_command="npm ci",
        provenance_evidence=("signal: curl: (28) operation timed out",),
        failure_step_status=FAILURE_STEP_CONFIRMED,
        failure_step="Install dependencies",
        failure_step_evidence=("failed step: Install dependencies",),
        side_effect_risk=side_effect_risk,
        side_effect_evidence=("deploy production",) if side_effect_risk else (),
        duration_minutes=2.5,
    )


def _bundle(*, run_attempt: int = 1, assessment: JobAssessment | None = None) -> dict:
    return produce_ci_evidence_bundle(
        repo="owner/repo",
        run={
            "head_sha": "abc123",
            "workflow_id": 99,
            "updated_at": "2026-09-22T20:10:00Z",
        },
        run_id=123,
        run_attempt=run_attempt,
        assessments=[assessment or _assessment()],
    )


def test_gate_allows_only_from_bundle_evidence() -> None:
    safe, reason = decide_ci_retry(_bundle(), max_attempts=2)

    assert safe is True
    assert "high-confidence transient" in reason


def test_gate_does_not_accept_job_assessment_objects_as_evidence_input() -> None:
    safe, reason = decide_ci_retry([_assessment()], max_attempts=2)

    assert safe is False
    assert "Evidence bundle is invalid" in reason


def test_missing_required_claim_fails_closed() -> None:
    bundle = _bundle()
    bundle["derived"] = [
        item for item in bundle["derived"]
        if item.get("claim") != "execution_provenance_status"
    ]

    safe, reason = assess_ci_retry_evidence(bundle)

    assert safe is False
    assert "missing(execution_provenance_status)" in reason


def test_conflicting_claim_fails_closed_and_is_reported() -> None:
    bundle = _bundle()
    duplicate = deepcopy(
        next(item for item in bundle["derived"] if item["claim"] == "failure_category")
    )
    duplicate["value"] = "CODE_REGRESSION"
    bundle["derived"].append(duplicate)

    safe, reason = assess_ci_retry_evidence(bundle)

    assert safe is False
    assert "conflicting(failure_category)" in reason
    assert "unit-tests: conflicting_claim=failure_category" in evidence_contradictions(bundle)


def test_retry_limit_is_policy_not_evidence_contradiction() -> None:
    bundle = _bundle(run_attempt=2)

    safe, reason = decide_ci_retry(bundle, max_attempts=2)

    assert safe is False
    assert "max_attempts=2" in reason
    assert evidence_contradictions(bundle) == []
