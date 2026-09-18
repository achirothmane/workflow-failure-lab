from ci_retry_gate import (
    FAILURE_STEP_CONFIRMED,
    assess_failure_step_provenance,
    classify_log,
    detect_side_effect_risk,
)
from history_ci_waste import HistoricalFailure
from pinned_research_corpus import SERDE_ATTESTATION_HTTP_500
from mechanism_causality_gate import (
    MECHANISM_CAUSAL_CONFIRMED,
    assess_mechanism_causality,
)
from recovery_ground_truth import RECOVERY_VALIDATED, assess_recovery_ground_truth
from transient_mechanism_gate import (
    MECHANISM_TRANSIENT_SUPPORTED,
    REASON_SERVER_5XX,
    assess_transient_mechanism,
)
from unknown_cause_decomposition import decompose_unknown_cause
from unknown_failure_intelligence import (
    PROMOTION_BLOCKER_INDEPENDENT_REPLICATION,
    PROMOTION_BLOCKER_INSUFFICIENT_GT_RERUNS,
    PROMOTION_BLOCKER_INSUFFICIENT_OCCURRENCES,
    summarize_unknown_patterns,
    unknown_signature,
)


def test_pinned_serde_http_500_remains_research_only_transient_candidate():
    case = SERDE_ATTESTATION_HTTP_500

    classification = classify_log(case.failure_log)
    assert classification.category == case.expected_runtime_category

    side_effect, _evidence = detect_side_effect_risk(case.failed_job)
    assert side_effect is case.expected_side_effect_risk

    failure_step = assess_failure_step_provenance(case.failed_job)
    assert failure_step.status == FAILURE_STEP_CONFIRMED
    assert failure_step.step_name == "Run dtolnay/install@cargo-outdated"

    recovery = assess_recovery_ground_truth(
        original_job=case.failed_job,
        failure_step_status=failure_step.status,
        failure_step=failure_step.step_name,
        rerun_observed=True,
        recovered=True,
        rerun_job=case.rerun_job,
    )
    assert recovery.status == case.expected_recovery_status == RECOVERY_VALIDATED

    signature = unknown_signature(case.failure_log)
    cause = decompose_unknown_cause(case.failure_log)
    mechanism = assess_transient_mechanism(signature, (cause.cause,))
    mechanism_causality = assess_mechanism_causality(
        case.failed_job,
        case.failure_log,
    )

    assert mechanism.status == case.expected_mechanism_status == MECHANISM_TRANSIENT_SUPPORTED
    assert case.expected_mechanism_reason == REASON_SERVER_5XX
    assert REASON_SERVER_5XX in mechanism.reasons
    assert mechanism_causality.status == MECHANISM_CAUSAL_CONFIRMED
    assert mechanism_causality.reasons == (REASON_SERVER_5XX,)
    assert any("HTTP 500" in line for line in mechanism_causality.evidence)

    failure = HistoricalFailure(
        run_id=case.run_id,
        job_name=case.job_name,
        category=classification.category,
        confidence=classification.confidence,
        duration_minutes=1.0,
        fingerprint="FG-PINNED-SERDE-HTTP-500",
        signature=signature,
        recovered_after_rerun=True,
        rerun_observed=True,
        side_effect_risk=side_effect,
        attempt=case.failed_attempt,
        recovery_status=recovery.status,
        unknown_cause=cause.cause,
        failure_step_status=failure_step.status,
        failure_step=failure_step.step_name,
        mechanism_causality_status=mechanism_causality.status,
        mechanism_causality_reasons=mechanism_causality.reasons,
        mechanism_causal_evidence=mechanism_causality.evidence,
    )
    intelligence = summarize_unknown_patterns(
        {},
        {case.repository: ([failure], 1)},
    )
    pattern = intelligence.patterns[0]

    assert pattern.promotion_candidate is False
    assert pattern.promotion_blockers == (
        PROMOTION_BLOCKER_INDEPENDENT_REPLICATION,
        PROMOTION_BLOCKER_INSUFFICIENT_OCCURRENCES,
        PROMOTION_BLOCKER_INSUFFICIENT_GT_RERUNS,
    )
    assert pattern.occurrence_deficit == 2
    assert pattern.gt_rerun_deficit == 2
    assert pattern.mechanism_status == MECHANISM_TRANSIENT_SUPPORTED
    assert pattern.mechanism_causal_gt_reruns == 1
    assert pattern.mechanism_causality_reasons == (REASON_SERVER_5XX,)
    assert pattern.independent_runs == 1
    assert pattern.independent_repositories == 1
    assert pattern.replication_run_ids == (case.run_id,)
    assert pattern.independent_run_deficit == 1


def test_pinned_corpus_metadata_matches_observed_public_run():
    case = SERDE_ATTESTATION_HTTP_500

    assert case.repository == "serde-rs/serde"
    assert case.run_id == 34427119351
    assert case.failed_attempt == 1
    assert case.rerun_attempt == 2
    assert case.failed_job_id == 102714612067
    assert case.rerun_job_id == 102722754676
    assert "HTTP 500: Server Error" in case.failure_log
