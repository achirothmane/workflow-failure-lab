from public_incident_corpus import PUBLIC_INCIDENT_CORPUS_V1
from public_incident_replay import (
    EXPECTED_BLOCK,
    PUBLIC_INCIDENT_REPLAY_FIXTURES_V1,
    main,
    run_public_incident_replay,
)


def test_replay_fixture_covers_every_public_incident():
    corpus_ids = {incident.case_id for incident in PUBLIC_INCIDENT_CORPUS_V1}
    replay_ids = {fixture.case_id for fixture in PUBLIC_INCIDENT_REPLAY_FIXTURES_V1}

    assert replay_ids == corpus_ids


def test_public_incident_replay_gate_has_no_false_allow():
    summary = run_public_incident_replay()

    assert summary.coverage == 1.0
    assert summary.false_allows == 0
    assert summary.missing_case_ids == ()
    assert summary.gate_passed is True


def test_current_v1_ground_truth_cases_remain_blocked():
    summary = run_public_incident_replay()

    assert summary.results
    for result in summary.results:
        assert result.expected_decision == EXPECTED_BLOCK
        assert result.actual_decision == EXPECTED_BLOCK


def test_runner_shutdown_counterexamples_do_not_reach_high_confidence():
    summary = run_public_incident_replay()

    for result in summary.results:
        assert result.category == "RUNNER_INFRA"
        assert result.confidence != "high"


def test_replay_check_cli_passes_current_corpus(capsys):
    exit_code = main(["--check"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "coverage: 100%" in output
    assert "false ALLOW: 0" in output
    assert "gate: PASS" in output
