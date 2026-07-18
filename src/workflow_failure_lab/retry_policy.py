"""Apply ADR-0001's two binding rules to a classification. Nothing else."""

from __future__ import annotations

from dataclasses import dataclass

from workflow_failure_lab.domain import Classification

RETRY_RULE = (
    "Retry is permitted if and only if the previous attempt is FAILED_CONFIRMED."
)
RECONCILIATION_RULE = (
    "INDETERMINATE requires reconciliation — checking the external system before "
    "attempting the action again. Blind retry is forbidden when the result is "
    "INDETERMINATE."
)


@dataclass(frozen=True, slots=True)
class RetryDecision:
    retry_permitted: bool
    reconciliation_required: bool
    rule: str


def decide(classification: Classification) -> RetryDecision:
    # Fail closed: anything that is not a Classification member — including
    # None and raw strings — is rejected before any matching happens.
    if not isinstance(classification, Classification):
        raise TypeError(
            "decide() requires a Classification member, got "
            f"{type(classification).__name__}: {classification!r}"
        )
    match classification:
        case Classification.FAILED_CONFIRMED:
            return RetryDecision(
                retry_permitted=True, reconciliation_required=False, rule=RETRY_RULE
            )
        case Classification.INDETERMINATE:
            return RetryDecision(
                retry_permitted=False,
                reconciliation_required=True,
                rule=RECONCILIATION_RULE,
            )
        case Classification.SUCCEEDED:
            return RetryDecision(
                retry_permitted=False, reconciliation_required=False, rule=RETRY_RULE
            )
