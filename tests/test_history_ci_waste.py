from recovery_ground_truth import (
    RECOVERY_NOT_OBSERVED,
    RECOVERY_NOT_RECOVERED,
    RECOVERY_VALIDATED,
)

from history_ci_waste import (
    POLICY_AUTO_RERUN_ONCE,
    POLICY_DO_NOT_AUTO_RERUN,
    POLICY_MANUAL_REVIEW,
    FingerprintSummary,
    HistoricalFailure,
    _later_rerun_outcome,
    failure_fingerprint,
    normalize_signature_line,
    recommend_policy,
    render_history_report,
    summarize_history,
)


def failure(
    run_id,
    job,
    category,
    confidence,
    minutes,
    *,
    fingerprint="",
    signature="",
    recovered=False,
    rerun=False,
    side_effect=False,
    attempt=1,
    recovery_status=None,
):
    if recovery_status is None:
        if not rerun:
            recovery_status = RECOVERY_NOT_OBSERVED
        elif recovered:
            recovery_status = RECOVERY_VALIDATED
        else:
            recovery_status = RECOVERY_NOT_RECOVERED
    return HistoricalFailure(
        run_id=run_id,
        job_name=job,
        category=category,
        confidence=confidence,
        duration_minutes=minutes,
        fingerprint=fingerprint,
        signature=signature,
        recovered_after_rerun=recovered,
        rerun_observed=rerun,
        side_effect_risk=side_effect,
        attempt=attempt,
        recovery_status=recovery_status,
    )


def fp_summary(
    *,
    category="DEPENDENCY_NETWORK",
    occurrences=5,
    reruns=5,
    recoveries=4,
    high_confidence=5,
    side_effect=False,
):
    return FingerprintSummary(
        fingerprint="FG-TEST",
        job_name="install dependencies",
        category=category,
        signature="npm err code etimedout",
        occurrences=occurrences,
        failed_minutes=10.0,
        rerun_observations=reruns,
        rerun_recoveries=recoveries,
        high_confidence_occurrences=high_confidence,
        side_effect_seen=side_effect,
        validated_rerun_observations=reruns,
        validated_rerun_recoveries=recoveries,
    )


def test_transient_waste_only_counts_high_confidence_transient_failures():
    summary = summarize_history(
        [
            failure(1, "tests", "DEPENDENCY_NETWORK", "high", 4.0),
            failure(2, "tests", "RUNNER_INFRA", "high", 3.5),
            failure(3, "tests", "CODE_REGRESSION", "high", 6.0),
            failure(4, "tests", "DEPENDENCY_NETWORK", "medium", 2.0),
        ],
        runs_analyzed=4,
    )

    assert summary.failed_minutes == 15.5
    assert summary.transient_waste_minutes == 7.5


def test_recurring_failure_requires_same_job_and_category_twice():
    summary = summarize_history(
        [
            failure(1, "tests", "DEPENDENCY_NETWORK", "high", 4.0),
            failure(2, "tests", "DEPENDENCY_NETWORK", "high", 5.0),
            failure(3, "tests", "CODE_REGRESSION", "high", 6.0),
            failure(4, "lint", "DEPENDENCY_NETWORK", "high", 2.0),
        ],
        runs_analyzed=4,
    )

    assert len(summary.recurring) == 1
    recurring = summary.recurring[0]
    assert recurring.job_name == "tests"
    assert recurring.category == "DEPENDENCY_NETWORK"
    assert recurring.occurrences == 2
    assert recurring.failed_minutes == 9.0


def test_recurring_failures_are_sorted_by_occurrences_then_minutes():
    summary = summarize_history(
        [
            failure(1, "install", "DEPENDENCY_NETWORK", "high", 1.0),
            failure(2, "install", "DEPENDENCY_NETWORK", "high", 1.0),
            failure(3, "tests", "RUNNER_INFRA", "high", 4.0),
            failure(4, "tests", "RUNNER_INFRA", "high", 5.0),
            failure(5, "tests", "RUNNER_INFRA", "high", 6.0),
        ],
        runs_analyzed=5,
    )

    assert summary.recurring[0].job_name == "tests"
    assert summary.recurring[0].occurrences == 3
    assert summary.recurring[1].job_name == "install"


