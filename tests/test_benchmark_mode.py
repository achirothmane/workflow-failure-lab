from __future__ import annotations

import pytest

from benchmark_mode import (
    REJECTION_CODE_REGRESSION,
    REJECTION_LOW_CONFIDENCE_TRANSIENT,
    REJECTION_NON_TRANSIENT,
    REJECTION_UNCONFIRMED_PROVENANCE,
    REJECTION_SIDE_EFFECT,
    REJECTION_UNKNOWN,
    _rejection_reason,
    collect_repository_history,
    collect_repository_samples,
    parse_repositories,
    render_benchmark_report,
    summarize_benchmark,
)
from history_ci_waste import HistoricalFailure
from recovery_ground_truth import (
    RECOVERY_NOT_OBSERVED,
    RECOVERY_NOT_RECOVERED,
    RECOVERY_UNVERIFIED,
    RECOVERY_VALIDATED,
)


def _failure(
    run_id: int,
    *,
    fingerprint: str = "FG-NETWORK",
    category: str = "DEPENDENCY_NETWORK",
    confidence: str = "high",
    recovered: bool = True,
    observed: bool = True,
    side_effect: bool = False,
    provenance: str = "CONFIRMED",
    recovery_status: str | None = None,
) -> HistoricalFailure:
    if recovery_status is None:
        if not observed:
            recovery_status = RECOVERY_NOT_OBSERVED
        elif recovered:
            recovery_status = RECOVERY_VALIDATED
        else:
            recovery_status = RECOVERY_NOT_RECOVERED
    return HistoricalFailure(
        run_id=run_id,
        job_name="test",
        category=category,
        confidence=confidence,
        duration_minutes=2.0,
        fingerprint=fingerprint,
        signature="connect etimedout <ip>:<n>",
        recovered_after_rerun=recovered,
        rerun_observed=observed,
        side_effect_risk=side_effect,
        attempt=1,
        provenance_status=provenance,
        recovery_status=recovery_status,
    )


def test_parse_repositories_deduplicates_and_supports_commas_and_newlines():
    repos = parse_repositories("acme/one, acme/two\nacme/one")
    assert repos == ["acme/one", "acme/two"]


def test_parse_repositories_uses_fallback_and_rejects_invalid_names():
    assert parse_repositories("", "acme/project") == ["acme/project"]
    with pytest.raises(ValueError):
        parse_repositories("not-a-repository")


def test_benchmark_learning_is_isolated_per_repository():
    histories = {
        "acme/one": ([_failure(1), _failure(2), _failure(3)], 3),
        "acme/two": ([_failure(4), _failure(5), _failure(6)], 3),
    }
    summary = summarize_benchmark(histories)

    assert summary.repositories_analyzed == 2
    assert summary.failed_jobs == 6
    assert summary.decisions == 0
    assert summary.evaluated == 0


def test_benchmark_backtests_sixth_local_failure_after_five_prior_recoveries():
    histories = {
        "acme/one": ([_failure(run_id) for run_id in range(1, 7)], 6),
    }
    summary = summarize_benchmark(histories)

    assert summary.failed_jobs == 6
    assert summary.decisions == 1
    assert summary.evaluated == 1
    assert summary.recoveries == 1
    assert summary.false_positives == 0
    assert summary.unknown_outcomes == 0
    assert summary.observed_precision == 1.0
    assert summary.decision_coverage == pytest.approx(1 / 6)
    assert summary.evaluated_coverage == pytest.approx(1 / 6)


def test_rerun_enriched_sample_measures_base_candidate_precision():
    natural = {"acme/one": ([], 10)}
    rerun = {
        "acme/one": (
            [
                _failure(101, recovered=True),
                _failure(102, recovered=True),
                _failure(103, recovered=False),
                _failure(104, category="CODE_REGRESSION", recovered=False),
            ],
            4,
        )
    }

    summary = summarize_benchmark(natural, rerun_histories=rerun)

    assert summary.rerun_runs_analyzed == 4
    assert summary.rerun_failed_jobs == 4
    assert summary.rerun_candidates == 3
    assert summary.rerun_evaluated == 3
    assert summary.rerun_recoveries == 2
    assert summary.rerun_false_positives == 1
    assert summary.rerun_unknown_outcomes == 0
    assert summary.rerun_observed_precision == pytest.approx(2 / 3)
    assert summary.rerun_candidate_coverage == pytest.approx(3 / 4)
    assert summary.categories[0].category == "DEPENDENCY_NETWORK"
    assert summary.categories[0].candidates == 3


