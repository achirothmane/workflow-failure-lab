from causal_dominance_positive_search import (
    SEARCH_SHARDS,
    render_positive_search,
    search_positive_controls,
    summary_payload,
)
from history_ci_waste import HistoricalFailure
from mechanism_causality_gate import MECHANISM_CAUSAL_CONFIRMED
from pinned_research_corpus import SWC_DPRINT_HTTP_504
from recovery_ground_truth import (
    RECOVERY_NOT_OBSERVED,
    RECOVERY_NOT_RECOVERED,
    RECOVERY_VALIDATED,
)
from transient_mechanism_gate import REASON_SERVER_5XX


class FakeAPI:
    def __init__(self, jobs_by_run, logs_by_job_id):
        self.jobs_by_run = jobs_by_run
        self.logs_by_job_id = logs_by_job_id

    def request(self, method, path, payload=None, accept="application/vnd.github+json"):
        assert method == "GET"
        run_id = int(path.split("/actions/runs/")[1].split("/")[0])
        return {"jobs": self.jobs_by_run.get(run_id, [])}

    def get_job_logs(self, repo, job_id):
        return self.logs_by_job_id[job_id]


def historical(run_id, job_name, recovery_status, *, category="CODE_REGRESSION"):
    return HistoricalFailure(
        run_id=run_id,
        job_name=job_name,
        category=category,
        confidence="high",
        duration_minutes=1.0,
        attempt=1,
        recovery_status=recovery_status,
        side_effect_risk=False,
        mechanism_causality_status=MECHANISM_CAUSAL_CONFIRMED,
        mechanism_causality_reasons=(REASON_SERVER_5XX,),
        mechanism_causal_evidence=("Error: HTTP 504 Gateway Timeout",),
    )


def deterministic_job():
    return {
        "id": 9002,
        "name": "unit",
        "conclusion": "failure",
        "steps": [
            {
                "name": "Run tests",
                "conclusion": "failure",
                "started_at": "2026-09-18T10:00:00Z",
                "completed_at": "2026-09-18T10:00:10Z",
            }
        ],
    }


def deterministic_log():
    return (
        "2026-09-18T10:00:02.0000000Z Error: HTTP 504 Gateway Timeout\n"
        "2026-09-18T10:00:03.0000000Z Error: TypeError: undefined is not a function\n"
        "2026-09-18T10:00:04.0000000Z error: test failed, to rerun pass "
        "`-p app --test unit`\n"
    )


def swc_api():
    case = SWC_DPRINT_HTTP_504
    return FakeAPI(
        {case.run_id: [case.failed_job]},
        {case.failed_job_id: case.failure_log},
    )


def test_search_finds_real_swc_validated_positive():
    case = SWC_DPRINT_HTTP_504
    histories = {
        case.repository: (
            [historical(case.run_id, case.job_name, RECOVERY_VALIDATED)],
            1,
        )
    }

    summary = search_positive_controls(
        swc_api(),
        histories,
        repositories_requested=1,
    )

    assert len(summary.records) == 1
    assert len(summary.dominance_candidates) == 1
    assert len(summary.validated_positives) == 1
    assert summary.independent_positive_runs == 1
    assert summary.independent_positive_repositories == 1
    assert summary.failed_again == ()


def test_search_surfaces_failed_again_as_falsifier():
    case = SWC_DPRINT_HTTP_504
    histories = {
        case.repository: (
            [historical(case.run_id, case.job_name, RECOVERY_NOT_RECOVERED)],
            1,
        )
    }

    summary = search_positive_controls(swc_api(), histories)

    assert len(summary.dominance_candidates) == 1
    assert len(summary.validated_positives) == 0
    assert len(summary.failed_again) == 1


def test_search_tracks_deterministic_blocker():
    histories = {
        "example/repo": (
            [historical(123, "unit", RECOVERY_VALIDATED)],
            1,
        )
    }
    api = FakeAPI({123: [deterministic_job()]}, {9002: deterministic_log()})

    summary = search_positive_controls(api, histories)

    assert len(summary.records) == 1
    assert summary.blocked_deterministic == 1
    assert len(summary.dominance_candidates) == 0


def test_search_excludes_non_evaluable_history_before_raw_lookup():
    case = SWC_DPRINT_HTTP_504
    histories = {
        case.repository: (
            [historical(case.run_id, case.job_name, RECOVERY_NOT_OBSERVED)],
            1,
        )
    }

    summary = search_positive_controls(FakeAPI({}, {}), histories)

    assert summary.records == ()


def test_search_payload_and_repo_shards_are_stable():
    summary = search_positive_controls(
        FakeAPI({}, {}),
        {},
        repositories_requested=50,
        repositories_skipped=2,
    )
    payload = summary_payload(summary)

    assert payload["repositories_requested"] == 50
    assert payload["repositories_analyzed"] == 0
    assert payload["repositories_skipped"] == 2
    assert payload["validated_positives"] == 0
    assert set(SEARCH_SHARDS) == {1, 2}
    assert len(SEARCH_SHARDS[1]) == 50
    assert len(SEARCH_SHARDS[2]) == 50

    report = render_positive_search(summary)
    assert "Read-only targeted search" in report
    assert "Authority-safe validated positives: **0**" in report
