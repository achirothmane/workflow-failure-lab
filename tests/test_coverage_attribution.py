from coverage_attribution import (
    GATE_CAUSAL_EVIDENCE,
    GATE_CLASSIFICATION_UNKNOWN,
    GATE_CODE_REGRESSION,
    GATE_ELIGIBLE,
    GATE_LOW_CONFIDENCE,
    GATE_NON_TRANSIENT_CATEGORY,
    GATE_PROVENANCE,
    GATE_SIDE_EFFECT,
    KIND_AUTHORITY_BOUNDARY,
    KIND_EVIDENCE_GAP,
    first_coverage_gate,
    summarize_coverage_attribution,
)
from history_ci_waste import HistoricalFailure
from recovery_ground_truth import (
    RECOVERY_NOT_OBSERVED,
    RECOVERY_NOT_RECOVERED,
    RECOVERY_UNVERIFIED,
    RECOVERY_VALIDATED,
)


def failure(
    *,
    category="DEPENDENCY_NETWORK",
    confidence="high",
    provenance="CONFIRMED",
    side_effect=False,
    causal_count=1,
    observed=False,
    recovered=False,
    recovery_status=RECOVERY_NOT_OBSERVED,
):
    return HistoricalFailure(
        run_id=1,
        job_name="test",
        category=category,
        confidence=confidence,
        duration_minutes=1.0,
        rerun_observed=observed,
        recovered_after_rerun=recovered,
        side_effect_risk=side_effect,
        provenance_status=provenance,
        recovery_status=recovery_status,
        causal_evidence_count=causal_count,
    )


def test_first_gate_classification_unknown():
    result = first_coverage_gate(
        failure(category="UNKNOWN", confidence="low", causal_count=0)
    )
    assert result.gate == GATE_CLASSIFICATION_UNKNOWN
    assert result.kind == KIND_EVIDENCE_GAP


def test_first_gate_non_transient_and_code_regression_are_separate():
    assert first_coverage_gate(
        failure(category="RESOURCE_TIMEOUT")
    ).gate == GATE_NON_TRANSIENT_CATEGORY

    assert first_coverage_gate(
        failure(category="CODE_REGRESSION")
    ).gate == GATE_CODE_REGRESSION


def test_low_confidence_without_causal_support_attributes_to_causal_evidence():
    result = first_coverage_gate(
        failure(confidence="medium", causal_count=0)
    )
    assert result.gate == GATE_CAUSAL_EVIDENCE
    assert result.kind == KIND_EVIDENCE_GAP


def test_low_confidence_with_causal_support_attributes_to_confidence():
    result = first_coverage_gate(
        failure(confidence="medium", causal_count=1)
    )
    assert result.gate == GATE_LOW_CONFIDENCE


def test_provenance_precedes_side_effect_in_pipeline_attribution():
    result = first_coverage_gate(
        failure(provenance="MISMATCH", side_effect=True)
    )
    assert result.gate == GATE_PROVENANCE
    assert result.kind == KIND_EVIDENCE_GAP


def test_side_effect_is_authority_boundary_after_evidence_gates_pass():
    result = first_coverage_gate(
        failure(side_effect=True)
    )
    assert result.gate == GATE_SIDE_EFFECT
    assert result.kind == KIND_AUTHORITY_BOUNDARY


def test_fully_safe_failure_is_eligible():
    assert first_coverage_gate(failure()).gate == GATE_ELIGIBLE


def test_summary_keeps_raw_success_separate_from_validated_recovery():
    rows = summarize_coverage_attribution(
        [
            failure(
                provenance="MISMATCH",
                observed=True,
                recovered=True,
                recovery_status=RECOVERY_UNVERIFIED,
            ),
            failure(
                confidence="medium",
                causal_count=1,
                observed=True,
                recovered=False,
                recovery_status=RECOVERY_NOT_RECOVERED,
            ),
            failure(
                side_effect=True,
                observed=True,
                recovered=True,
                recovery_status=RECOVERY_VALIDATED,
            ),
        ]
    )
    by_gate = {item.gate: item for item in rows}

    provenance = by_gate[GATE_PROVENANCE]
    assert provenance.raw_later_successes == 1
    assert provenance.validated_recoveries == 0
    assert provenance.unknown_or_unverified == 1

    confidence = by_gate[GATE_LOW_CONFIDENCE]
    assert confidence.failed_reruns == 1

    authority = by_gate[GATE_SIDE_EFFECT]
    assert authority.raw_later_successes == 1
    assert authority.validated_recoveries == 1
