from datetime import datetime, timezone

import pytest

from flaky_quarantine_lifecycle import (
    ACTIVE,
    BLOCKED_REGRESSION,
    EXPIRED,
    RELEASED_HEALTHY,
    QuarantineEntry,
    clean_revision_streak,
    evaluate_lifecycle,
    load_manifest,
)
from flaky_test_intelligence import (
    FAIL,
    PASS,
    QUARANTINE_CANDIDATE,
    CaseObservation,
    FlakyTestSummary,
)


NOW = datetime(2026, 9, 19, 13, 0, tzinfo=timezone.utc)


def candidate(test_id="pkg.TestCart::test_total", persistent=0):
    return FlakyTestSummary(
        test_id=test_id,
        observations=4,
        failures=2,
        passes=2,
        same_sha_flips=2,
        validated_recoveries=2,
        persistent_failure_shas=persistent,
        failed_seconds=20,
        recovery_seconds=18,
        estimated_waste_seconds=38,
        recommendation=(
            QUARANTINE_CANDIDATE
            if persistent == 0
            else "DO_NOT_QUARANTINE"
        ),
        reason="evidence",
    )


def entry(
    *,
    test_id="pkg.TestCart::test_total",
    expires="2026-09-30T00:00:00Z",
    activated_run_id=100,
):
    return QuarantineEntry(
        test_id=test_id,
        approved_by="maintainer",
        approved_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
        activated_run_id=activated_run_id,
        expires_at=datetime.fromisoformat(expires.replace("Z", "+00:00")),
        reason="approved in review",
    )


def obs(sha, run_id, status):
    return CaseObservation(
        test_id="pkg.TestCart::test_total",
        sha=sha,
        run_id=run_id,
        attempt=1,
        status=status,
        duration_seconds=1,
    )


def test_manifest_requires_explicit_approval_and_bounded_expiry():
    text = """
    {
      "version": 1,
      "entries": [
        {
          "test_id": "pkg.TestCart::test_total",
          "approved_by": "alice",
          "approved_at": "2026-09-18T00:00:00Z",
          "activated_run_id": 100,
          "expires_at": "2026-09-25T00:00:00Z",
          "reason": "reviewed in PR"
        }
      ]
    }
    """
    entries = load_manifest(text, max_days=14)

    assert len(entries) == 1
    assert entries[0].approved_by == "alice"

    too_long = text.replace(
        "2026-09-25T00:00:00Z",
        "2026-10-20T00:00:00Z",
    )
    with pytest.raises(ValueError):
        load_manifest(too_long, max_days=14)


def test_candidate_with_valid_approval_becomes_active():
    result = evaluate_lifecycle(
        (entry(),),
        (candidate(),),
        (),
        now=NOW,
        release_clean_shas=3,
    )

    assert result.decisions[0].state == ACTIVE
    assert len(result.active) == 1


def test_expired_entry_is_not_active():
    result = evaluate_lifecycle(
        (entry(expires="2026-09-19T12:00:00Z"),),
        (candidate(),),
        (),
        now=NOW,
        release_clean_shas=3,
    )

    assert result.decisions[0].state == EXPIRED
    assert not result.active


def test_persistent_failure_suspends_quarantine():
    result = evaluate_lifecycle(
        (entry(),),
        (candidate(persistent=1),),
        (),
        now=NOW,
        release_clean_shas=3,
    )

    assert result.decisions[0].state == BLOCKED_REGRESSION
    assert not result.active


def test_three_clean_later_revisions_auto_release():
    observations = (
        obs("sha-a", 101, PASS),
        obs("sha-b", 102, PASS),
        obs("sha-c", 103, PASS),
    )

    assert clean_revision_streak(
        "pkg.TestCart::test_total",
        observations,
        after_run_id=100,
    ) == 3

    result = evaluate_lifecycle(
        (entry(),),
        (candidate(),),
        observations,
        now=NOW,
        release_clean_shas=3,
    )

    assert result.decisions[0].state == RELEASED_HEALTHY
    assert len(result.released) == 1
    assert not result.active


def test_latest_failed_revision_breaks_clean_streak():
    observations = (
        obs("sha-a", 101, PASS),
        obs("sha-b", 102, PASS),
        obs("sha-c", 103, FAIL),
    )

    assert clean_revision_streak(
        "pkg.TestCart::test_total",
        observations,
        after_run_id=100,
    ) == 0


def test_mixed_pass_fail_same_revision_is_not_clean():
    observations = (
        obs("sha-a", 101, PASS),
        CaseObservation(
            test_id="pkg.TestCart::test_total",
            sha="sha-a",
            run_id=101,
            attempt=2,
            status=FAIL,
            duration_seconds=1,
        ),
    )

    assert clean_revision_streak(
        "pkg.TestCart::test_total",
        observations,
        after_run_id=100,
    ) == 0
