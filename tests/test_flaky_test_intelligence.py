import pytest

from flaky_test_intelligence import (
    DO_NOT_QUARANTINE,
    FAIL,
    INVESTIGATE,
    PASS,
    QUARANTINE_CANDIDATE,
    CaseObservation,
    observations_from_junit,
    summarize_flaky_tests,
)


def obs(test_id, sha, run_id, attempt, status, seconds):
    return CaseObservation(
        test_id=test_id,
        sha=sha,
        run_id=run_id,
        attempt=attempt,
        status=status,
        duration_seconds=seconds,
    )


def test_junit_parser_extracts_pass_failure_error_and_skips_skipped():
    xml = """
    <testsuite>
      <testcase classname="pkg.TestMath" name="test_ok" time="1.2" />
      <testcase classname="pkg.TestMath" name="test_fail" time="2.0">
        <failure message="boom" />
      </testcase>
      <testcase classname="pkg.TestMath" name="test_error" time="3.0">
        <error message="broken" />
      </testcase>
      <testcase classname="pkg.TestMath" name="test_skip" time="4.0">
        <skipped />
      </testcase>
    </testsuite>
    """
    items = observations_from_junit(
        xml,
        sha="abc",
        run_id=10,
        attempt=2,
    )

    assert [(item.test_id, item.status) for item in items] == [
        ("pkg.TestMath::test_ok", PASS),
        ("pkg.TestMath::test_fail", FAIL),
        ("pkg.TestMath::test_error", FAIL),
    ]


def test_two_same_sha_recoveries_create_quarantine_candidate():
    items = [
        obs("test_checkout", "sha-a", 1, 1, FAIL, 30),
        obs("test_checkout", "sha-a", 1, 2, PASS, 28),
        obs("test_checkout", "sha-b", 2, 1, FAIL, 32),
        obs("test_checkout", "sha-b", 2, 2, PASS, 29),
    ]

    summary = summarize_flaky_tests(items)[0]

    assert summary.validated_recoveries == 2
    assert summary.same_sha_flips == 2
    assert summary.persistent_failure_shas == 0
    assert summary.recommendation == QUARANTINE_CANDIDATE
    assert summary.estimated_waste_seconds == 119


def test_persistent_failure_blocks_quarantine_even_with_prior_recoveries():
    items = [
        obs("test_payments", "sha-a", 1, 1, FAIL, 10),
        obs("test_payments", "sha-a", 1, 2, PASS, 9),
        obs("test_payments", "sha-b", 2, 1, FAIL, 10),
        obs("test_payments", "sha-b", 2, 2, PASS, 9),
        obs("test_payments", "sha-c", 3, 1, FAIL, 10),
    ]

    summary = summarize_flaky_tests(items)[0]

    assert summary.validated_recoveries == 2
    assert summary.persistent_failure_shas == 1
    assert summary.recommendation == DO_NOT_QUARANTINE
    assert "real regression" in summary.reason


def test_single_recovery_is_only_investigate():
    items = [
        obs("test_login", "same-sha", 1, 1, FAIL, 5),
        obs("test_login", "same-sha", 1, 2, PASS, 4),
    ]

    summary = summarize_flaky_tests(items)[0]

    assert summary.recommendation == INVESTIGATE


def test_code_change_pass_does_not_count_as_validated_recovery():
    items = [
        obs("test_profile", "old-sha", 1, 1, FAIL, 12),
        obs("test_profile", "new-sha", 2, 1, PASS, 11),
    ]

    summary = summarize_flaky_tests(items)[0]

    assert summary.validated_recoveries == 0
    assert summary.persistent_failure_shas == 1
    assert summary.recommendation == DO_NOT_QUARANTINE


def test_rank_by_estimated_waste():
    items = [
        obs("fast_flake", "a", 1, 1, FAIL, 1),
        obs("fast_flake", "a", 1, 2, PASS, 1),
        obs("slow_flake", "b", 2, 1, FAIL, 50),
        obs("slow_flake", "b", 2, 2, PASS, 40),
    ]

    summaries = summarize_flaky_tests(items)

    assert [item.test_id for item in summaries] == [
        "slow_flake",
        "fast_flake",
    ]


def test_invalid_observation_fails_closed():
    with pytest.raises(ValueError):
        summarize_flaky_tests(
            [obs("test_x", "sha", 1, 1, "unknown", 1)]
        )


def test_fail_and_pass_in_same_execution_do_not_prove_recovery():
    items = [
        obs("test_duplicate", "same-sha", 1, 1, FAIL, 5),
        obs("test_duplicate", "same-sha", 1, 1, PASS, 4),
    ]

    summary = summarize_flaky_tests(items)[0]

    assert summary.validated_recoveries == 0
    assert summary.same_sha_flips == 0
    assert summary.persistent_failure_shas == 1
    assert summary.recommendation == DO_NOT_QUARANTINE


def test_junit_parser_captures_optional_source_file_for_ownership():
    xml = """
    <testsuite>
      <testcase classname="pkg.TestCart" name="test_total" time="1.0" file="tests/test_cart.py">
        <failure message="boom" />
      </testcase>
    </testsuite>
    """
    items = observations_from_junit(
        xml,
        sha="abc",
        run_id=10,
    )

    assert items[0].source_file == "tests/test_cart.py"
