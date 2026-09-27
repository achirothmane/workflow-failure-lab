from __future__ import annotations

import json
from pathlib import Path

import pytest

from easl_state_binding import (
    REASON_SUBJECT_STATE_CHANGED,
    StateBinding,
    StateBindingError,
    evaluate_required_state_bindings,
)


CONFORMANCE_PATH = (
    Path(__file__).parent / "conformance" / "easl" / "subject_state_binding.json"
)


def _load_vectors() -> dict:
    payload = json.loads(CONFORMANCE_PATH.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["primitive"] == "subject_state_binding"
    return payload


VECTORS = _load_vectors()


@pytest.mark.parametrize(
    "case",
    VECTORS["cases"],
    ids=[case["name"] for case in VECTORS["cases"]],
)
def test_python_consumer_matches_easl_subject_state_conformance(case: dict) -> None:
    bindings = [StateBinding(**item) for item in case["bindings"]]

    expected_error = case.get("want_error_contains")
    if expected_error:
        with pytest.raises(StateBindingError, match=expected_error):
            evaluate_required_state_bindings(bindings, case["required"])
        return

    result = evaluate_required_state_bindings(bindings, case["required"])

    invalidated = sorted(item.state_binding_id for item in result)
    expected_invalidated = sorted(case["want_invalidated_bindings"])
    assert invalidated == expected_invalidated
    assert all(item.reason == REASON_SUBJECT_STATE_CHANGED for item in result)

    actual_state = "INVALID" if result else "VALID"
    actual_evidence_status = "INSUFFICIENT" if result else "SUFFICIENT"

    assert actual_state == case["want_state"]
    assert actual_evidence_status == case["want_evidence_status"]
