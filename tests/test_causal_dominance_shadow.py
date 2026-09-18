from history_ci_waste import HistoricalFailure
from mechanism_causality_gate import MECHANISM_CAUSAL_CONFIRMED
from pinned_research_corpus import SWC_DPRINT_HTTP_504
from recovery_ground_truth import RECOVERY_NOT_RECOVERED, RECOVERY_VALIDATED
from root_cause_precedence import (
    DOMINANCE_CANDIDATE,
    DOMINANCE_PRIMARY_DETERMINISTIC_EVIDENCE,
)
from transient_mechanism_gate import REASON_SERVER_5XX

from causal_dominance_shadow import (
    CausalDominanceShadowSummary,
    collect_causal_dominance_shadow,
    render_causal_dominance_shadow,
)


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


def historical(run_id, job_name, recovery_status):
    return HistoricalFailure(
        run_id=run_id,
        job_name=job_name,
        category="CODE_REGRESSION",
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
        "id": 2002,
        "name": "build",
        "conclusion": "failure",
        "steps": [
            {
                "name": "Run build",
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
        {
            case.run_id: [case.failed_job],
        },
        {
            case.failed_job_id: case.failure_log,
        },
    )


def test_shadow_summary_separates_candidate_and_deterministic_blocker():
    case = SWC_DPRINT_HTTP_504
    histories = {
        case.repository: (
            [
                historical(case.run_id, case.job_name, RECOVERY_VALIDATED),
            ],
            1,
        ),
        "example/repo": (
            [
                historical(102, "build", RECOVERY_VALIDATED),
            ],
            1,
        ),
    }
    api = FakeAPI(
        {
            case.run_id: [case.failed_job],
            102: [deterministic_job()],
        },
        {
            case.failed_job_id: case.failure_log,
            2002: deterministic_log(),
        },
    )

    summary = collect_causal_dominance_shadow(api, histories)

    assert isinstance(summary, CausalDominanceShadowSummary)
    assert summary.qualifying == 2
    assert len(summary.candidates) == 1
    assert summary.candidates[0].dominance_status == DOMINANCE_CANDIDATE
    assert summary.validated_recoveries == 1
    assert summary.failed_again == 0
    assert summary.observed_precision == 1.0
    assert summary.primary_deterministic_blocked == 1
    assert any(
        item.dominance_status == DOMINANCE_PRIMARY_DETERMINISTIC_EVIDENCE
        for item in summary.records
    )


def test_shadow_counts_failed_again_as_counterexample():
    case = SWC_DPRINT_HTTP_504
    histories = {
        case.repository: (
            [historical(case.run_id, case.job_name, RECOVERY_NOT_RECOVERED)],
            1,
        )
    }

    summary = collect_causal_dominance_shadow(swc_api(), histories)

    assert len(summary.candidates) == 1
    assert len(summary.evaluable_candidates) == 1
    assert summary.validated_recoveries == 0
    assert summary.failed_again == 1
    assert summary.observed_precision == 0.0


def test_shadow_report_is_explicitly_research_only():
    case = SWC_DPRINT_HTTP_504
    histories = {
        case.repository: (
            [historical(case.run_id, case.job_name, RECOVERY_VALIDATED)],
            1,
        )
    }

    report = render_causal_dominance_shadow(
        collect_causal_dominance_shadow(swc_api(), histories)
    )

    assert "Research-only counterfactual" in report
    assert "No runtime classifier category" in report
    assert "Validated candidate recoveries: **1**" in report
    assert "Candidate failed again: **0**" in report
