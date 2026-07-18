"""Classify one execution from domain objects and collect the evidence.

Raw source-system statuses are data, not vocabulary (ADR-0001): the sets below
record which raw strings this analyzer accepts as evidence. Anything outside
both sets is ambiguous, and ambiguity classifies as INDETERMINATE — never as an
optimistic SUCCEEDED or a pessimistic FAILED_CONFIRMED.
"""

from __future__ import annotations

from dataclasses import dataclass

from workflow_failure_lab.domain import Classification, Evidence, Execution

_SUCCESS_STATUSES = frozenset({"succeeded", "success", "completed"})
_CONFIRMED_FAILURE_STATUSES = frozenset({"failed", "error"})


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    classification: Classification
    evidence: tuple[Evidence, ...]


def analyze(execution: Execution) -> AnalysisResult:
    ambiguities: list[Evidence] = []
    success_support: list[Evidence] = []
    confirmed_failures: list[Evidence] = []

    execution_status = execution.status.strip().lower()
    status_reads_success = execution_status in _SUCCESS_STATUSES
    status_reads_failure = execution_status in _CONFIRMED_FAILURE_STATUSES

    if not status_reads_success and not status_reads_failure:
        ambiguities.append(
            Evidence(
                "execution.status",
                f"raw status '{execution.status}' proves neither success nor confirmed failure",
            )
        )
    if execution.finished_at is None:
        ambiguities.append(
            Evidence(
                "execution.finished_at",
                "missing: the execution is not proven to have completed",
            )
        )
    if not execution.steps:
        ambiguities.append(
            Evidence("steps", "empty: no step evidence to support any conclusion")
        )

    for index, step in enumerate(execution.steps):
        where = f"steps[{index}] ('{step.name}')"
        step_status = step.status.strip().lower()
        if step.finished_at is None:
            ambiguities.append(
                Evidence(
                    f"{where}.finished_at",
                    f"missing (raw status '{step.status}'): the step is not proven "
                    "to have completed; a side effect may or may not have occurred",
                )
            )
            if step.error is not None:
                ambiguities.append(
                    Evidence(
                        f"{where}.error",
                        f"recorded error does not confirm the outcome: {step.error.message}",
                    )
                )
        elif step_status in _SUCCESS_STATUSES:
            success_support.append(
                Evidence(
                    f"{where}.status",
                    f"recorded terminal status '{step.status}' with finished_at present",
                )
            )
        elif step_status in _CONFIRMED_FAILURE_STATUSES:
            if step.error is not None:
                confirmed_failures.append(
                    Evidence(
                        f"{where}.error",
                        f"terminal status '{step.status}' with recorded error: "
                        f"{step.error.message}",
                    )
                )
            else:
                ambiguities.append(
                    Evidence(
                        f"{where}.status",
                        f"raw status '{step.status}' but no recorded error to confirm "
                        "the failure",
                    )
                )
        else:
            ambiguities.append(
                Evidence(
                    f"{where}.status",
                    f"raw status '{step.status}' proves neither success nor confirmed failure",
                )
            )

    if ambiguities:
        return AnalysisResult(Classification.INDETERMINATE, tuple(ambiguities))

    if status_reads_failure and confirmed_failures:
        evidence = [
            Evidence(
                "execution.status",
                f"recorded terminal status '{execution.status}' with finished_at present",
            ),
            *confirmed_failures,
        ]
        return AnalysisResult(Classification.FAILED_CONFIRMED, tuple(evidence))

    if status_reads_success and not confirmed_failures:
        evidence = [
            Evidence(
                "execution.status",
                f"recorded terminal status '{execution.status}' with finished_at present",
            ),
            *success_support,
        ]
        return AnalysisResult(Classification.SUCCEEDED, tuple(evidence))

    # Execution status and step evidence contradict each other.
    contradiction = [
        Evidence(
            "execution.status",
            f"raw status '{execution.status}' contradicts the step evidence below",
        ),
        *success_support,
        *confirmed_failures,
    ]
    return AnalysisResult(Classification.INDETERMINATE, tuple(contradiction))