def test_signature_normalization_ignores_dynamic_numbers_ips_and_hex_ids():
    first = normalize_signature_line(
        "2026-09-17T08:00:01Z connect ETIMEDOUT 104.20.22.46 request abcdef1234567890 after 1500 ms"
    )
    second = normalize_signature_line(
        "2026-09-18T09:11:12Z connect ETIMEDOUT 172.18.0.2 request 999999abcdefaaaa after 3000 ms"
    )

    assert first == second
    assert "<ip>" in first
    assert "<hex>" in first
    assert "<n>" in first


def test_same_failure_with_dynamic_values_gets_same_fingerprint():
    fp1, signature1 = failure_fingerprint(
        "install dependencies",
        "DEPENDENCY_NETWORK",
        (
            "npm ERR! code ETIMEDOUT",
            "connect ETIMEDOUT 104.20.22.46:443 after 1500 ms",
        ),
    )
    fp2, signature2 = failure_fingerprint(
        "install dependencies",
        "DEPENDENCY_NETWORK",
        (
            "npm ERR! code ETIMEDOUT",
            "connect ETIMEDOUT 172.18.0.2:443 after 3000 ms",
        ),
    )

    assert fp1 == fp2
    assert signature1 == signature2
    assert fp1.startswith("FG-")


def test_different_failure_evidence_gets_different_fingerprint():
    network_fp, _ = failure_fingerprint(
        "tests", "DEPENDENCY_NETWORK", ("connection reset by peer",)
    )
    runner_fp, _ = failure_fingerprint(
        "tests", "RUNNER_INFRA", ("runner disconnected unexpectedly",)
    )

    assert network_fp != runner_fp


def test_fingerprint_summary_counts_real_reruns_and_recoveries():
    fp, signature = failure_fingerprint(
        "install dependencies",
        "DEPENDENCY_NETWORK",
        ("npm ERR! code ETIMEDOUT", "connection reset by peer"),
    )
    summary = summarize_history(
        [
            failure(
                1,
                "install dependencies",
                "DEPENDENCY_NETWORK",
                "high",
                4.0,
                fingerprint=fp,
                signature=signature,
                recovered=True,
                rerun=True,
            ),
            failure(
                2,
                "install dependencies",
                "DEPENDENCY_NETWORK",
                "high",
                5.5,
                fingerprint=fp,
                signature=signature,
                recovered=False,
                rerun=True,
            ),
        ],
        runs_analyzed=2,
    )

    assert len(summary.fingerprints) == 1
    item = summary.fingerprints[0]
    assert item.fingerprint == fp
    assert item.occurrences == 2
    assert item.failed_minutes == 9.5
    assert item.rerun_observations == 2
    assert item.rerun_recoveries == 1
    assert item.rerun_recovery_rate == 0.5
    assert item.high_confidence_rate == 1.0
    assert item.validated_rerun_observations == 2
    assert item.validated_rerun_recoveries == 1
    assert item.ground_truth_recovery_rate == 0.5
    assert summary.rerun_recoveries == 1
    assert summary.validated_rerun_recoveries == 1


def test_copied_untouched_job_is_not_counted_as_real_rerun():
    attempts = {
        1: [
            {
                "name": "code-regression",
                "started_at": "2026-09-17T08:51:54Z",
                "conclusion": "failure",
            }
        ],
        2: [
            {
                "name": "code-regression",
                "started_at": "2026-09-17T08:51:54Z",
                "conclusion": "failure",
            }
        ],
    }

    observed, recovered = _later_rerun_outcome(
        attempts,
        current_attempt=1,
        attempts=2,
        job_name="code-regression",
        original_started_at="2026-09-17T08:51:54Z",
    )

    assert observed is False
    assert recovered is False


