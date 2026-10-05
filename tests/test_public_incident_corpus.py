from validation.public_incidents.public_incident_corpus import (
    PUBLIC_INCIDENT_CORPUS_V1,
    PUBLIC_INCIDENT_CORPUS_V2,
    PUBLIC_INCIDENT_CORPUS_V3,
    PUBLIC_INCIDENT_CORPUS_V4,
    PUBLIC_INCIDENT_CORPUS_V5,
)


def test_public_incident_corpus_v5_has_unique_case_ids():
    ids = [case.case_id for case in PUBLIC_INCIDENT_CORPUS_V5]
    assert len(ids) == len(set(ids))


def test_public_incident_corpus_v5_is_source_backed():
    for case in PUBLIC_INCIDENT_CORPUS_V5:
        assert case.repository
        assert case.source_url.startswith("https://github.com/")
        assert case.observed_signal
        assert case.actual_cause_family
        assert case.remediation_family
        assert case.classifier_implication
        assert case.expected_decision in {"ALLOW", "BLOCK"}


def test_v1_runner_shutdown_cases_remain_block_controls():
    for case in PUBLIC_INCIDENT_CORPUS_V1:
        assert case.actual_cause_family != "RUNNER_INFRA"
        assert case.expected_decision == "BLOCK"


def test_v2_bidirectional_baseline_is_preserved():
    assert len(PUBLIC_INCIDENT_CORPUS_V2) == 6
    assert sum(case.expected_decision == "ALLOW" for case in PUBLIC_INCIDENT_CORPUS_V2) == 3
    assert sum(case.expected_decision == "BLOCK" for case in PUBLIC_INCIDENT_CORPUS_V2) == 3


def test_v3_mechanism_diversity_is_preserved():
    assert len(PUBLIC_INCIDENT_CORPUS_V3) == 9
    added = PUBLIC_INCIDENT_CORPUS_V3[len(PUBLIC_INCIDENT_CORPUS_V2):]
    assert {case.actual_cause_family for case in added} == {
        "TRANSIENT_DEPENDENCY_NETWORK",
        "HOSTED_RUNNER_LOSS",
        "PERSISTENT_DEPENDENCY_RATE_LIMIT",
    }


def test_v4_keeps_authority_decisions_while_improving_prql_provenance_contract():
    v3 = {case.case_id: case for case in PUBLIC_INCIDENT_CORPUS_V3}
    v4 = {case.case_id: case for case in PUBLIC_INCIDENT_CORPUS_V4}

    changed = [
        case_id
        for case_id in v4
        if v4[case_id].expected_decision != v3[case_id].expected_decision
    ]
    assert changed == []

    prql = v4["prql-hosted-runner-loss-2026-08-26"]
    assert prql.expected_decision == "BLOCK"
    assert "does not override an independent side-effect boundary" in prql.classifier_implication


def test_v5_positive_controls_have_observable_recovery():
    positive = [
        case for case in PUBLIC_INCIDENT_CORPUS_V5
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
        item for item in PUBLIC_INCIDENT_CORPUS_V5
        if item.case_id == "hiromi-github-rate-limit-recurrence-2026-09-26"
    )

    assert case.expected_decision == "BLOCK"
    assert case.failed_job_id == 108421448279
    assert case.successful_rerun_job_id is None
    assert case.recurrent_rerun_job_id == 108422710231


def test_v5_adds_persistence_and_provenance_block_controls():
    v4_ids = {case.case_id for case in PUBLIC_INCIDENT_CORPUS_V4}
    added = [case for case in PUBLIC_INCIDENT_CORPUS_V5 if case.case_id not in v4_ids]

    assert len(added) == 2
    assert {case.case_id for case in added} == {
        "runner-images-13719-prestep-disk-exhaustion",
        "serverless-cfn-lint-dns-retry-exhaustion-2025-11-19",
    }
    assert all(case.expected_decision == "BLOCK" for case in added)

    dns = next(
        case for case in added
        if case.case_id == "serverless-cfn-lint-dns-retry-exhaustion-2025-11-19"
    )
    assert dns.ground_truth_run_id == 19517345578
    assert dns.failed_job_id == 55875798766
    assert dns.successful_rerun_job_id == 55876077959
