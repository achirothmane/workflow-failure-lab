"""Domain model: the innermost layer.

Imports nothing else from this package (implementation plan §3). Encodes the
three certainty terms fixed by ADR-0001 and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Classification(Enum):
    """The only three certainty values (ADR-0001, imported vocabulary)."""

    SUCCEEDED = "SUCCEEDED"
    FAILED_CONFIRMED = "FAILED_CONFIRMED"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True, slots=True)
class StepError:
    message: str
    kind: str | None = None


@dataclass(frozen=True, slots=True)
class Step:
    id: str
    name: str
    started_at: str
    finished_at: str | None
    status: str
    attempt: int
    error: StepError | None = None
    # Tri-state, as declared by the source system: True — the step performs an
    # external side effect (e.g. charging a card); False — explicitly declared
    # side-effect-free; None — not declared, therefore unknown.
    side_effect: bool | None = None


@dataclass(frozen=True, slots=True)
class Execution:
    id: str
    workflow_name: str
    started_at: str
    finished_at: str | None
    status: str
    steps: tuple[Step, ...]


@dataclass(frozen=True, slots=True)
class Evidence:
    """One input fact cited in support of (or against) a classification."""

    source: str
    detail: str
