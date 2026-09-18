from __future__ import annotations

from dataclasses import dataclass

from ci_retry_gate import PROVENANCE_CONFIRMED


RECOVERY_VALIDATED = "VALIDATED_RECOVERY"
RECOVERY_NOT_RECOVERED = "NOT_RECOVERED"
RECOVERY_UNVERIFIED = "UNVERIFIED_RECOVERY"
RECOVERY_INCONSISTENT = "INCONSISTENT_RECOVERY"
RECOVERY_NOT_OBSERVED = "NOT_OBSERVED"


@dataclass(frozen=True)
class RecoveryGroundTruth:
    status: str
    evidence: tuple[str, ...] = ()


def later_rerun_result(
    attempt_jobs: dict[int, list[dict]],
    current_attempt: int,
    attempts: int,
    job_name: str,
    original_started_at: str,
) -> tuple[bool, bool, dict | None]:
    """Return a genuine later execution of the same job, ignoring copied untouched jobs."""
    observed = False
    for later_attempt in range(current_attempt + 1, attempts + 1):
        for candidate in attempt_jobs.get(later_attempt, []):
            if str(candidate.get("name") or "") != job_name:
                continue
            later_started_at = str(candidate.get("started_at") or "")
            if not later_started_at or later_started_at == original_started_at:
                continue
            observed = True
            if str(candidate.get("conclusion") or "").lower() == "success":
                return True, True, candidate
    return observed, False, None


def assess_recovery_ground_truth(
    *,
    original_job: dict,
    provenance_status: str,
    provenance_step: str,
    rerun_observed: bool,
    recovered: bool,
    rerun_job: dict | None,
) -> RecoveryGroundTruth:
    """Validate that a later success re-executed the operation tied to the original failure."""
    if not rerun_observed:
        return RecoveryGroundTruth(
            RECOVERY_NOT_OBSERVED,
            ("No genuine later execution of the same job was observed.",),
        )

    if not recovered:
        return RecoveryGroundTruth(
            RECOVERY_NOT_RECOVERED,
            ("A genuine later execution was observed, but it did not succeed.",),
        )

    if provenance_status != PROVENANCE_CONFIRMED or not provenance_step:
        return RecoveryGroundTruth(
            RECOVERY_UNVERIFIED,
            (
                "The later job succeeded, but the original failure was not bound "
                "to a confirmed failed step.",
            ),
        )

    if rerun_job is None:
        return RecoveryGroundTruth(
            RECOVERY_UNVERIFIED,
            ("The later success was observed without inspectable rerun-job metadata.",),
        )

    rerun_steps = list(rerun_job.get("steps") or [])
    if not rerun_steps:
        return RecoveryGroundTruth(
            RECOVERY_UNVERIFIED,
            ("The later successful job had no inspectable step metadata.",),
        )

    matching_steps = [
        step
        for step in rerun_steps
        if str(step.get("name") or "") == provenance_step
    ]
    if not matching_steps:
        return RecoveryGroundTruth(
            RECOVERY_INCONSISTENT,
            (
                f"The later job succeeded, but the original failed step "
                f"{provenance_step!r} was not re-executed.",
            ),
        )

    for step in matching_steps:
        if str(step.get("conclusion") or "").lower() == "success":
            return RecoveryGroundTruth(
                RECOVERY_VALIDATED,
                (
                    f"Original failed step: {provenance_step}",
                    "The same step was re-executed in the later attempt and succeeded.",
                ),
            )

    conclusions = ", ".join(
        sorted(
            {
                str(step.get("conclusion") or "unknown").lower()
                for step in matching_steps
            }
        )
    )
    return RecoveryGroundTruth(
        RECOVERY_INCONSISTENT,
        (
            f"The later job succeeded, but the matching step did not: {conclusions}.",
        ),
    )


def is_validated_recovery(status: str) -> bool:
    return status == RECOVERY_VALIDATED


def is_ground_truth_evaluable(status: str) -> bool:
    return status in {RECOVERY_VALIDATED, RECOVERY_NOT_RECOVERED}
