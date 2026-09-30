from public_incident_corpus import PUBLIC_INCIDENT_CORPUS_V1


def test_public_incident_corpus_has_unique_case_ids():
    ids = [case.case_id for case in PUBLIC_INCIDENT_CORPUS_V1]
    assert len(ids) == len(set(ids))


def test_public_incident_corpus_is_source_backed():
    for case in PUBLIC_INCIDENT_CORPUS_V1:
        assert case.repository
        assert case.source_url.startswith("https://github.com/")
        assert case.observed_signal
        assert case.actual_cause_family
        assert case.remediation_family
        assert case.classifier_implication


def test_runner_shutdown_cases_are_not_labeled_runner_infra_ground_truth():
    assert PUBLIC_INCIDENT_CORPUS_V1
    for case in PUBLIC_INCIDENT_CORPUS_V1:
        assert case.actual_cause_family != "RUNNER_INFRA"


def test_corpus_contains_multiple_independent_remediation_families():
    families = {case.remediation_family for case in PUBLIC_INCIDENT_CORPUS_V1}
    assert len(families) >= 3
