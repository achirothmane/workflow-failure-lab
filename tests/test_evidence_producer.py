from __future__ import annotations

from ci_retry_gate import (
    FAILURE_STEP_CONFIRMED,
    PROVENANCE_CONFIRMED,
    PROVENANCE_UNAVAILABLE,
    JobAssessment,
)
from evidence_gate import build_ci_retry_decision
from evidence_producer import EVIDENCE_BUNDLE_SCHEMA, produce_ci_evidence_bundle


def _assessment(*, provenance_status: str = PROVENANCE_CONFIRMED) -> JobAssessment:
    return JobAssessment(
        job_id=42,
        name="unit-tests",
        category="DEPENDENCY_NETWORK",
        confidence="high",
        evidence=("curl: (28) operation timed out",),
        provenance_status=provenance_status,
        provenance_step="Install dependencies",
        provenance_command="pip install -r requirements.txt",
        provenance_evidence=(
            ("signal: curl: (28) operation timed out",)
            if provenance_status != PROVENANCE_UNAVAILABLE
            else ()
        ),
        failure_step_status=FAILURE_STEP_CONFIRMED,
        failure_step="Install dependencies",
        failure_step_evidence=("failed step: Install dependencies",),
        side_effect_risk=False,
        side_effect_evidence=(),
        duration_minutes=2.5,
    )


def _run() -> dict:
    return {
        "head_sha": "abc123",
        "workflow_id": 99,
        "updated_at": "2026-09-22T20:10:00Z",
    }


def _contains_key(value: object, forbidden: str) -> bool:
    if isinstance(value, dict):
        return forbidden in value or any(
            _contains_key(item, forbidden) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_key(item, forbidden) for item in value)
    return False


def test_producer_separates_observed_from_derived_and_has_no_policy() -> None:
    bundle = produce_ci_evidence_bundle(
        repo="owner/repo",
        run=_run(),
        run_id=123,
        run_attempt=1,
        assessments=[_assessment()],
    )

    assert bundle["schema_version"] == EVIDENCE_BUNDLE_SCHEMA
    assert bundle["producer"] == {
        "name": "workflow-failure-lab",
        "mode": "deterministic",
        "policy_free": True,
    }
    assert bundle["subject"]["head_sha"] == "abc123"
    assert bundle["quality"]["status"] == "COMPLETE"
    assert bundle["inferred"] == []

    assert any(
        item["source"] == "github-actions.job-log"
        and "timed out" in item["detail"]
        for item in bundle["observations"]
    )
    assert any(
        item["claim"] == "failure_category"
        and item["value"] == "DEPENDENCY_NETWORK"
        for item in bundle["derived"]
    )

    assert not _contains_key(bundle, "decision")
    assert not _contains_key(bundle, "retry_permitted")
    assert not _contains_key(bundle, "policy")
    assert not _contains_key(bundle, "max_attempts")


def test_missing_provenance_is_reported_as_evidence_quality_not_policy() -> None:
    bundle = produce_ci_evidence_bundle(
        repo="owner/repo",
        run=_run(),
        run_id=123,
        run_attempt=1,
        assessments=[_assessment(provenance_status=PROVENANCE_UNAVAILABLE)],
    )

    assert bundle["quality"]["status"] == "PARTIAL"
    assert "job:42:execution-provenance" in bundle["quality"]["missing_sources"]
    assert bundle["quality"]["contradictions"] == []
    assert bundle["inferred"] == []


def test_retry_gate_embeds_the_producer_bundle_without_moving_policy_into_it() -> None:
    assessment = _assessment()
    evidence_bundle = produce_ci_evidence_bundle(
        repo="owner/repo",
        run=_run(),
        run_id=123,
        run_attempt=1,
        assessments=[assessment],
    )
    payload = build_ci_retry_decision(
        evidence_bundle,
        max_attempts=2,
    )

    bundle = payload["evidence_bundle"]
    assert bundle["schema_version"] == EVIDENCE_BUNDLE_SCHEMA
    assert payload["decision"] == "ALLOW"
    assert payload["policy"] == {"max_attempts": 2}
    assert not _contains_key(bundle, "decision")
    assert not _contains_key(bundle, "policy")
