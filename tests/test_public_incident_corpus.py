from public_incident_corpus import (
    PUBLIC_INCIDENT_CORPUS_V1,
    PUBLIC_INCIDENT_CORPUS_V2,
)


def test_public_incident_corpus_v2_has_unique_case_ids():
    ids = [case.case_id for case in PUBLIC_INCIDENT_CORPUS_V2]
    assert len(ids) == len(set(ids))


def test_public_incident_corpus_v2_is_source_backed():
    for case in PUBLIC_INCIDENT_CORPUS_V2:
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


def test_corpus_contains_multiple_independent_remediation_families():
    families = {case.remediation_family for case in PUBLIC_INCIDENT_CORPUS_V2}
    assert len(families) >= 5


def test_positive_controls_have_same_run_recovery_identity():
    positive = [
        case
        for case in PUBLIC_INCIDENT_CORPUS_V2
        if case.expected_decision == "ALLOW"
    ]

    assert len(positive) == 3
    assert len({case.repository for case in positive}) == 3
    for case in positive:
        assert case.ground_truth_run_id is not None
        assert case.failed_job_id is not None
        assert case.successful_rerun_job_id is not None
        assert case.failed_job_id != case.successful_rerun_job_id
