from __future__ import annotations

from datetime import datetime

from flaky_test_intelligence import FAIL, CaseObservation, summarize_flaky_tests

SHADOW_SCHEMA = "historical-flakiness-shadow.ci.v1"
SUPPORT = "HISTORICAL_SUPPORT_PRESENT"
CONTRADICTION = "HISTORICAL_CONTRADICTION"
ORDERING_UNAVAILABLE = "ORDERING_UNAVAILABLE"
NO_PRIOR = "NO_PRIOR_EVIDENCE"
INSUFFICIENT = "INSUFFICIENT_PRIOR_EVIDENCE"
NOT_APPLICABLE = "NOT_APPLICABLE"
MIN_PRIOR_RECOVERIES = 2


def _time(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _prior(item: CaseObservation, current: CaseObservation):
    if item.run_id == current.run_id:
        if item.attempt == current.attempt:
            return False
        return item.attempt < current.attempt
    left, right = _time(item.observed_at), _time(current.observed_at)
    if left is None or right is None or left == right:
        return None
    return left < right


def _evaluate(observations, current):
    prior = []
    unknown_order = False
    for item in observations:
        if item.test_id != current.test_id:
            continue
        relation = _prior(item, current)
        if relation is True:
            prior.append(item)
        elif relation is None:
            unknown_order = True

    if unknown_order:
        return {
            "test_id": current.test_id,
            "status": ORDERING_UNAVAILABLE,
            "prior_observations": len(prior),
            "validated_recoveries": 0,
            "persistent_failure_shas": 0,
            "failure_rate": 0.0,
        }
    if not prior:
        return {
            "test_id": current.test_id,
            "status": NO_PRIOR,
            "prior_observations": 0,
            "validated_recoveries": 0,
            "persistent_failure_shas": 0,
            "failure_rate": 0.0,
        }

    summary = summarize_flaky_tests(prior)[0]
    if summary.persistent_failure_shas:
        status = CONTRADICTION
    elif summary.validated_recoveries >= MIN_PRIOR_RECOVERIES:
        status = SUPPORT
    else:
        status = INSUFFICIENT

    return {
        "test_id": current.test_id,
        "status": status,
        "prior_observations": summary.observations,
        "validated_recoveries": summary.validated_recoveries,
        "persistent_failure_shas": summary.persistent_failure_shas,
        "failure_rate": round(summary.failure_rate, 6),
    }


def compare_historical_flakiness_shadow(
    *,
    repo: str,
    run_id: int,
    run_attempt: int,
    observations: tuple[CaseObservation, ...],
    baseline_decision: str,
    baseline_evidence_status: str,
) -> dict:
    decision = baseline_decision.strip().upper()
    evidence = baseline_evidence_status.strip().upper()

    if decision != "BLOCK" or evidence != "UNKNOWN":
        tests = []
        status = NOT_APPLICABLE
    else:
        current = {}
        for item in observations:
            if (
                item.run_id == run_id
                and item.attempt == run_attempt
                and item.status == FAIL
            ):
                current.setdefault(item.test_id, item)

        tests = [_evaluate(observations, current[k]) for k in sorted(current)]
        states = {item["status"] for item in tests}
        if CONTRADICTION in states:
            status = CONTRADICTION
        elif ORDERING_UNAVAILABLE in states:
            status = ORDERING_UNAVAILABLE
        elif tests and states == {SUPPORT}:
            status = SUPPORT
        elif not tests or states == {NO_PRIOR}:
            status = NO_PRIOR
        else:
            status = INSUFFICIENT

    return {
        "schema_version": SHADOW_SCHEMA,
        "mode": "shadow_read_only",
        "subject": {
            "repository": repo,
            "run_id": run_id,
            "run_attempt": run_attempt,
        },
        "baseline": {
            "decision": decision,
            "evidence_status": evidence,
        },
        "shadow": {
            "status": status,
            "current_failed_tests": len(tests),
            "tests_with_historical_support": sum(x["status"] == SUPPORT for x in tests),
            "tests_with_historical_contradiction": sum(x["status"] == CONTRADICTION for x in tests),
            "tests_with_ordering_unavailable": sum(x["status"] == ORDERING_UNAVAILABLE for x in tests),
            "tests": tests,
        },
        "authorization": {
            "changed": False,
            "reason": "Shadow evidence never changes production retry authorization.",
        },
    }


def render_historical_flakiness_shadow(result: dict) -> str:
    baseline = result["baseline"]
    shadow = result["shadow"]
    return (
        "## Historical Flakiness Shadow Comparison\n\n"
        "> Read-only. Historical evidence cannot grant rerun authority.\n\n"
        f"Baseline: **{baseline['decision']} / {baseline['evidence_status']}**\n"
        f"Shadow status: **{shadow['status']}**\n"
        f"Failed tests evaluated: **{shadow['current_failed_tests']}**\n"
        f"Strictly-prior support: **{shadow['tests_with_historical_support']}**\n"
        f"Historical contradictions: **{shadow['tests_with_historical_contradiction']}**\n"
        f"Ordering unavailable: **{shadow['tests_with_ordering_unavailable']}**\n"
    )
