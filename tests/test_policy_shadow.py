from history_ci_waste import HistoricalFailure, failure_fingerprint
from policy_shadow import (
    SHADOW_NOT_RECOVERED,
    SHADOW_RECOVERED,
    SHADOW_UNKNOWN,
    render_shadow_report,
    simulate_shadow,
)


def record(
    run_id,
    *,
    recovered=False,
    rerun=True,
    attempt=1,
    minutes=2.0,
    fingerprint="FG-TEST",
    category="DEPENDENCY_NETWORK",
    confidence="high",
    side_effect=False,
):
    return HistoricalFailure(
        run_id=run_id,
        job_name="install dependencies",
        category=category,
        confidence=confidence,
        duration_minutes=minutes,
        fingerprint=fingerprint,
        signature="npm err code etimedout",
        recovered_after_rerun=recovered,
        rerun_observed=rerun,
        side_effect_risk=side_effect,
        attempt=attempt,
    )


def test_shadow_uses_only_prior_samples_before_deciding():
    failures = [
        record(1, recovered=True),
        record(2, recovered=True),
        record(3, recovered=True),
        record(4, recovered=True),
        record(5, recovered=True),
        record(6, recovered=True),
    ]

    summary = simulate_shadow(failures)

    assert summary.decisions == 1
    assert summary.evaluated == 1
    assert summary.recoveries == 1
    assert summary.false_positives == 0
    assert summary.observed_precision == 1.0


def test_shadow_counts_failed_real_rerun_as_false_positive():
    failures = [
        record(1, recovered=True),
        record(2, recovered=True),
        record(3, recovered=True),
        record(4, recovered=True),
        record(5, recovered=True),
        record(6, recovered=False),
    ]

    summary = simulate_shadow(failures)

    assert summary.decisions == 1
    assert summary.evaluated == 1
    assert summary.recoveries == 0
    assert summary.false_positives == 1
    assert summary.observed_precision == 0.0


def test_shadow_keeps_unobserved_counterfactual_unknown():
    failures = [
        record(1, recovered=True),
        record(2, recovered=True),
        record(3, recovered=True),
        record(4, recovered=True),
        record(5, recovered=True),
        record(6, rerun=False, recovered=False),
    ]

    summary = simulate_shadow(failures)

    assert summary.decisions == 1
    assert summary.evaluated == 0
    assert summary.unknown_outcomes == 1
    assert summary.observed_precision == 0.0


def test_shadow_ignores_second_attempt_as_new_auto_rerun_once_decision():
    failures = [
        record(1, recovered=True),
        record(2, recovered=True),
        record(3, recovered=True),
        record(4, recovered=True),
        record(5, recovered=True),
        record(6, recovered=False, attempt=1),
        record(6, recovered=True, attempt=2),
    ]

    summary = simulate_shadow(failures)

    assert summary.decisions == 1


def test_shadow_does_not_simulate_code_regression_policy():
    failures = [
        record(i, recovered=True, category="CODE_REGRESSION")
        for i in range(1, 8)
    ]

    summary = simulate_shadow(failures)

    assert summary.decisions == 0


def test_shadow_reports_recoverable_failed_runtime_without_calling_it_saved_minutes():
    failures = [
        record(1, recovered=True),
        record(2, recovered=True),
        record(3, recovered=True),
        record(4, recovered=True),
        record(5, recovered=True),
        record(6, recovered=True, minutes=7.5),
    ]

    summary = simulate_shadow(failures)
    report = render_shadow_report(summary)

    assert summary.recoverable_failed_minutes == 7.5
    assert "Recoverable failed-job runtime" in report
    assert "not a claim of billed CI minutes saved" in report


def test_shadow_groups_multiple_fingerprints_separately():
    fp2, _ = failure_fingerprint(
        "runner tests", "RUNNER_INFRA", ("runner disconnected unexpectedly",)
    )
    failures = [record(i, recovered=True) for i in range(1, 7)]
    failures += [
        HistoricalFailure(
            run_id=100 + i,
            job_name="runner tests",
            category="RUNNER_INFRA",
            confidence="high",
            duration_minutes=3.0,
            fingerprint=fp2,
            signature="runner disconnected unexpectedly",
            recovered_after_rerun=True,
            rerun_observed=True,
            side_effect_risk=False,
            attempt=1,
        )
        for i in range(1, 7)
    ]

    summary = simulate_shadow(failures)

    assert summary.decisions == 2
    assert len(summary.fingerprints) == 2
