from public_incident_corpus import (
    PUBLIC_INCIDENT_CORPUS_V1,
    PUBLIC_INCIDENT_CORPUS_V2,
    PUBLIC_INCIDENT_CORPUS_V3,
    PUBLIC_INCIDENT_CORPUS_V4,
)
from public_incident_replay import (
    EXPECTED_ALLOW,
    EXPECTED_BLOCK,
    PUBLIC_INCIDENT_REPLAY_FIXTURES_V1,
    PUBLIC_INCIDENT_REPLAY_FIXTURES_V2,
    PUBLIC_INCIDENT_REPLAY_FIXTURES_V3,
    PUBLIC_INCIDENT_REPLAY_FIXTURES_V4,
    main,
    run_public_incident_replay,
)


def test_versioned_fixture_sets_are_preserved():
    assert len(PUBLIC_INCIDENT_CORPUS_V1) == 3
    assert len(PUBLIC_INCIDENT_REPLAY_FIXTURES_V1) == 3
    assert len(PUBLIC_INCIDENT_CORPUS_V2) == 6
    assert len(PUBLIC_INCIDENT_REPLAY_FIXTURES_V2) == 6
    assert len(PUBLIC_INCIDENT_CORPUS_V3) == 9
    assert len(PUBLIC_INCIDENT_REPLAY_FIXTURES_V3) == 9


def test_v4_replay_fixture_covers_every_public_incident():
    corpus_ids = {incident.case_id for incident in PUBLIC_INCIDENT_CORPUS_V4}
    replay_ids = {fixture.case_id for fixture in PUBLIC_INCIDENT_REPLAY_FIXTURES_V4}
    assert replay_ids == corpus_ids


def test_fixture_expected_decisions_match_v4_corpus_contract():
    expected = {
        incident.case_id: incident.expected_decision
        for incident in PUBLIC_INCIDENT_CORPUS_V4
    }
    for fixture in PUBLIC_INCIDENT_REPLAY_FIXTURES_V4:
        assert fixture.expected_decision == expected[fixture.case_id]


def test_public_incident_replay_gate_has_no_authorization_errors():
    summary = run_public_incident_replay()

    assert summary.coverage == 1.0
    assert summary.false_allows == 0
    assert summary.false_blocks == 0
    assert summary.missing_case_ids == ()
    assert summary.gate_passed is True


def test_known_block_cases_remain_blocked():
    summary = run_public_incident_replay()
    blocked = [
        result for result in summary.results
        if result.expected_decision == EXPECTED_BLOCK
    ]

    assert len(blocked) == 5
    assert all(result.actual_decision == EXPECTED_BLOCK for result in blocked)


def test_original_runner_shutdown_counterexamples_remain_conservative():
    summary = run_public_incident_replay()
    original_ids = {case.case_id for case in PUBLIC_INCIDENT_CORPUS_V1}
    original = [result for result in summary.results if result.case_id in original_ids]

    assert len(original) == 3
    for result in original:
        assert result.category == "RUNNER_INFRA"
        assert result.confidence != "high"
        assert result.actual_decision == EXPECTED_BLOCK


def test_v4_positive_controls_are_allowed():
    summary = run_public_incident_replay()
    allowed = [
        result for result in summary.results
        if result.expected_decision == EXPECTED_ALLOW
    ]

    assert len(allowed) == 4
    assert {result.repository for result in allowed} == {
        "alunduil/alunduil-chezmoi",
        "vtmocanu/uzi",
        "docker/compose",
        "alethialabs-io/alethialabs",
    }
    for result in allowed:
        assert result.actual_decision == EXPECTED_ALLOW
        assert result.evidence_status == "SUFFICIENT"
        assert result.confidence == "high"
        assert result.provenance_status == "CONFIRMED"


def test_log_positive_controls_use_real_failed_step_metadata():
    positive = [
        fixture
        for fixture in PUBLIC_INCIDENT_REPLAY_FIXTURES_V4
        if fixture.expected_decision == EXPECTED_ALLOW
        and fixture.check_run is None
    ]

    assert len(positive) == 4
    for fixture in positive:
        assert fixture.source_job is not None
        failed_steps = [
            step for step in fixture.source_job.get("steps", [])
            if step.get("conclusion") == "failure"
        ]
        assert len(failed_steps) == 1
        assert failed_steps[0]["name"] == fixture.failed_step_name


def test_prql_runner_loss_annotation_confirms_provenance_but_side_effect_still_blocks():
    summary = run_public_incident_replay()
    result = next(
        item for item in summary.results
        if item.case_id == "prql-hosted-runner-loss-2026-08-26"
    )
    fixture = next(
        item for item in PUBLIC_INCIDENT_REPLAY_FIXTURES_V4
        if item.case_id == result.case_id
    )

    assert fixture.check_run is not None
    assert fixture.source_job is not None
    assert fixture.source_job["check_run_url"].endswith("/check-runs/98152972844")
    assert result.category == "RUNNER_INFRA"
    assert result.confidence == "high"
    assert result.provenance_status == "CONFIRMED"
    assert result.evidence_status == "CONTRADICTED"
    assert result.actual_decision == EXPECTED_BLOCK


def test_v3_prql_contract_remains_fail_closed_before_annotation_path():
    case = next(
        item for item in PUBLIC_INCIDENT_CORPUS_V3
        if item.case_id == "prql-hosted-runner-loss-2026-08-26"
    )
    assert case.expected_decision == EXPECTED_BLOCK


def test_persistent_rate_limit_case_remains_blocked():
    summary = run_public_incident_replay()
    result = next(
        item for item in summary.results
        if item.case_id == "hiromi-github-rate-limit-recurrence-2026-09-26"
    )
    assert result.actual_decision == EXPECTED_BLOCK


def test_replay_check_cli_passes_authenticated_annotation_corpus(capsys):
    exit_code = main(["--check"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Public Incident Replay Gate v4" in output
    assert "cases: 9/9" in output
    assert "coverage: 100%" in output
    assert "false ALLOW: 0" in output
    assert "false BLOCK: 0" in output
    assert "gate: PASS" in output
