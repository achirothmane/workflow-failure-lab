from recovery_ground_truth import (
    RECOVERY_INCONSISTENT,
    RECOVERY_NOT_OBSERVED,
    RECOVERY_NOT_RECOVERED,
    RECOVERY_UNVERIFIED,
    RECOVERY_VALIDATED,
    assess_recovery_ground_truth,
    later_rerun_result,
)


def failed_job():
    return {
        "name": "tests",
        "started_at": "2026-09-18T01:00:00Z",
        "conclusion": "failure",
        "steps": [
            {
                "name": "Install dependencies",
                "conclusion": "failure",
            }
        ],
    }


def successful_rerun(step_name="Install dependencies", step_conclusion="success"):
    return {
        "name": "tests",
        "started_at": "2026-09-18T01:02:00Z",
        "conclusion": "success",
        "steps": [
            {
                "name": step_name,
                "conclusion": step_conclusion,
            }
        ],
    }


def test_validated_recovery_requires_same_failed_step_to_succeed():
    result = assess_recovery_ground_truth(
        original_job=failed_job(),
        provenance_status="CONFIRMED",
        provenance_step="Install dependencies",
        rerun_observed=True,
        recovered=True,
        rerun_job=successful_rerun(),
    )

    assert result.status == RECOVERY_VALIDATED
    assert any("same step" in item.lower() for item in result.evidence)


def test_success_without_confirmed_original_provenance_is_unverified():
    result = assess_recovery_ground_truth(
        original_job=failed_job(),
        provenance_status="MISMATCH",
        provenance_step="Install dependencies",
        rerun_observed=True,
        recovered=True,
        rerun_job=successful_rerun(),
    )

    assert result.status == RECOVERY_UNVERIFIED


def test_success_without_reexecuting_original_failed_step_is_inconsistent():
    result = assess_recovery_ground_truth(
        original_job=failed_job(),
        provenance_status="CONFIRMED",
        provenance_step="Install dependencies",
        rerun_observed=True,
        recovered=True,
        rerun_job=successful_rerun(step_name="Compile"),
    )

    assert result.status == RECOVERY_INCONSISTENT


def test_failed_real_rerun_is_ground_truth_not_recovered():
    result = assess_recovery_ground_truth(
        original_job=failed_job(),
        provenance_status="CONFIRMED",
        provenance_step="Install dependencies",
        rerun_observed=True,
        recovered=False,
        rerun_job=None,
    )

    assert result.status == RECOVERY_NOT_RECOVERED


def test_no_real_rerun_stays_not_observed():
    result = assess_recovery_ground_truth(
        original_job=failed_job(),
        provenance_status="CONFIRMED",
        provenance_step="Install dependencies",
        rerun_observed=False,
        recovered=False,
        rerun_job=None,
    )

    assert result.status == RECOVERY_NOT_OBSERVED


def test_later_rerun_result_ignores_copied_job_and_returns_real_success_job():
    attempts = {
        1: [],
        2: [
            {
                "name": "tests",
                "started_at": "2026-09-18T01:00:00Z",
                "conclusion": "failure",
            }
        ],
        3: [
            successful_rerun(),
        ],
    }

    observed, recovered, job = later_rerun_result(
        attempts,
        current_attempt=1,
        attempts=3,
        job_name="tests",
        original_started_at="2026-09-18T01:00:00Z",
    )

    assert observed is True
    assert recovered is True
    assert job is not None
    assert job["started_at"] == "2026-09-18T01:02:00Z"
