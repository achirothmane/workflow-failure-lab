"""B3 retry-policy tests: exhaustive per-value decisions, structural coverage
of the enum, and fail-closed rejection of anything that is not a member.
"""

from __future__ import annotations

import pytest

from workflow_failure_lab.domain import Classification
from workflow_failure_lab.retry_policy import RetryDecision, decide

# Expected (retry_permitted, reconciliation_required) per ADR-0001.
EXPECTED_DECISIONS: dict[Classification, tuple[bool, bool]] = {
    Classification.SUCCEEDED: (False, False),
    Classification.FAILED_CONFIRMED: (True, False),
    Classification.INDETERMINATE: (False, True),
}


def test_expected_decisions_cover_every_classification() -> None:
    """Fails automatically when a new enum value lands without a policy update."""
    assert set(EXPECTED_DECISIONS) == set(Classification)


@pytest.mark.parametrize(
    ("classification", "retry_permitted", "reconciliation_required"),
    [
        (classification, retry, reconciliation)
        for classification, (retry, reconciliation) in EXPECTED_DECISIONS.items()
    ],
    ids=[classification.value for classification in EXPECTED_DECISIONS],
)
def test_decide_for_each_classification(
    classification: Classification,
    retry_permitted: bool,
    reconciliation_required: bool,
) -> None:
    decision = decide(classification)

    assert isinstance(decision, RetryDecision)
    assert decision.retry_permitted is retry_permitted
    assert decision.reconciliation_required is reconciliation_required
    assert decision.rule


@pytest.mark.parametrize(
    "not_a_classification",
    [None, "FAILED_CONFIRMED", 0, object()],
    ids=["none", "string", "int", "object"],
)
def test_decide_rejects_non_classification_values(
    not_a_classification: object,
) -> None:
    with pytest.raises(TypeError):
        decide(not_a_classification)  # type: ignore[arg-type]
