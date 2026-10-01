from __future__ import annotations

from dataclasses import dataclass

from fleet_report import fleet_payload, render_fleet_report, summarize_fleet


@dataclass(frozen=True)
class Failure:
    category: str
    confidence: str
    provenance_status: str
    side_effect_risk: bool
    duration_minutes: float
    recovery_status: str


def test_summarize_fleet_separates_eligible_and_blocked_value():
    summary = summarize_fleet(
        "owner/repo",
        [
            Failure(
                "DEPENDENCY_NETWORK",
                "high",
                "CONFIRMED",
                False,
                4.5,
                "VALIDATED_RECOVERY",
            ),
            Failure(
                "RUNNER_INFRA",
                "high",
                "CONFIRMED",
                False,
                1.5,
                "NOT_RECOVERED",
            ),
            Failure(
                "CODE_REGRESSION",
                "high",
                "NOT_APPLICABLE",
                False,
                8.0,
                "NOT_OBSERVED",
            ),
            Failure(
                "UNKNOWN",
                "unknown",
                "UNAVAILABLE",
                False,
                2.0,
                "NOT_OBSERVED",
            ),
            Failure(
                "DEPENDENCY_NETWORK",
                "high",
                "CONFIRMED",
                True,
                3.0,
                "VALIDATED_RECOVERY",
            ),
        ],
        runs_analyzed=40,
    )

    assert summary.runs_analyzed == 40
    assert summary.failed_jobs == 5
    assert summary.rerun_eligible_jobs == 2
    assert summary.rerun_blocked_jobs == 3
    assert summary.observed_failed_minutes == 19.0
    assert summary.eligible_failed_minutes == 6.0
    assert summary.blocked_failed_minutes == 13.0
    assert summary.validated_candidate_recoveries == 1
    assert summary.candidate_failed_again == 1
    assert summary.candidate_unknown_outcomes == 0
    assert dict(summary.blocked_reasons) == {
        "CODE_REGRESSION": 1,
        "SIDE_EFFECT_BOUNDARY": 1,
        "UNKNOWN_CLASSIFICATION": 1,
    }


def test_payload_never_claims_saved_minutes():
    summary = summarize_fleet(
        "owner/repo",
        [
            Failure(
                "DEPENDENCY_NETWORK",
                "high",
                "CONFIRMED",
                False,
                4.5,
                "VALIDATED_RECOVERY",
            )
        ],
        runs_analyzed=10,
    )

    payload = fleet_payload(summary)

    assert payload["authority"] == "REPORT_ONLY"
    assert payload["minutes"]["claimed_saved"] is None
    assert payload["candidate_outcomes"]["observed_precision"] == 1.0


def test_unknown_candidate_outcome_stays_outside_precision():
    summary = summarize_fleet(
        "owner/repo",
        [
            Failure(
                "RUNNER_INFRA",
                "high",
                "CONFIRMED",
                False,
                2.0,
                "NOT_OBSERVED",
            )
        ],
        runs_analyzed=5,
    )

    payload = fleet_payload(summary)

    assert payload["candidate_outcomes"]["unknown"] == 1
    assert payload["candidate_outcomes"]["observed_precision"] is None


def test_report_is_operator_readable_and_explicitly_read_only():
    summary = summarize_fleet(
        "owner/repo",
        [
            Failure(
                "EVIDENCE_UNAVAILABLE",
                "none",
                "UNAVAILABLE",
                False,
                3.0,
                "NOT_OBSERVED",
            )
        ],
        runs_analyzed=7,
    )

    report = render_fleet_report(fleet_payload(summary))

    assert "Fleet Report" in report
    assert "EVIDENCE_UNAVAILABLE" in report
    assert "Claimed CI minutes saved: **not asserted**" in report
    assert "report-only" in report