def test_later_job_with_new_start_time_is_real_rerun_and_recovery():
    attempts = {
        1: [],
        2: [
            {
                "name": "install",
                "started_at": "2026-09-17T08:52:16Z",
                "conclusion": "success",
            }
        ],
    }

    observed, recovered = _later_rerun_outcome(
        attempts,
        current_attempt=1,
        attempts=2,
        job_name="install",
        original_started_at="2026-09-17T08:51:55Z",
    )

    assert observed is True
    assert recovered is True


def test_policy_auto_rerun_once_requires_five_samples_and_80_percent_recovery():
    policy = recommend_policy(fp_summary(reruns=5, recoveries=4))

    assert policy.policy == POLICY_AUTO_RERUN_ONCE
    assert policy.recovery_rate == 0.8


def test_policy_stays_manual_with_too_few_rerun_samples():
    policy = recommend_policy(fp_summary(occurrences=4, reruns=4, recoveries=4, high_confidence=4))

    assert policy.policy == POLICY_MANUAL_REVIEW
    assert "at least 5" in policy.reason


def test_policy_blocks_code_regression_even_when_reruns_recovered():
    policy = recommend_policy(
        fp_summary(category="CODE_REGRESSION", reruns=5, recoveries=5)
    )

    assert policy.policy == POLICY_DO_NOT_AUTO_RERUN


def test_policy_blocks_any_fingerprint_with_side_effect_history():
    policy = recommend_policy(fp_summary(side_effect=True, reruns=10, recoveries=10))

    assert policy.policy == POLICY_DO_NOT_AUTO_RERUN
    assert "side-effect" in policy.reason


def test_policy_blocks_transient_fingerprint_with_very_low_recovery():
    policy = recommend_policy(fp_summary(reruns=5, recoveries=1))

    assert policy.policy == POLICY_DO_NOT_AUTO_RERUN
    assert policy.recovery_rate == 0.2


def test_policy_requires_high_confidence_history():
    policy = recommend_policy(
        fp_summary(occurrences=10, reruns=10, recoveries=9, high_confidence=7)
    )

    assert policy.policy == POLICY_MANUAL_REVIEW
    assert "High-confidence" in policy.reason


def test_report_contains_policy_recommendation():
    fp, signature = failure_fingerprint(
        "install",
        "DEPENDENCY_NETWORK",
        ("npm ERR! code ETIMEDOUT", "connection reset by peer"),
    )
    records = [
        failure(
            i,
            "install",
            "DEPENDENCY_NETWORK",
            "high",
            2.0,
            fingerprint=fp,
            signature=signature,
            recovered=i <= 4,
            rerun=True,
        )
        for i in range(1, 6)
    ]
    summary = summarize_history(records, runs_analyzed=5)
    report = render_history_report(summary)

    assert "Policy Learning" in report
    assert POLICY_AUTO_RERUN_ONCE in report
    assert "4/5" in report


def test_report_labels_failed_runtime_separately_from_transient_waste():
    summary = summarize_history(
        [
            failure(1, "tests", "CODE_REGRESSION", "high", 6.0),
            failure(2, "install", "DEPENDENCY_NETWORK", "high", 4.0),
            failure(3, "install", "DEPENDENCY_NETWORK", "high", 5.0),
        ],
        runs_analyzed=3,
    )
    report = render_history_report(summary)

    assert "Historical failed-job runtime: **15.00 min**" in report
    assert "High-confidence transient CI waste: **9.00 min**" in report
    assert "Failed-job runtime is not automatically waste" in report


def test_empty_history_is_valid():
    summary = summarize_history([], runs_analyzed=0)

    assert summary.failed_minutes == 0
    assert summary.transient_waste_minutes == 0
    assert summary.recurring == ()
    assert summary.fingerprints == ()
    assert summary.policies == ()
    assert summary.rerun_recoveries == 0
