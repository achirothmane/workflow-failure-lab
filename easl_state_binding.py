"""Portable consumer of the EASL subject-state binding invariant.

This module mirrors only the domain-neutral primitive introduced by EASL:
an assumption that requires a subject-state binding remains justified only
while the opaque expected and observed tokens match.

It intentionally does not implement the rest of EASL. The Go module remains
the reference implementation; this compatibility layer exists so the Python
CI Retry Gate can consume the same invariant without importing Kubernetes- or
CI-specific comparison semantics back into the gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


REASON_SUBJECT_STATE_CHANGED = "SUBJECT_STATE_CHANGED"


class StateBindingError(ValueError):
    """Raised when the subject-state binding contract is structurally invalid."""


@dataclass(frozen=True, slots=True)
class StateBinding:
    id: str
    expected: str
    observed: str


@dataclass(frozen=True, slots=True)
class StateBindingInvalidation:
    state_binding_id: str
    reason: str = REASON_SUBJECT_STATE_CHANGED


def evaluate_required_state_bindings(
    bindings: Iterable[StateBinding],
    required_ids: Iterable[str],
) -> tuple[StateBindingInvalidation, ...]:
    """Evaluate the EASL subject-state binding invariant.

    Contract mirrored from EASL:
    - binding IDs must be non-empty and unique;
    - expected/observed opaque tokens must be non-empty;
    - required binding references must exist;
    - expected != observed invalidates with SUBJECT_STATE_CHANGED.
    """
    by_id: dict[str, StateBinding] = {}
    for binding in bindings:
        if not binding.id:
            raise StateBindingError("empty state binding id")
        if not binding.expected or not binding.observed:
            raise StateBindingError(
                f"state binding {binding.id!r} requires expected and observed tokens"
            )
        if binding.id in by_id:
            raise StateBindingError(f"duplicate state binding id {binding.id!r}")
        by_id[binding.id] = binding

    invalidations: list[StateBindingInvalidation] = []
    for binding_id in required_ids:
        if not binding_id:
            raise StateBindingError("empty required state binding id")
        binding = by_id.get(binding_id)
        if binding is None:
            raise StateBindingError(
                f"requires unknown state binding {binding_id!r}"
            )
        if binding.expected != binding.observed:
            invalidations.append(
                StateBindingInvalidation(state_binding_id=binding_id)
            )

    return tuple(invalidations)