def test_rerun_enriched_excludes_side_effect_and_low_confidence_candidates():
    rerun = {
        "acme/one": (
            [
                _failure(1, side_effect=True),
                _failure(2, confidence="medium"),
                _failure(3, category="CODE_REGRESSION"),
            ],
            3,
        )
    }
    summary = summarize_benchmark(
        {"acme/one": ([], 0)},
        rerun_histories=rerun,
    )

    assert summary.rerun_failed_jobs == 3
    assert summary.rerun_candidates == 0
    assert summary.rerun_evaluated == 0


def test_rerun_enriched_keeps_copied_unexecuted_job_unknown():
    rerun = {
        "acme/one": (
            [_failure(1, recovered=False, observed=False)],
            1,
        )
    }
    summary = summarize_benchmark(
        {"acme/one": ([], 0)},
        rerun_histories=rerun,
    )

    assert summary.rerun_candidates == 1
    assert summary.rerun_evaluated == 0
    assert summary.rerun_false_positives == 0
    assert summary.rerun_unknown_outcomes == 1


def test_report_separates_natural_coverage_from_rerun_precision():
    summary = summarize_benchmark(
        {"acme/one": ([_failure(run_id) for run_id in range(1, 7)], 6)},
        rerun_histories={"acme/one": ([_failure(10)], 1)},
    )
    report = render_benchmark_report(summary)

    assert "Natural sample — coverage" in report
    assert "Rerun-enriched sample — precision" in report
    assert "must not be interpreted as prevalence or natural coverage" in report


class _FakeAPI:
    def request(self, method: str, path: str, payload=None, accept=None):
        if path.startswith("/repos/acme/repo/actions/runs?status=completed"):
            return {
                "workflow_runs": [
                    {"id": 104, "run_attempt": 1},
                    {"id": 103, "run_attempt": 1},
                    {"id": 102, "run_attempt": 2},
                    {"id": 101, "run_attempt": 2},
                ]
            }

        for run_id, attempts in [(104, 1), (103, 1), (102, 2), (101, 2)]:
            for attempt in range(1, attempts + 1):
                if path == (
                    f"/repos/acme/repo/actions/runs/{run_id}/attempts/"
                    f"{attempt}/jobs?per_page=100"
                ):
                    if attempt == 1:
                        return {
                            "jobs": [
                                {
                                    "id": run_id * 10 + 1,
                                    "name": "test",
                                    "conclusion": "failure",
                                    "started_at": f"2026-01-01T00:{run_id % 60:02d}:00Z",
                                    "completed_at": f"2026-01-01T00:{run_id % 60:02d}:30Z",
                                    "steps": [{
                                        "name": "Run tests",
                                        "conclusion": "failure",
                                        "started_at": f"2026-01-01T00:{run_id % 60:02d}:00Z",
                                        "completed_at": f"2026-01-01T00:{run_id % 60:02d}:30Z",
                                    }],
                                }
                            ]
                        }
                    return {
                        "jobs": [
                            {
                                "id": run_id * 10 + 2,
                                "name": "test",
                                "conclusion": "success",
                                "started_at": f"2026-01-01T01:{run_id % 60:02d}:00Z",
                                "completed_at": f"2026-01-01T01:{run_id % 60:02d}:30Z",
                                "steps": [{
                                    "name": "Run tests",
                                    "conclusion": "success",
                                    "started_at": f"2026-01-01T01:{run_id % 60:02d}:00Z",
                                    "completed_at": f"2026-01-01T01:{run_id % 60:02d}:30Z",
                                }],
                            }
                        ]
                    }

        raise AssertionError(f"unexpected request: {method} {path}")

    def get_job_logs(self, repo: str, job_id: int) -> str:
        assert repo == "acme/repo"
        run_id = job_id // 10
        minute = run_id % 60
        return (
            f"2026-01-01T00:{minute:02d}:05.0000000Z ##[group]Run npm ci\n"
            f"2026-01-01T00:{minute:02d}:10.0000000Z npm ERR! code ETIMEDOUT\n"
            f"2026-01-01T00:{minute:02d}:11.0000000Z Error: connection reset by peer\n"
            f"2026-01-01T00:{minute:02d}:12.0000000Z Process completed with exit code 1\n"
        )

    def get_jobs(self, repo: str, run_id: int):
        raise AssertionError("fallback should not be used")


