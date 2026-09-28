from __future__ import annotations

from flaky_test_intelligence import FAIL, PASS, CaseObservation
from historical_flakiness_shadow import (
    CONTRADICTION,
    NOT_APPLICABLE,
    ORDERING_UNAVAILABLE,
    SUPPORT,
    compare_historical_flakiness_shadow,
)


def obs(test_id, sha, run_id, attempt, status, observed_at):
    return CaseObservation(
        test_id=test_id,
        sha=sha,
        run_id=run_id,
        attempt=attempt,
        status=status,
        duration_seconds=1.0,
        observed_at=observed_at,
    )


def compare(items, run_id=30, attempt=1, decision="BLOCK", evidence="UNKNOWN"):
    return compare_historical_flakiness_shadow(
        repo="owner/repo",
        run_id=run_id,
        run_attempt=attempt,
        observations=tuple(items),
        baseline_decision=decision,
        baseline_evidence_status=evidence,
    )


def test_unknown_baseline_gets_support_only_from_strictly_prior_recoveries():
    items = [
        obs("test_x", "a", 10, 1, FAIL, "2026-01-01T00:00:00Z"),
        obs("test_x", "a", 10, 2, PASS, "2026-01-01T00:00:00Z"),
        obs("test_x", "b", 20, 1, FAIL, "2026-01-02T00:00:00Z"),
        obs("test_x", "b", 20, 2, PASS, "2026-01-02T00:00:00Z"),
        obs("test_x", "c", 30, 1, FAIL, "2026-01-03T00:00:00Z"),
    ]
    result = compare(items)
    assert result["shadow"]["status"] == SUPPORT
    assert result["shadow"]["tests_with_historical_support"] == 1
    assert result["shadow"]["tests"][0]["validated_recoveries"] == 2
    assert result["authorization"]["changed"] is False


def test_persistent_prior_failure_is_contradiction():
    items = [
        obs("test_x", "a", 10, 1, FAIL, "2026-01-01T00:00:00Z"),
        obs("test_x", "a", 10, 2, PASS, "2026-01-01T00:00:00Z"),
        obs("test_x", "b", 20, 1, FAIL, "2026-01-02T00:00:00Z"),
        obs("test_x", "c", 30, 1, FAIL, "2026-01-03T00:00:00Z"),
    ]
    result = compare(items)
    assert result["shadow"]["status"] == CONTRADICTION


def test_future_observations_do_not_leak_into_support():
    items = [
        obs("test_x", "c", 30, 1, FAIL, "2026-01-03T00:00:00Z"),
        obs("test_x", "d", 40, 1, FAIL, "2026-01-04T00:00:00Z"),
        obs("test_x", "d", 40, 2, PASS, "2026-01-04T00:00:00Z"),
        obs("test_x", "e", 50, 1, FAIL, "2026-01-05T00:00:00Z"),
        obs("test_x", "e", 50, 2, PASS, "2026-01-05T00:00:00Z"),
    ]
    result = compare(items)
    assert result["shadow"]["tests_with_historical_support"] == 0
    assert result["authorization"]["changed"] is False


def test_missing_cross_run_timestamps_fail_closed():
    items = [
        obs("test_x", "a", 10, 1, FAIL, ""),
        obs("test_x", "a", 10, 2, PASS, ""),
        obs("test_x", "c", 30, 1, FAIL, "2026-01-03T00:00:00Z"),
    ]
    result = compare(items)
    assert result["shadow"]["status"] == ORDERING_UNAVAILABLE


def test_non_unknown_baseline_is_not_reinterpreted():
    items = [obs("test_x", "c", 30, 1, FAIL, "2026-01-03T00:00:00Z")]
    result = compare(items, decision="ALLOW", evidence="SUFFICIENT")
    assert result["shadow"]["status"] == NOT_APPLICABLE
    assert result["shadow"]["tests"] == []


def test_same_run_attempt_ordering_is_trusted():
    items = [
        obs("test_x", "same", 30, 1, FAIL, "2026-01-03T00:00:00Z"),
        obs("test_x", "same", 30, 2, FAIL, "2026-01-03T00:00:00Z"),
    ]
    result = compare(items, run_id=30, attempt=2)
    assert result["shadow"]["status"] != ORDERING_UNAVAILABLE
