from __future__ import annotations

import pytest

from easl_state_binding import (
    REASON_SUBJECT_STATE_CHANGED,
    StateBinding,
    StateBindingError,
    evaluate_required_state_bindings,
)


def test_matching_binding_remains_valid() -> None:
    result = evaluate_required_state_bindings(
        [StateBinding(id="target-state", expected="sha256:abc", observed="sha256:abc")],
        ["target-state"],
    )

    assert result == ()


def test_changed_binding_emits_subject_state_changed() -> None:
    result = evaluate_required_state_bindings(
        [
            StateBinding(
                id="target-state",
                expected="sha256:before",
                observed="sha256:after",
            )
        ],
        ["target-state"],
    )

    assert len(result) == 1
    assert result[0].state_binding_id == "target-state"
    assert result[0].reason == REASON_SUBJECT_STATE_CHANGED


def test_multiple_changed_bindings_preserve_required_order() -> None:
    result = evaluate_required_state_bindings(
        [
            StateBinding(id="run-attempt", expected="json:1", observed="json:2"),
            StateBinding(id="head-sha", expected='json:"abc"', observed='json:"def"'),
        ],
        ["head-sha", "run-attempt"],
    )

    assert [item.state_binding_id for item in result] == [
        "head-sha",
        "run-attempt",
    ]


def test_unknown_required_binding_is_structural_error() -> None:
    with pytest.raises(StateBindingError, match="unknown state binding"):
        evaluate_required_state_bindings([], ["missing"])


def test_duplicate_binding_id_is_structural_error() -> None:
    with pytest.raises(StateBindingError, match="duplicate state binding id"):
        evaluate_required_state_bindings(
            [
                StateBinding(id="target-state", expected="a", observed="a"),
                StateBinding(id="target-state", expected="a", observed="a"),
            ],
            ["target-state"],
        )


def test_empty_binding_token_is_structural_error() -> None:
    with pytest.raises(StateBindingError, match="requires expected and observed tokens"):
        evaluate_required_state_bindings(
            [StateBinding(id="target-state", expected="", observed="current")],
            ["target-state"],
        )