def test_collect_repository_history_observes_real_rerun_recovery():
    failures, runs = collect_repository_history(_FakeAPI(), "acme/repo", 4)

    assert runs == 4
    assert len(failures) == 4
    rerun_items = [item for item in failures if item.run_id in {101, 102}]
    assert all(item.category == "DEPENDENCY_NETWORK" for item in rerun_items)
    assert all(item.confidence == "high" for item in rerun_items)
    assert all(item.rerun_observed is True for item in rerun_items)
    assert all(item.recovered_after_rerun is True for item in rerun_items)
    assert all(item.recovery_status == RECOVERY_VALIDATED for item in rerun_items)


def test_collect_repository_samples_separates_natural_and_rerun_runs():
    natural, enriched = collect_repository_samples(
        _FakeAPI(),
        "acme/repo",
        natural_run_limit=2,
        rerun_run_limit=2,
        rerun_search_limit=4,
    )

    natural_failures, natural_runs = natural
    rerun_failures, rerun_runs = enriched

    assert natural_runs == 2
    assert {item.run_id for item in natural_failures} == {103, 104}
    assert rerun_runs == 2
    assert {item.run_id for item in rerun_failures} == {101, 102}
    assert all(item.rerun_observed for item in rerun_failures)
    assert all(item.recovered_after_rerun for item in rerun_failures)
    assert all(item.recovery_status == RECOVERY_VALIDATED for item in rerun_failures)


class _SideEffectWorkflowAPI:
    def request(self, method: str, path: str, payload=None, accept=None):
        if path.startswith("/repos/acme/repo/actions/runs?status=completed"):
            return {"workflow_runs": [{"id": 201, "run_attempt": 2}]}
        if path == "/repos/acme/repo/actions/runs/201/attempts/1/jobs?per_page=100":
            return {
                "jobs": [
                    {
                        "id": 2011,
                        "name": "test",
                        "conclusion": "failure",
                        "started_at": "2026-01-01T00:00:00Z",
                        "completed_at": "2026-01-01T00:01:00Z",
                        "steps": [{"name": "Run tests"}],
                    },
                    {
                        "id": 2012,
                        "name": "deploy production",
                        "conclusion": "success",
                        "started_at": "2026-01-01T00:00:00Z",
                        "completed_at": "2026-01-01T00:01:00Z",
                        "steps": [{"name": "Deploy production"}],
                    },
                ]
            }
        if path == "/repos/acme/repo/actions/runs/201/attempts/2/jobs?per_page=100":
            return {
                "jobs": [
                    {
                        "id": 2013,
                        "name": "test",
                        "conclusion": "success",
                        "started_at": "2026-01-01T00:02:00Z",
                        "completed_at": "2026-01-01T00:03:00Z",
                        "steps": [{"name": "Run tests"}],
                    }
                ]
            }
        raise AssertionError(f"unexpected request: {method} {path}")

    def get_job_logs(self, repo: str, job_id: int) -> str:
        return (
            "2026-01-01T00:00:10.0000000Z npm ERR! code ETIMEDOUT\n"
            "2026-01-01T00:00:11.0000000Z Error: connection reset by peer\n"
            "2026-01-01T00:00:12.0000000Z Process completed with exit code 1\n"
        )

    def get_jobs(self, repo: str, run_id: int):
        raise AssertionError("fallback should not be used")


def test_workflow_wide_side_effect_blocks_rerun_candidate():
    failures, _ = collect_repository_history(_SideEffectWorkflowAPI(), "acme/repo", 1)
    assert len(failures) == 1
    assert failures[0].category == "DEPENDENCY_NETWORK"
    assert failures[0].side_effect_risk is True

    summary = summarize_benchmark(
        {"acme/repo": ([], 0)},
        rerun_histories={"acme/repo": (failures, 1)},
    )
    assert summary.rerun_candidates == 0


def test_rejection_reason_explains_why_non_candidates_are_blocked():
    assert _rejection_reason(_failure(1, side_effect=True)) == REJECTION_SIDE_EFFECT
    assert _rejection_reason(
        _failure(2, category="CODE_REGRESSION", recovered=False)
    ) == REJECTION_CODE_REGRESSION
    assert _rejection_reason(
        _failure(3, confidence="medium")
    ) == REJECTION_LOW_CONFIDENCE_TRANSIENT
    assert _rejection_reason(
        _failure(4, category="UNKNOWN", confidence="low")
    ) == REJECTION_UNKNOWN
    assert _rejection_reason(
        _failure(5, category="RESOURCE_TIMEOUT", confidence="high")
    ) == REJECTION_NON_TRANSIENT
    assert _rejection_reason(
        _failure(6, provenance="UNAVAILABLE")
    ) == REJECTION_UNCONFIRMED_PROVENANCE
    assert _rejection_reason(_failure(7)) is None


