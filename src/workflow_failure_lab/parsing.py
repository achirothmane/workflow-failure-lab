"""Read and validate the input file, map raw JSON to domain objects.

Interpreting what a raw status *means* is analysis's job, not this module's
(implementation plan §2).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

from workflow_failure_lab.domain import Execution, Step, StepError


class InputError(Exception):
    """The input file could not be read, parsed as JSON, or schema-validated."""


EXECUTION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["execution", "steps"],
    "additionalProperties": False,
    "properties": {
        "execution": {
            "type": "object",
            "required": ["id", "workflow_name", "started_at", "finished_at", "status"],
            "additionalProperties": False,
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "workflow_name": {"type": "string", "minLength": 1},
                "started_at": {"type": "string", "minLength": 1},
                "finished_at": {"type": ["string", "null"], "minLength": 1},
                "status": {"type": "string", "minLength": 1},
            },
        },
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "name", "started_at", "finished_at", "status", "attempt"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "name": {"type": "string", "minLength": 1},
                    "started_at": {"type": "string", "minLength": 1},
                    "finished_at": {"type": ["string", "null"], "minLength": 1},
                    "status": {"type": "string", "minLength": 1},
                    "attempt": {"type": "integer", "minimum": 1},
                    "side_effect": {
                        "type": "boolean",
                        "description": (
                            "Declared by the source system: true when the step "
                            "performs an external side effect (e.g. charging a "
                            "card), false when explicitly side-effect-free. "
                            "Absent means unknown."
                        ),
                    },
                    "error": {
                        "type": "object",
                        "required": ["message"],
                        "additionalProperties": False,
                        "properties": {
                            "message": {"type": "string", "minLength": 1},
                            "kind": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
        },
    },
}

_VALIDATOR = Draft202012Validator(EXECUTION_SCHEMA)


def load_execution(path: str | Path) -> Execution:
    """Load, validate, and map one execution file; raise InputError otherwise."""
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"cannot read {file}: {exc}") from exc

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"{file} is not valid JSON: {exc}") from exc

    error = best_match(_VALIDATOR.iter_errors(raw))
    if error is not None:
        raise InputError(
            f"{file} failed schema validation at {error.json_path}: {error.message}"
        ) from error

    return _to_domain(raw)


def _to_domain(raw: dict[str, Any]) -> Execution:
    execution = raw["execution"]
    return Execution(
        id=execution["id"],
        workflow_name=execution["workflow_name"],
        started_at=execution["started_at"],
        finished_at=execution["finished_at"],
        status=execution["status"],
        steps=tuple(_step_to_domain(step) for step in raw["steps"]),
    )


def _step_to_domain(raw_step: dict[str, Any]) -> Step:
    raw_error = raw_step.get("error")
    error = (
        StepError(message=raw_error["message"], kind=raw_error.get("kind"))
        if raw_error is not None
        else None
    )
    return Step(
        id=raw_step["id"],
        name=raw_step["name"],
        started_at=raw_step["started_at"],
        finished_at=raw_step["finished_at"],
        status=raw_step["status"],
        attempt=raw_step["attempt"],
        error=error,
        # .get without a bool default: an absent key stays None (unknown),
        # preserving the tri-state declared in the domain model.
        side_effect=raw_step.get("side_effect"),
    )
