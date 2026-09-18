from causal_dominance_shadow import (
    CausalDominanceShadowSummary,
    shadow_summary_payload,
)
from causal_dominance_validation import (
    MIN_INDEPENDENT_REAL_POSITIVE_CONTROLS_FOR_PRODUCTION,
    evaluate_validation,
    render_validation,
)


def clean_holdout():
    return {
        "repositories_requested": 50,
        "repositories_analyzed": 50,
        "repositories_skipped": 0,
        "qualifying": 0,
        "dominance_candidates": 0,
        "evaluable_candidates": 0,
        "validated_candidate_recoveries": 0,
        "candidate_failed_again": 0,
        "candidate_unknown_outcomes": 0,
        "observed_candidate_precision": 0.0,
        "authority_safe_validated_candidates": 0,
        "primary_deterministic_blocked": 0,
        "ordering_unproven": 0,
        "no_causal_5xx": 0,
        "unresolved": 0,
        "independent_candidate_runs": 0,
        "independent_candidate_repositories": 0,
    }


def test_positive_control_and_negative_controls_pass():
    summary = evaluate_validation()

    assert summary.controls_passed is True
    assert summary.evidence_ledger_ok is True
    assert summary.evidence_ledger_count == 11
    assert summary.evidence_wave_counts == ((1, 4), (2, 1), (3, 6))
    assert summary.independent_real_positive_controls == 1

    real = [item for item in summary.controls if item.real_case]
    assert len(real) == 1
    assert real[0].passed is True

    negatives = [item for item in summary.controls if not item.real_case]
    assert len(negatives) == 4
    assert all(item.passed for item in negatives)


def test_clean_holdout_still_does_not_promote_with_one_real_positive():
    summary = evaluate_validation(clean_holdout())

    assert summary.holdout_present is True
    assert summary.holdout_clean is True
    assert summary.production_promotion_ready is False
    assert (
        summary.independent_real_positive_controls
        < MIN_INDEPENDENT_REAL_POSITIVE_CONTROLS_FOR_PRODUCTION
    )

    report = render_validation(summary)
    assert "Validation mechanics pass" in report
    assert "need **2** more independent real causal-dominance positive" in report


def test_failed_again_holdout_fails_clean_gate():
    holdout = clean_holdout()
    holdout["dominance_candidates"] = 1
    holdout["evaluable_candidates"] = 1
    holdout["candidate_failed_again"] = 1

    summary = evaluate_validation(holdout)

    assert summary.holdout_clean is False
    assert "failed_again=1" in summary.holdout_reason
    assert summary.production_promotion_ready is False


def test_unknown_candidate_outcome_fails_clean_gate():
    holdout = clean_holdout()
    holdout["dominance_candidates"] = 1
    holdout["candidate_unknown_outcomes"] = 1

    summary = evaluate_validation(holdout)

    assert summary.holdout_clean is False
    assert "unknown_candidate_outcomes=1" in summary.holdout_reason


def test_shadow_payload_is_machine_readable():
    summary = CausalDominanceShadowSummary(records=())
    payload = shadow_summary_payload(
        summary,
        repositories_requested=50,
        repositories_analyzed=50,
        repositories_skipped=0,
    )

    assert payload["repositories_requested"] == 50
    assert payload["repositories_analyzed"] == 50
    assert payload["dominance_candidates"] == 0
    assert payload["candidate_failed_again"] == 0
    assert payload["unresolved"] == 0
