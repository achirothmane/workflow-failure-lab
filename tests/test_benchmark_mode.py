from __future__ import annotations

import pytest

from benchmark_mode import (
    collect_repository_history,
    parse_repositories,
    render_benchmark_report,
    summarize_benchmark,
)
from history_ci_waste import HistoricalFailure


def _failure(
    run_id: int,
    *,
    fingerprint: str = "FG-NETWORK",
    category: str = "DEPENDENCY_NETWORK",
    recovered: bool = True,
    observed: bool = True,
) -> HistoricalFailure:
    return HistoricalFailure(
        run_id=run_id,
        job_name="test",
        category=category,
        confidence="high",
        duration_minutes=2.0,
        fingerprint=fingerprint,
        signature="connect etimedout <ip>:<n>",
        recovered_after_rerun=recovered,
        rerun_observed=observed,
        side_effect_risk=False,
        attempt=1,
    )


def test_parse_repositories_deduplicates_and_supports_commas_and_newlines():
    repos = parse_repositories("acme/one, acme/two\nacme/one")
    assert repos == ["acme/one", "acme/two"]


def test_parse_repositories_uses_fallback_and_rejects_invalid_names():
    assert parse_repositories("", "acme/project") == ["acme/project"]
    with pytest.raises(ValueError):
        parse_repositories("not-a-repository")


def test_benchmark_learning_is_isolated_per_repository():
    # Six identical observations across two repos must NOT satisfy the five-sample
    # threshold because neither repository has five local samples.
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
    assert summary.categories[0].category == "DEPENDENCY_NETWORK"
    assert summary.categories[0].evaluated == 1
    assert summary.categories[0].observed_precision == 1.0


def test_benchmark_keeps_unobserved_counterfactual_unknown():
    samples = [_failure(run_id) for run_id in range(1, 6)]
    samples.append(_failure(6, recovered=False, observed=False))
    summary = summarize_benchmark({"acme/one": (samples, 6)})

    assert summary.decisions == 1
    assert summary.evaluated == 0
    assert summary.recoveries == 0
    assert summary.false_positives == 0
    assert summary.unknown_outcomes == 1
    assert summary.observed_precision == 0.0


def test_report_distinguishes_precision_from_overall_accuracy():
    summary = summarize_benchmark(
        {"acme/one": ([_failure(run_id) for run_id in range(1, 7)], 6)}
    )
    report = render_benchmark_report(summary)

    assert "CI Retry Gate Benchmark Mode" in report
    assert "Observed precision" in report
    assert "not overall classifier accuracy" in report
    assert "DEPENDENCY_NETWORK" in report


class _FakeAPI:
    def request(self, method: str, path: str, payload=None, accept=None):
        if path.startswith("/repos/acme/repo/actions/runs?status=completed"):
            return {
                "workflow_runs": [
                    {"id": 101, "run_attempt": 2},
                ]
            }
        if path == "/repos/acme/repo/actions/runs/101/attempts/1/jobs?per_page=100":
            return {
                "jobs": [
                    {
                        "id": 1001,
                        "name": "test",
                        "conclusion": "failure",
                        "started_at": "2026-01-01T00:00:00Z",
                        "completed_at": "2026-01-01T00:02:00Z",
                        "steps": [{"name": "Run tests"}],
                    }
                ]
            }
        if path == "/repos/acme/repo/actions/runs/101/attempts/2/jobs?per_page=100":
            return {
                "jobs": [
                    {
                        "id": 1002,
                        "name": "test",
                        "conclusion": "success",
                        "started_at": "2026-01-01T00:03:00Z",
                        "completed_at": "2026-01-01T00:04:00Z",
                        "steps": [{"name": "Run tests"}],
                    }
                ]
            }
        raise AssertionError(f"unexpected request: {method} {path}")

    def get_job_logs(self, repo: str, job_id: int) -> str:
        assert repo == "acme/repo"
        assert job_id == 1001
        return "npm ERR! code ETIMEDOUT\nError: connection reset by peer\n"

    def get_jobs(self, repo: str, run_id: int):
        raise AssertionError("fallback should not be used")


def test_collect_repository_history_observes_real_rerun_recovery():
    failures, runs = collect_repository_history(_FakeAPI(), "acme/repo", 10)

    assert runs == 1
    assert len(failures) == 1
    item = failures[0]
    assert item.category == "DEPENDENCY_NETWORK"
    assert item.confidence == "high"
    assert item.rerun_observed is True
    assert item.recovered_after_rerun is True
    assert item.duration_minutes == 2.0
