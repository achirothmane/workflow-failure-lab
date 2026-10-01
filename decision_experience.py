from __future__ import annotations

from typing import Any, Iterable

DECISION_EXPERIENCE_SCHEMA = "ci-retry-gate.decision-experience.v1"
TRANSIENT_CATEGORIES = frozenset({"RUNNER_INFRA", "DEPENDENCY_NETWORK"})


def _field(item: object, name: str, default: object = None) -> object:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _minutes(item: object) -> float:
    try:
        return max(0.0, float(_field(item, "duration_minutes", 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _eligible(item: object) -> bool:
    return (
        str(_field(item, "category", "")) in TRANSIENT_CATEGORIES
        and str(_field(item, "confidence", "")) == "high"
        and str(_field(item, "provenance_status", "")) == "CONFIRMED"
        and _field(item, "side_effect_risk", False) is not True
    )


def _next_action(
    *,
    decision: str,
    evidence_status: str,
    assessments: list[object],
    rerun_triggered: bool,
    run_attempt: int,
    max_attempts: int,
) -> str:
    if decision == "ALLOW":
        return "OBSERVE_RERUN_OUTCOME" if rerun_triggered else "RERUN_ALLOWED"

    if any(_field(item, "side_effect_risk", False) is True for item in assessments):
        return "REVIEW_SIDE_EFFECT_BOUNDARY"

    if max_attempts > 0 and run_attempt >= max_attempts:
        return "STOP_RETRY_LOOP"

    if any(str(_field(item, "category", "")) == "CODE_REGRESSION" for item in assessments):
        return "INVESTIGATE_REGRESSION"

    if (
        evidence_status == "UNKNOWN"
        or any(
            str(_field(item, "category", "")) == "EVIDENCE_UNAVAILABLE"
            for item in assessments
        )
    ):
        return "COLLECT_MORE_EVIDENCE"

    return "INVESTIGATE_FAILURE"


def build_decision_experience(
    *,
    evidence_decision: dict[str, Any],
    assessments: Iterable[object],
    rerun_triggered: bool,
    run_attempt: int,
    max_attempts: int,
) -> dict[str, Any]:
    """Build a user-facing decision/value summary without creating new authority.

    The artifact is descriptive only. It derives product-facing metrics from the
    already-finalized production decision and job assessments. It must never be
    consumed as a source of retry authority.
    """
    items = list(assessments)
    decision = str(evidence_decision.get("decision") or "BLOCK")
    evidence_status = str(evidence_decision.get("evidence_status") or "UNKNOWN")
    confidence = str(evidence_decision.get("confidence") or "unknown")

    eligible = [item for item in items if _eligible(item)]
    blocked = [item for item in items if not _eligible(item)]
    side_effect = [
        item for item in items if _field(item, "side_effect_risk", False) is True
    ]
    unavailable = [
        item
        for item in items
        if str(_field(item, "category", "")) == "EVIDENCE_UNAVAILABLE"
    ]

    observed_minutes = round(sum(_minutes(item) for item in items), 2)
    eligible_minutes = round(sum(_minutes(item) for item in eligible), 2)
    blocked_minutes = round(sum(_minutes(item) for item in blocked), 2)

    reasons = evidence_decision.get("reasons")
    if not isinstance(reasons, list):
        reasons = []

    return {
        "schema_version": DECISION_EXPERIENCE_SCHEMA,
        "authority": "DESCRIPTIVE_ONLY",
        "decision": decision,
        "evidence_status": evidence_status,
        "confidence": confidence,
        "reason": str(reasons[0]) if reasons else "",
        "next_action": _next_action(
            decision=decision,
            evidence_status=evidence_status,
            assessments=items,
            rerun_triggered=rerun_triggered,
            run_attempt=run_attempt,
            max_attempts=max_attempts,
        ),
        "jobs": {
            "failed": len(items),
            "rerun_eligible": len(eligible),
            "rerun_blocked": len(blocked),
            "side_effect_blocked": len(side_effect),
            "evidence_unavailable": len(unavailable),
        },
        "minutes": {
            "observed_failed": observed_minutes,
            "rerun_eligible_failed": eligible_minutes,
            "rerun_blocked_failed": blocked_minutes,
            "claimed_saved": None,
        },
        "execution": {
            "run_attempt": run_attempt,
            "max_attempts": max_attempts,
            "rerun_triggered": bool(rerun_triggered),
        },
        "measurement_basis": (
            "Runtime metrics are observed failed-job minutes only. "
            "No saved-minute claim is made until a counterfactual rerun outcome "
            "can be established from later evidence."
        ),
    }


def render_decision_card(experience: dict[str, Any]) -> str:
    jobs = experience.get("jobs") if isinstance(experience.get("jobs"), dict) else {}
    minutes = (
        experience.get("minutes")
        if isinstance(experience.get("minutes"), dict)
        else {}
    )
    return "\n".join(
        [
            "### Decision at a glance",
            "",
            "| Decision | Evidence | Next action | Failed runtime | Eligible jobs | Blocked jobs |",
            "|---|---|---|---:|---:|---:|",
            (
                f"| `{experience.get('decision', 'BLOCK')}` | "
                f"`{experience.get('evidence_status', 'UNKNOWN')}` | "
                f"`{experience.get('next_action', 'INVESTIGATE_FAILURE')}` | "
                f"{float(minutes.get('observed_failed', 0.0)):.2f} min | "
                f"{int(jobs.get('rerun_eligible', 0))} | "
                f"{int(jobs.get('rerun_blocked', 0))} |"
            ),
            "",
            (
                "Value measurement is evidence-bounded: observed failed runtime is "
                "reported, but CI minutes are not labeled as saved without later "
                "counterfactual evidence."
            ),
            "",
        ]
    )
