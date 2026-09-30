from public_incident_corpus import (
    PUBLIC_INCIDENT_CORPUS_V1,
    PUBLIC_INCIDENT_CORPUS_V2,
    PUBLIC_INCIDENT_CORPUS_V3,
)


def test_public_incident_corpus_v3_has_unique_case_ids():
    ids = [case.case_id for case in PUBLIC_INCIDENT_CORPUS_V3]
    assert len(ids) == len(set(ids))


def test_public_incident_corpus_v3_is_source_backed():
    for case in PUBLIC_INCIDENT_CORPUS_V3:
        assert case.repository
        assert case.source_url.startswith("https://github.com/")
        assert case.observed_signal
        assert case.actual_cause_family
        assert case.remediation_family
        assert case.classifier_implication
        assert case.expected_decision in {"ALLOW", "BLOCK"}


def test_v1_runner_shutdown_cases_are_not_labeled_runner_infra_ground_truth():
    assert PUBLIC_INCIDENT_CORPUS_V1
    for case in PUBLIC_INCIDENT_CORPUS_V1:
        assert case.actual_cause_family != "RUNNER_INFRA"
        assert case.expected_decision == "BLOCK"


def test_v2_bidirectional_baseline_is_preserved():
    assert len(PUBLIC_INCIDENT_CORPUS_V2) == 6
    assert sum(case.expected_decision == "ALLOW" for case in PUBLIC_INCIDENT_CORPUS_V2) == 3
    assert sum(case.expected_decision == "BLOCK" for case in PUBLIC_INCIDENT_CORPUS_V2) == 3


def test_v3_adds_mechanism_diversity():
    added = PUBLIC_INCIDENT_CORPUS_V3[len(PUBLIC_INCIDENT_CORPUS_V2):]
    assert len(added) == 3
    assert {case.actual_cause_family for case in added} == {
        "TRANSIENT_DEPENDENCY_NETWORK",
        "HOSTED_RUNNER_LOSS",
        "PERSISTENT_DEPENDENCY_RATE_LIMIT",
    }


def test_corpus_contains_multiple_independent_remediation_families():
    families = {case.remediation_family for case in PUBLIC_INCIDENT_CORPUS_V3}
    assert len(families) >= 8


def test_positive_controls_have_same_run_recovery_identity():
    positive = [
        case for case in PUBLIC_INCIDENT_CORPUS_V3
        if case.expected_decision == "ALLOW"
    ]

    assert len(positive) == 4
    assert len({case.repository for case in positive}) == 4
    for case in positive:
        assert case.ground_truth_run_id is not None
        assert case.failed_job_id is not None
        assert case.successful_rerun_job_id is not None
        assert case.failed_job_id != case.successful_rerun_job_id


def test_persistent_rate_limit_records_failed_next_attempt():
    case = next(
        item for item in PUBLIC_INCIDENT_CORPUS_V3
        if item.case_id == "hiromi-github-rate-limit-recurrence-2026-09-26"
    )

    assert case.expected_decision == "BLOCK"
    assert case.failed_job_id == 108421448279
    assert case.successful_rerun_job_id is None
    assert case.recurrent_rerun_job_id == 108422710231


def test_runner_loss_control_separates_cause_from_authority():
    case = next(
        item for item in PUBLIC_INCIDENT_CORPUS_V3
        if item.case_id == "prql-hosted-runner-loss-2026-08-26"
    )

    assert case.actual_cause_family == "HOSTED_RUNNER_LOSS"
    assert case.expected_decision == "BLOCK"
    assert case.successful_rerun_job_id == 98168778451
