from history_ci_waste import HistoricalFailure
from mechanism_causality_gate import MECHANISM_CAUSAL_CONFIRMED
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
    def __init__(self, logs_by_job_id):
        self.logs_by_job_id = logs_by_job_id

    def request(self, method, path, payload=None, accept="application/vnd.github+json"):
        assert method == "GET"
        run_id = int(path.split("/actions/runs/")[1].split("/")[0])
        if run_id == 101:
            return {"jobs": [failed_job(1001, "unit", "Run tests")]}
        if run_id == 102:
            return {"jobs": [failed_job(1002, "build", "Run build")]}
        if run_id == 103:
            return {"jobs": [failed_job(1003, "unit-again", "Run tests")]}
        return {"jobs": []}

    def get_job_logs(self, repo, job_id):
        return self.logs_by_job_id[job_id]


def failed_job(job_id, name, step_name):
    return {
        "id": job_id,
        "name": name,
        "conclusion": "failure",
        "steps": [
            {
                "name": step_name,
                "conclusion": "failure",
                "started_at": "2026-09-18T10:00:00Z",
                "completed_at": "2026-09-18T10:00:10Z",
            }
        ],
    }


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


def candidate_log():
    return (
        "2026-09-18T10:00:02.0000000Z Error: HTTP 504 Gateway Timeout\n"
        "2026-09-18T10:00:04.0000000Z error: test failed, to rerun pass "
        "`-p app --test unit`\n"
    )


def deterministic_log():
    return (
        "2026-09-18T10:00:02.0000000Z Error: HTTP 504 Gateway Timeout\n"
        "2026-09-18T10:00:03.0000000Z Error: TypeError: undefined is not a function\n"
        "2026-09-18T10:00:04.0000000Z error: test failed, to rerun pass "
        "`-p app --test unit`\n"
    )


def test_shadow_summary_separates_candidate_and_deterministic_blocker():
    histories = {
        "example/repo": (
            [
                historical(101, "unit", RECOVERY_VALIDATED),
                historical(102, "build", RECOVERY_VALIDATED),
            ],
            2,
        )
    }
    api = FakeAPI(
        {
            1001: candidate_log(),
            1002: deterministic_log(),
        }
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
    histories = {
        "example/repo": (
            [historical(103, "unit-again", RECOVERY_NOT_RECOVERED)],
            1,
        )
    }
    api = FakeAPI({1003: candidate_log()})

    summary = collect_causal_dominance_shadow(api, histories)

    assert len(summary.candidates) == 1
    assert len(summary.evaluable_candidates) == 1
    assert summary.validated_recoveries == 0
    assert summary.failed_again == 1
    assert summary.observed_precision == 0.0


def test_shadow_report_is_explicitly_research_only():
    histories = {
        "example/repo": (
            [historical(101, "unit", RECOVERY_VALIDATED)],
            1,
        )
    }
    api = FakeAPI({1001: candidate_log()})

    report = render_causal_dominance_shadow(
        collect_causal_dominance_shadow(api, histories)
    )

    assert "Research-only counterfactual" in report
    assert "No runtime classifier category" in report
    assert "Validated candidate recoveries: **1**" in report
    assert "Candidate failed again: **0**" in report
