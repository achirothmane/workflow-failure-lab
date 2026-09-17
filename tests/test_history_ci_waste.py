from history_ci_waste import HistoricalFailure, render_history_report, summarize_history


def failure(run_id, job, category, confidence, minutes):
    return HistoricalFailure(
        run_id=run_id,
        job_name=job,
        category=category,
        confidence=confidence,
        duration_minutes=minutes,
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
    assert "`DEPENDENCY_NETWORK`" in report
    assert "Failed-job runtime is not automatically waste" in report


def test_empty_history_is_valid():
    summary = summarize_history([], runs_analyzed=0)

    assert summary.failed_minutes == 0
    assert summary.transient_waste_minutes == 0
    assert summary.recurring == ()