def test_benchmark_counts_blocked_recoveries_by_rejection_reason():
    rerun = {
        "acme/one": (
            [
                _failure(1, recovered=True),
                _failure(2, side_effect=True, recovered=True),
                _failure(3, category="CODE_REGRESSION", recovered=True),
                _failure(4, confidence="medium", recovered=True),
                _failure(
                    5,
                    category="UNKNOWN",
                    confidence="low",
                    recovered=False,
                    observed=True,
                ),
                _failure(
                    6,
                    category="RESOURCE_TIMEOUT",
                    confidence="high",
                    recovered=False,
                    observed=False,
                ),
            ],
            6,
        )
    }

    summary = summarize_benchmark(
        {"acme/one": ([], 0)},
        rerun_histories=rerun,
    )

    assert summary.rerun_candidates == 1
    assert summary.rerun_blocked == 5
    assert summary.rerun_blocked_recovered == 3
    assert summary.rerun_blocked_failed_again == 1
    assert summary.rerun_blocked_unknown == 1

    by_reason = {item.reason: item for item in summary.rejections}
    assert by_reason[REJECTION_SIDE_EFFECT].recovered == 1
    assert by_reason[REJECTION_CODE_REGRESSION].recovered == 1
    assert by_reason[REJECTION_LOW_CONFIDENCE_TRANSIENT].recovered == 1
    assert by_reason[REJECTION_UNKNOWN].failed_again == 1
    assert by_reason[REJECTION_NON_TRANSIENT].unknown_outcomes == 1

    assert summary.rerun_candidates + summary.rerun_blocked == summary.rerun_failed_jobs


def test_benchmark_report_surfaces_blocked_and_missed_recovery_intelligence():
    summary = summarize_benchmark(
        {"acme/one": ([], 0)},
        rerun_histories={
            "acme/one": (
                [
                    _failure(1, side_effect=True, recovered=True),
                    _failure(2, category="CODE_REGRESSION", recovered=False),
                ],
                2,
            )
        },
    )

    report = render_benchmark_report(summary)
    assert "Blocked / missed-recovery intelligence" in report
    assert "Blocked failures that later recovered after a real rerun: **1**" in report
    assert "`SIDE_EFFECT_RISK`" in report
    assert "`CODE_REGRESSION`" in report
    assert "coverage signal, not proof that automatic rerun was safe" in report


def test_rerun_candidate_requires_confirmed_execution_provenance():
    rerun = {
        "acme/one": (
            [
                _failure(1, provenance="CONFIRMED", recovered=True),
                _failure(2, provenance="UNAVAILABLE", recovered=True),
                _failure(3, provenance="MISMATCH", recovered=False),
            ],
            3,
        )
    }

    summary = summarize_benchmark(
        {"acme/one": ([], 0)},
        rerun_histories=rerun,
    )

    assert summary.rerun_candidates == 1
    by_reason = {item.reason: item for item in summary.rejections}
    assert by_reason[REJECTION_UNCONFIRMED_PROVENANCE].blocked == 2
    assert by_reason[REJECTION_UNCONFIRMED_PROVENANCE].recovered == 1
    assert by_reason[REJECTION_UNCONFIRMED_PROVENANCE].failed_again == 1


def test_rerun_precision_excludes_unverified_later_success():
    rerun = {
        "acme/one": (
            [
                _failure(
                    1,
                    recovered=True,
                    recovery_status=RECOVERY_UNVERIFIED,
                ),
                _failure(2, recovered=True),
                _failure(3, recovered=False),
            ],
            3,
        )
    }

    summary = summarize_benchmark(
        {"acme/one": ([], 0)},
        rerun_histories=rerun,
    )

    assert summary.rerun_candidates == 3
    assert summary.rerun_evaluated == 2
    assert summary.rerun_recoveries == 1
    assert summary.rerun_false_positives == 1
    assert summary.rerun_unknown_outcomes == 1
    assert summary.rerun_observed_precision == 0.5

