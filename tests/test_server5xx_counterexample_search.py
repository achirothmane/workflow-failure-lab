from history_ci_waste import HistoricalFailure
from mechanism_causality_gate import (
    MECHANISM_CAUSAL_CONFIRMED,
    MECHANISM_CAUSAL_UNCONFIRMED,
)
from recovery_ground_truth import (
    RECOVERY_NOT_OBSERVED,
    RECOVERY_NOT_RECOVERED,
    RECOVERY_VALIDATED,
)
from server5xx_counterexample_search import (
    render_server5xx_counterexample_report,
    search_server5xx_counterexamples,
)


def failure(
    run_id: int,
    *,
    category: str = "UNKNOWN",
    confidence: str = "low",
    recovery_status: str = RECOVERY_VALIDATED,
    causal: bool = True,
    side_effect: bool = False,
    reason: str = "SERVER_5XX",
) -> HistoricalFailure:
    return HistoricalFailure(
        run_id=run_id,
        job_name="build",
        category=category,
        confidence=confidence,
        duration_minutes=1.0,
        signature="error: http <n> server error",
        recovery_status=recovery_status,
        side_effect_risk=side_effect,
        mechanism_causality_status=(
            MECHANISM_CAUSAL_CONFIRMED if causal else MECHANISM_CAUSAL_UNCONFIRMED
        ),
        mechanism_causality_reasons=(reason,) if causal else (),
        mechanism_causal_evidence=("Error: HTTP 503 Service Unavailable",) if causal else (),
    )


def test_counterexample_search_spans_all_runtime_categories():
    histories = {
        "acme/repo": (
            [
                failure(101, category="UNKNOWN"),
                failure(202, category="DEPENDENCY_NETWORK", confidence="high"),
                failure(303, category="CODE_REGRESSION", confidence="high"),
            ],
            3,
        )
    }

    summary = search_server5xx_counterexamples(histories)

    assert len(summary.matches) == 3
    assert dict(summary.category_counts) == {
        "CODE_REGRESSION": 1,
        "DEPENDENCY_NETWORK": 1,
        "UNKNOWN": 1,
    }
    assert len(summary.classification_contradictions) == 1
    assert summary.classification_contradictions[0].category == "CODE_REGRESSION"


def test_failed_again_is_strong_outcome_counterexample():
    histories = {
        "acme/repo": (
            [
                failure(101, recovery_status=RECOVERY_VALIDATED),
                failure(202, recovery_status=RECOVERY_NOT_RECOVERED),
            ],
            2,
        )
    }

    summary = search_server5xx_counterexamples(histories)

    assert len(summary.evaluable_matches) == 2
    assert summary.validated_recoveries == 1
    assert summary.failed_again == 1
    assert summary.observed_recovery_rate == 0.5
    assert summary.outcome_counterexamples[0].run_id == 202


def test_unverified_outcome_does_not_enter_recovery_denominator():
    histories = {
        "acme/repo": (
            [
                failure(101, recovery_status=RECOVERY_VALIDATED),
                failure(202, recovery_status=RECOVERY_NOT_OBSERVED),
            ],
            2,
        )
    }

    summary = search_server5xx_counterexamples(histories)

    assert len(summary.matches) == 2
    assert len(summary.evaluable_matches) == 1
    assert summary.unknown_outcomes == 1
    assert summary.observed_recovery_rate == 1.0


def test_side_effect_is_reported_separately_from_counterexample():
    histories = {
        "acme/repo": (
            [
                failure(101, side_effect=True),
                failure(202, side_effect=False),
            ],
            2,
        )
    }

    summary = search_server5xx_counterexamples(histories)

    assert summary.side_effect_matches == 1
    assert summary.failed_again == 0
    assert summary.classification_contradictions == ()


def test_noncausal_or_other_mechanism_is_excluded():
    histories = {
        "acme/repo": (
            [
                failure(101, causal=False),
                failure(202, reason="CONNECTION_RESET"),
            ],
            2,
        )
    }

    summary = search_server5xx_counterexamples(histories)

    assert summary.matches == ()
    assert summary.evaluable_matches == ()


def test_counterexample_report_is_explicitly_falsification_only():
    summary = search_server5xx_counterexamples(
        {
            "acme/repo": (
                [failure(101, recovery_status=RECOVERY_NOT_RECOVERED)],
                1,
            )
        }
    )

    report = render_server5xx_counterexample_report(summary)

    assert "SERVER_5XX Counterexample Search" in report
    assert "Failed again outcome counterexamples: **1**" in report
    assert "No classifier rule or rerun authority is changed" in report
    assert "strongest falsifier" in report
