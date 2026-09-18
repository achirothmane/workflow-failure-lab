from history_ci_waste import HistoricalFailure
from mechanism_causality_gate import MECHANISM_CAUSAL_CONFIRMED, MECHANISM_CAUSAL_UNCONFIRMED
from recovery_ground_truth import RECOVERY_NOT_RECOVERED, RECOVERY_VALIDATED
from targeted_replication_search import search_targeted_replication


def failure(
    run_id: int,
    *,
    reason: str = "SERVER_5XX",
    recovered: bool = True,
    side_effect: bool = False,
    causal: bool = True,
    signature: str = "error: http 500 server error",
) -> HistoricalFailure:
    return HistoricalFailure(
        run_id=run_id,
        job_name="build",
        category="UNKNOWN",
        confidence="low",
        duration_minutes=1.0,
        signature=signature,
        side_effect_risk=side_effect,
        recovery_status=RECOVERY_VALIDATED if recovered else RECOVERY_NOT_RECOVERED,
        mechanism_causality_status=(
            MECHANISM_CAUSAL_CONFIRMED if causal else MECHANISM_CAUSAL_UNCONFIRMED
        ),
        mechanism_causality_reasons=(reason,),
        mechanism_causal_evidence=(f"Error: {reason}",),
    )


def test_targeted_search_deduplicates_independent_runs():
    histories = {
        "acme/repo": (
            [
                failure(101),
                failure(101, signature="error: http 500 from second job"),
                failure(202),
            ],
            3,
        )
    }

    summary = search_targeted_replication(histories, "SERVER_5XX")

    assert len(summary.matches) == 3
    assert summary.independent_runs == 2
    assert summary.run_ids == (101, 202)
    assert summary.replicated is True
    assert summary.independent_repositories == 1
    assert summary.cross_repository_replicated is False


def test_targeted_search_tracks_cross_repository_replication():
    histories = {
        "acme/repo": ([failure(101)], 1),
        "other/project": ([failure(202)], 1),
    }

    summary = search_targeted_replication(histories, "SERVER_5XX")

    assert summary.independent_runs == 2
    assert summary.independent_repositories == 2
    assert summary.repositories == ("acme/repo", "other/project")
    assert summary.cross_repository_replicated is True


def test_side_effect_matches_are_visible_but_not_usable_replication():
    histories = {
        "acme/repo": (
            [
                failure(101),
                failure(202, side_effect=True),
            ],
            2,
        )
    }

    summary = search_targeted_replication(histories, "SERVER_5XX")

    assert len(summary.matches) == 2
    assert len(summary.usable_matches) == 1
    assert summary.side_effect_contaminated == 1
    assert summary.independent_runs == 1
    assert summary.replicated is False


def test_wrong_or_uncausal_mechanisms_are_excluded():
    histories = {
        "acme/repo": (
            [
                failure(101, reason="TIMEOUT"),
                failure(202, causal=False),
            ],
            2,
        )
    }

    summary = search_targeted_replication(histories, "SERVER_5XX")

    assert summary.matches == ()
    assert summary.independent_runs == 0


def test_targeted_search_reports_ground_truth_outcomes():
    histories = {
        "acme/repo": (
            [
                failure(101, recovered=True),
                failure(202, recovered=False),
            ],
            2,
        )
    }

    summary = search_targeted_replication(histories, "SERVER_5XX")

    assert summary.validated_recoveries == 1
    assert summary.failed_again == 1
    assert summary.recovery_rate == 0.5
