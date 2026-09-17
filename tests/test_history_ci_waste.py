from history_ci_waste import (
    HistoricalFailure,
    failure_fingerprint,
    normalize_signature_line,
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
    attempt=1,
):
    return HistoricalFailure(
        run_id=run_id,
        job_name=job,
        category=category,
        confidence=confidence,
        duration_minutes=minutes,
        fingerprint=fingerprint,
        signature=signature,
        recovered_after_rerun=recovered,
        attempt=attempt,
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


def test_fingerprint_summary_counts_occurrences_minutes_and_rerun_recoveries():
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
            ),
        ],
        runs_analyzed=2,
    )

    assert len(summary.fingerprints) == 1
    item = summary.fingerprints[0]
    assert item.fingerprint == fp
    assert item.occurrences == 2
    assert item.failed_minutes == 9.5
    assert item.rerun_recoveries == 1
    assert item.rerun_recovery_rate == 0.5
    assert summary.rerun_recoveries == 1


def test_report_contains_recurring_fingerprint_and_recovery_count():
    fp, signature = failure_fingerprint(
        "install",
        "DEPENDENCY_NETWORK",
        ("npm ERR! code ETIMEDOUT", "connection reset by peer"),
    )
    summary = summarize_history(
        [
            failure(1, "install", "DEPENDENCY_NETWORK", "high", 4.0, fingerprint=fp, signature=signature, recovered=True),
            failure(2, "install", "DEPENDENCY_NETWORK", "high", 5.0, fingerprint=fp, signature=signature, recovered=True),
        ],
        runs_analyzed=2,
    )
    report = render_history_report(summary)

    assert "Recurring failure fingerprints" in report
    assert fp in report
    assert "Failures recovered by a later rerun: **2**" in report
    assert "| 2 | 2 | 9.00 min |" in report


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
    assert summary.rerun_recoveries == 0
