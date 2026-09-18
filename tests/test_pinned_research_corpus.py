from classifier_rule_research import evaluate_server5xx_shadow_rule
from ci_retry_gate import (
    FAILURE_STEP_CONFIRMED,
    assess_failure_step_provenance,
    classify_log,
    detect_side_effect_risk,
)
from history_ci_waste import HistoricalFailure
from pinned_research_corpus import SERDE_ATTESTATION_HTTP_500, TRAEFIK_GOLANGCI_HTTP_504
from mechanism_causality_gate import (
    MECHANISM_CAUSAL_CONFIRMED,
    assess_mechanism_causality,
)
from recovery_ground_truth import RECOVERY_VALIDATED, assess_recovery_ground_truth
from transient_mechanism_gate import (
    MECHANISM_TRANSIENT_SUPPORTED,
    MECHANISM_UNPROVEN,
    REASON_SERVER_5XX,
    assess_transient_mechanism,
)
from unknown_cause_decomposition import decompose_unknown_cause
from targeted_replication_search import search_targeted_replication
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


def _historical_from_pinned_case(case):
    classification = classify_log(case.failure_log)
    side_effect, _evidence = detect_side_effect_risk(case.failed_job)
    failure_step = assess_failure_step_provenance(case.failed_job)
    recovery = assess_recovery_ground_truth(
        original_job=case.failed_job,
        failure_step_status=failure_step.status,
        failure_step=failure_step.step_name,
        rerun_observed=True,
        recovered=True,
        rerun_job=case.rerun_job,
    )
    signature = unknown_signature(case.failure_log)
    cause = decompose_unknown_cause(case.failure_log)
    mechanism_causality = assess_mechanism_causality(case.failed_job, case.failure_log)
    return HistoricalFailure(
        run_id=case.run_id,
        job_name=case.job_name,
        category=classification.category,
        confidence=classification.confidence,
        duration_minutes=1.0,
        fingerprint=f"FG-PINNED-{case.case_id}",
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


def test_pinned_traefik_http_504_is_causal_validated_recovery():
    case = TRAEFIK_GOLANGCI_HTTP_504

    classification = classify_log(case.failure_log)
    assert classification.category == case.expected_runtime_category == "UNKNOWN"

    side_effect, _evidence = detect_side_effect_risk(case.failed_job)
    assert side_effect is case.expected_side_effect_risk is False

    failure_step = assess_failure_step_provenance(case.failed_job)
    assert failure_step.status == FAILURE_STEP_CONFIRMED
    assert failure_step.step_name == "golangci-lint"

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
    mechanism_causality = assess_mechanism_causality(case.failed_job, case.failure_log)

    # The normalized UNKNOWN signature replaces 504 with <n>, so the signature-only
    # heuristic cannot recover the 5xx code. Direct failed-step causal evidence is stronger.
    assert mechanism.status == MECHANISM_UNPROVEN
    assert case.expected_mechanism_status == MECHANISM_TRANSIENT_SUPPORTED
    assert case.expected_mechanism_reason == REASON_SERVER_5XX
    assert mechanism_causality.status == MECHANISM_CAUSAL_CONFIRMED
    assert mechanism_causality.reasons == (REASON_SERVER_5XX,)
    assert any("504" in line for line in mechanism_causality.evidence)

    failure = _historical_from_pinned_case(case)
    intelligence = summarize_unknown_patterns(
        {},
        {case.repository: ([failure], 1)},
    )
    pattern = intelligence.patterns[0]
    assert pattern.mechanism_status == MECHANISM_TRANSIENT_SUPPORTED
    assert pattern.mechanism_reasons == (REASON_SERVER_5XX,)


def test_pinned_server_5xx_mechanism_family_is_cross_repository_replicated():
    serde = _historical_from_pinned_case(SERDE_ATTESTATION_HTTP_500)
    traefik = _historical_from_pinned_case(TRAEFIK_GOLANGCI_HTTP_504)

    summary = search_targeted_replication(
        {
            SERDE_ATTESTATION_HTTP_500.repository: ([serde], 1),
            TRAEFIK_GOLANGCI_HTTP_504.repository: ([traefik], 1),
        },
        "SERVER_5XX",
    )

    assert summary.independent_runs == 2
    assert summary.independent_repositories == 2
    assert summary.validated_recoveries == 2
    assert summary.failed_again == 0
    assert summary.recovery_rate == 1.0
    assert summary.replicated is True
    assert summary.cross_repository_replicated is True
    assert summary.repositories == ("serde-rs/serde", "traefik/traefik")


def test_pinned_traefik_metadata_matches_observed_public_run():
    case = TRAEFIK_GOLANGCI_HTTP_504

    assert case.repository == "traefik/traefik"
    assert case.run_id == 34857150924
    assert case.failed_attempt == 1
    assert case.rerun_attempt == 2
    assert case.failed_job_id == 104019537901
    assert case.rerun_job_id == 104021344977
    assert "Unexpected HTTP response: 504" in case.failure_log


def test_pinned_server_5xx_cases_support_shadow_classifier_hypothesis():
    serde = _historical_from_pinned_case(SERDE_ATTESTATION_HTTP_500)
    traefik = _historical_from_pinned_case(TRAEFIK_GOLANGCI_HTTP_504)

    summary = evaluate_server5xx_shadow_rule(
        {},
        {
            SERDE_ATTESTATION_HTTP_500.repository: ([serde], 1),
            TRAEFIK_GOLANGCI_HTTP_504.repository: ([traefik], 1),
        },
    )

    assert summary.evaluable_matches == 2
    assert summary.validated_recoveries == 2
    assert summary.failed_again == 0
    assert summary.observed_precision == 1.0
    assert summary.independent_runs == 2
    assert summary.independent_repositories == 2
    assert summary.side_effect_matches == 0

