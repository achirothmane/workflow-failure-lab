from classifier_rule_research import (
    PROPOSED_CATEGORY,
    RULE_SERVER_5XX_CAUSAL_UNKNOWN,
    evaluate_server5xx_shadow_rule,
    render_server5xx_rule_research,
)
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


def failure(
    run_id: int,
    *,
    category: str = "UNKNOWN",
    causal: bool = True,
    reason: str = "SERVER_5XX",
    recovery_status: str = RECOVERY_VALIDATED,
    side_effect: bool = False,
    signature: str = "error: unexpected http response: <n>",
) -> HistoricalFailure:
    return HistoricalFailure(
        run_id=run_id,
        job_name="build",
        category=category,
        confidence="low",
        duration_minutes=1.0,
        signature=signature,
        recovery_status=recovery_status,
        side_effect_risk=side_effect,
        mechanism_causality_status=(
            MECHANISM_CAUSAL_CONFIRMED if causal else MECHANISM_CAUSAL_UNCONFIRMED
        ),
        mechanism_causality_reasons=(reason,) if causal else (),
        mechanism_causal_evidence=("Error: HTTP 503 Service Unavailable",) if causal else (),
    )


def test_shadow_rule_matches_only_unknown_causal_server_5xx():
    natural = {
        "acme/repo": (
            [
                failure(1),
                failure(2, category="DEPENDENCY_NETWORK"),
                failure(3, causal=False),
                failure(4, reason="CONNECTION_RESET"),
            ],
            4,
        )
    }

    summary = evaluate_server5xx_shadow_rule(natural, {})

    assert summary.rule_name == RULE_SERVER_5XX_CAUSAL_UNKNOWN
    assert summary.proposed_category == PROPOSED_CATEGORY
    assert summary.natural_unknown_failures == 3
    assert len(summary.natural_matches) == 1
    assert summary.natural_match_rate == 1 / 3


def test_shadow_rule_precision_uses_only_ground_truth_evaluable_matches():
    rerun = {
        "acme/repo": (
            [
                failure(101, recovery_status=RECOVERY_VALIDATED),
                failure(202, recovery_status=RECOVERY_NOT_RECOVERED),
                failure(303, recovery_status=RECOVERY_NOT_OBSERVED),
            ],
            3,
        )
    }

    summary = evaluate_server5xx_shadow_rule({}, rerun)

    assert len(summary.rerun_matches) == 3
    assert summary.evaluable_matches == 2
    assert summary.validated_recoveries == 1
    assert summary.failed_again == 1
    assert summary.unknown_outcomes == 1
    assert summary.observed_precision == 0.5
    assert len(summary.false_positive_matches) == 1
    assert summary.false_positive_matches[0].run_id == 202


def test_side_effect_is_authority_signal_not_classifier_false_positive():
    rerun = {
        "acme/repo": (
            [
                failure(101, side_effect=True),
                failure(202, side_effect=False),
            ],
            2,
        )
    }

    summary = evaluate_server5xx_shadow_rule({}, rerun)

    assert summary.evaluable_matches == 2
    assert summary.validated_recoveries == 2
    assert summary.observed_precision == 1.0
    assert summary.side_effect_matches == 1
    assert summary.authority_safe_matches == 1
    assert summary.authority_blocked_matches == 1
    assert summary.false_positive_matches == ()


def test_shadow_rule_tracks_independent_runs_and_repositories():
    rerun = {
        "acme/repo": ([failure(101), failure(101)], 2),
        "other/project": ([failure(202)], 1),
    }

    summary = evaluate_server5xx_shadow_rule({}, rerun)

    assert summary.evaluable_matches == 3
    assert summary.independent_runs == 2
    assert summary.independent_repositories == 2
    assert summary.run_ids == (101, 202)
    assert summary.repositories == ("acme/repo", "other/project")


def test_shadow_rule_report_states_no_runtime_authority():
    summary = evaluate_server5xx_shadow_rule(
        {},
        {"acme/repo": ([failure(101)], 1)},
    )

    report = render_server5xx_rule_research(summary)

    assert "Shadow-only classifier hypothesis" in report
    assert "does not modify classify_log()" in report
    assert "does not grant rerun authority" in report
    assert "Observed classifier-hypothesis precision: **100.00%**" in report
