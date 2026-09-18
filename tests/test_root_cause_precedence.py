from ci_retry_gate import (
    FAILURE_STEP_CONFIRMED,
    assess_failure_step_provenance,
    classify_log,
    detect_side_effect_risk,
)
from mechanism_causality_gate import (
    MECHANISM_CAUSAL_CONFIRMED,
    assess_mechanism_causality,
)
from pinned_research_corpus import SWC_DPRINT_HTTP_504
from recovery_ground_truth import RECOVERY_VALIDATED, assess_recovery_ground_truth
from root_cause_precedence import (
    DOMINANCE_CANDIDATE,
    DOMINANCE_NOT_APPLICABLE,
    DOMINANCE_PRIMARY_DETERMINISTIC_EVIDENCE,
    assess_causal_dominance,
)
from transient_mechanism_gate import REASON_SERVER_5XX


def test_pinned_swc_504_is_a_causal_dominance_candidate():
    case = SWC_DPRINT_HTTP_504

    classification = classify_log(case.failure_log)
    assert classification.category == case.expected_runtime_category == "CODE_REGRESSION"

    mechanism = assess_mechanism_causality(case.failed_job, case.failure_log)
    assert mechanism.status == MECHANISM_CAUSAL_CONFIRMED
    assert REASON_SERVER_5XX in mechanism.reasons

    failure_step = assess_failure_step_provenance(case.failed_job)
    assert failure_step.status == FAILURE_STEP_CONFIRMED
    assert failure_step.step_name == "Run cargo test"

    recovery = assess_recovery_ground_truth(
        original_job=case.failed_job,
        failure_step_status=failure_step.status,
        failure_step=failure_step.step_name,
        rerun_observed=True,
        recovered=True,
        rerun_job=case.rerun_job,
    )
    assert recovery.status == case.expected_recovery_status == RECOVERY_VALIDATED

    side_effect, _evidence = detect_side_effect_risk(case.failed_job)
    assert side_effect is case.expected_side_effect_risk is False

    dominance = assess_causal_dominance(case.failed_job, case.failure_log)
    assert dominance.status == DOMINANCE_CANDIDATE
    assert dominance.baseline_category == "CODE_REGRESSION"
    assert dominance.proposed_category == "DEPENDENCY_NETWORK"
    assert dominance.failed_step == "Run cargo test"
    assert any("504" in line for line in dominance.transient_evidence)
    assert any("test failed" in line.lower() for line in dominance.downstream_evidence)


def test_primary_assertion_blocks_transient_dominance_even_if_504_appears():
    job = {
        "name": "unit tests",
        "steps": [
            {
                "name": "Run tests",
                "conclusion": "failure",
                "started_at": "2026-09-18T10:00:00Z",
                "completed_at": "2026-09-18T10:00:10Z",
            }
        ],
    }
    log = (
        "2026-09-18T10:00:02.0000000Z Error: assertion failed: left == right\n"
        "2026-09-18T10:00:03.0000000Z Error: HTTP 504 Gateway Timeout\n"
        "2026-09-18T10:00:04.0000000Z error: test failed, to rerun pass "
        "\`-p app --test unit\`\n"
    )

    classification = classify_log(log)
    assert classification.category == "CODE_REGRESSION"

    dominance = assess_causal_dominance(job, log)
    assert dominance.status == DOMINANCE_PRIMARY_DETERMINISTIC_EVIDENCE
    assert any("left == right" in line for line in dominance.blocking_evidence)


def test_strong_code_error_after_504_still_blocks_dominance():
    job = {
        "name": "build",
        "steps": [
            {
                "name": "Run build",
                "conclusion": "failure",
                "started_at": "2026-09-18T10:00:00Z",
                "completed_at": "2026-09-18T10:00:10Z",
            }
        ],
    }
    log = (
        "2026-09-18T10:00:02.0000000Z Error: HTTP 504 Gateway Timeout\n"
        "2026-09-18T10:00:03.0000000Z Error: TypeError: undefined is not a function\n"
        "2026-09-18T10:00:04.0000000Z error: test failed, to rerun pass "
        "\`-p app --test unit\`\n"
    )

    assert classify_log(log).category == "CODE_REGRESSION"
    dominance = assess_causal_dominance(job, log)
    assert dominance.status == DOMINANCE_PRIMARY_DETERMINISTIC_EVIDENCE
    assert any("TypeError" in line for line in dominance.blocking_evidence)


def test_unknown_server_5xx_does_not_use_dominance_override():
    job = {
        "name": "download",
        "steps": [
            {
                "name": "Download tool",
                "conclusion": "failure",
                "started_at": "2026-09-18T10:00:00Z",
                "completed_at": "2026-09-18T10:00:10Z",
            }
        ],
    }
    log = "2026-09-18T10:00:02.0000000Z Error: HTTP 500: Server Error\n"

    assert classify_log(log).category == "UNKNOWN"
    dominance = assess_causal_dominance(job, log)
    assert dominance.status == DOMINANCE_NOT_APPLICABLE
