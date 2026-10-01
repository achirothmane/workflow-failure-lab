from __future__ import annotations

from dataclasses import dataclass

from decision_experience import (
    DECISION_EXPERIENCE_SCHEMA,
    build_decision_experience,
    render_decision_card,
)


@dataclass(frozen=True)
class Assessment:
    category: str
    confidence: str
    provenance_status: str
    side_effect_risk: bool
    duration_minutes: float


def decision(value: str, status: str, reason: str = "because") -> dict:
    return {
        "decision": value,
        "evidence_status": status,
        "confidence": "high" if status != "UNKNOWN" else "unknown",
        "reasons": [reason],
    }


def test_allow_without_execution_recommends_bounded_rerun():
    experience = build_decision_experience(
        evidence_decision=decision("ALLOW", "SUFFICIENT"),
        assessments=[
            Assessment("DEPENDENCY_NETWORK", "high", "CONFIRMED", False, 3.25)
        ],
        rerun_triggered=False,
        run_attempt=1,
        max_attempts=2,
    )

    assert experience["schema_version"] == DECISION_EXPERIENCE_SCHEMA
    assert experience["authority"] == "DESCRIPTIVE_ONLY"
    assert experience["next_action"] == "RERUN_ALLOWED"
    assert experience["jobs"]["rerun_eligible"] == 1
    assert experience["jobs"]["rerun_blocked"] == 0
    assert experience["minutes"]["observed_failed"] == 3.25
    assert experience["minutes"]["claimed_saved"] is None


def test_allow_after_dispatch_recommends_observing_outcome():
    experience = build_decision_experience(
        evidence_decision=decision("ALLOW", "SUFFICIENT"),
        assessments=[
            Assessment("RUNNER_INFRA", "high", "CONFIRMED", False, 1.0)
        ],
        rerun_triggered=True,
        run_attempt=1,
        max_attempts=2,
    )

    assert experience["next_action"] == "OBSERVE_RERUN_OUTCOME"
    assert experience["execution"]["rerun_triggered"] is True


def test_side_effect_boundary_is_explained_before_generic_failure():
    experience = build_decision_experience(
        evidence_decision=decision("BLOCK", "CONTRADICTED"),
        assessments=[
            Assessment("DEPENDENCY_NETWORK", "high", "CONFIRMED", True, 8.0)
        ],
        rerun_triggered=False,
        run_attempt=1,
        max_attempts=2,
    )

    assert experience["next_action"] == "REVIEW_SIDE_EFFECT_BOUNDARY"
    assert experience["jobs"]["side_effect_blocked"] == 1
    assert experience["jobs"]["rerun_eligible"] == 0
    assert experience["minutes"]["rerun_blocked_failed"] == 8.0


def test_attempt_cap_stops_retry_loop():
    experience = build_decision_experience(
        evidence_decision=decision("BLOCK", "UNKNOWN"),
        assessments=[
            Assessment("DEPENDENCY_NETWORK", "high", "CONFIRMED", False, 2.0)
        ],
        rerun_triggered=False,
        run_attempt=2,
        max_attempts=2,
    )

    assert experience["next_action"] == "STOP_RETRY_LOOP"


def test_regression_action_precedes_unknown_collection():
    experience = build_decision_experience(
        evidence_decision=decision("BLOCK", "CONTRADICTED"),
        assessments=[
            Assessment("CODE_REGRESSION", "high", "NOT_APPLICABLE", False, 5.5)
        ],
        rerun_triggered=False,
        run_attempt=1,
        max_attempts=2,
    )

    assert experience["next_action"] == "INVESTIGATE_REGRESSION"


def test_evidence_unavailable_recommends_collection_and_card_is_compact():
    experience = build_decision_experience(
        evidence_decision=decision("BLOCK", "UNKNOWN"),
        assessments=[
            Assessment("EVIDENCE_UNAVAILABLE", "none", "UNAVAILABLE", False, 4.0)
        ],
        rerun_triggered=False,
        run_attempt=1,
        max_attempts=2,
    )

    assert experience["next_action"] == "COLLECT_MORE_EVIDENCE"
    assert experience["jobs"]["evidence_unavailable"] == 1

    card = render_decision_card(experience)
    assert "Decision at a glance" in card
    assert "`BLOCK`" in card
    assert "`COLLECT_MORE_EVIDENCE`" in card
    assert "4.00 min" in card
    assert "not labeled as saved" in card
